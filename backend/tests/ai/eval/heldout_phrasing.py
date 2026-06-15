"""heldout-v1 自然语言表达层：把 IntentSpec 渲染成口语化、带扰动的 query。

与 cases_generator 的模板**刻意不同**（不同句式骨架、不同词库），避免题库重叠。
每个正向能力 6-8 个骨架、边界方向 4 个骨架，叠加前后缀/错别字/语序扰动，
配合生成器的拒绝采样保证整句零重复（防"题量虚胖"）。
所有随机来自传入的 Random(seed)，保证可复现。本模块禁止 import llm_planner。
"""

from __future__ import annotations

from random import Random

from tests.ai.eval.heldout_intents import IntentSpec


# 礼貌/啰嗦包裹前后缀（测试模型能否从噪声里抽出真实意图）。
_PREFIXES = ("", "麻烦了，", "辛苦帮个忙，", "嗨，那个，", "在吗？想请教下，", "急用，", "对了，")
_SUFFIXES = ("", " 谢谢啦", " 越快越好", "，先这样", "，拜托拜托", " 麻烦尽快", "，今天要")
# 错别字替换表（轻度脏输入，只动中文词，不碰 ID）。
_TYPO_MAP = {"影像": "影象", "计算": "计祘", "检测": "检侧", "重投影": "重头影", "文档": "文挡", "掩膜": "掩模"}


def _maybe_typo(text: str, rng: Random, prob: float) -> str:
    if rng.random() >= prob:
        return text
    for src, dst in _TYPO_MAP.items():
        if src in text:
            return text.replace(src, dst, 1)
    return text


def _wrap(text: str, rng: Random) -> str:
    return f"{rng.choice(_PREFIXES)}{text}{rng.choice(_SUFFIXES)}"


# ---------------------------------------------------------------------------
# 正向单工具骨架库（每能力 6-8 个，口语化，与 dev-set 模板不同骨架）。
POSITIVE_BANKS: dict[str, tuple[str, ...]] = {
    "raster_inspect": (
        "这景 {img} 到底几个波段、什么投影，给我看下基本信息",
        "我想先摸清 {img} 的底细，分辨率、范围、坐标系都报一下",
        "{img} 的元数据帮我拉出来看看",
        "上传的 {img} 是多少波段的？顺便看下 CRS",
        "先核对一下 {img} 的影像参数再说别的",
        "{img} 这景图的基本属性查一下，宽高波段那些",
        "帮我确认 {img} 的投影和覆盖范围对不对",
        "查询影像 {img} 的 profile 信息",
    ),
    "calculate_ndvi": (
        "{img} 这块地的植被长势咋样，跑个 NDVI 看看",
        "帮忙出一下 {img} 的归一化植被指数",
        "我要 {img} 的 NDVI 结果图",
        "给 {img} 算下植被指数 NDVI，看看绿化情况",
        "{img} 的 ndvi 跑一下呗，急等",
        "评估下 {img} 的植被覆盖，用 NDVI 就行",
        "麻烦对 {img} 执行 NDVI 计算",
        "看下 {img} 里植被健康度，先出 NDVI",
    ),
    "calculate_spectral_index": (
        "{img} 我想看 {term}，麻烦算一下",
        "对 {img} 来个 {term} 的结果",
        "帮我把 {img} 的 {term} 跑出来",
        "{img} 需要做 {term} 分析",
        "出一份 {img} 的 {term} 图",
        "算 {term} 吧，影像是 {img}",
        "{img} 这景，{term} 安排上",
    ),
    "render_band_composite": (
        "把 {img} 弄成{term}图我瞅瞅",
        "{img} 出个{term}预览",
        "给 {img} 做{term}显示",
        "我想看 {img} 的{term}效果",
        "{img} 渲染成{term}发我",
        "用{term}方案把 {img} 显示出来",
        "{term}合成图来一张，用 {img}",
    ),
    "cloud_shadow_mask": (
        "{img} 好像有云，先把云和阴影圈出来质检下",
        "想确认 {img} 是不是被云挡了，做个掩膜",
        "给 {img} 跑一遍云阴影检测",
        "{img} 的云量情况出个掩膜评估下",
        "查下 {img} 哪些区域被云污染了",
        "对 {img} 做去云前的云检测",
        "{img} 需要云和云影的质检掩膜",
    ),
    "extract_water_mask": (
        "{img} 里的水面范围帮我勾出来",
        "把 {img} 的河湖水域提取一下",
        "{img} 哪里是水，出个水体掩膜",
        "提取 {img} 的水体分布",
        "我要 {img} 的水域边界图层",
        "圈一下 {img} 里的湖泊河流范围",
        "{img} 做水体提取，掩膜给我",
    ),
    "clip_reproject_raster": (
        "{img} 帮我换到 {crs} 这个坐标系",
        "把 {img} 重投到 {crs}",
        "{img} 转成 {crs} 的投影",
        "需要把 {img} 的坐标系改成 {crs}",
        "对 {img} 做投影转换，目标 {crs}",
        "{img} 现在的投影不对，统一到 {crs}",
        "重投影：{img} 转 {crs}，谢谢",
    ),
    "detect_objects": (
        "{img} 里有没有{target}，帮我框出来",
        "扫一下 {img} 看看{target}在哪",
        "检出 {img} 中所有{target}的位置",
        "{img} 这景找{target}，标出来",
        "数一数 {img} 里有多少{target}",
        "帮我定位 {img} 中的{target}",
        "{img} 目标排查：重点是{target}",
    ),
    "segment_landcover": (
        "{img} 给我分一下地表类别，哪块是建筑哪块是植被",
        "对 {img} 做土地覆盖分区",
        "{img} 整景做地物分类分割",
        "把 {img} 按地类切成一块块的",
        "我要 {img} 的 landcover 分割结果",
        "{img} 的地表覆盖类型图做一份",
        "给 {img} 跑语义分割，分地物类型",
    ),
    "ocr_recognize": (
        "{img} 这张扫描图上的字帮我读出来",
        "认一下 {img} 上面标注的地名文字",
        "{img} 里印的文字内容提取一下",
        "把 {img} 图面上的注记识别出来",
        "{img} 上写了什么字？OCR 一下",
        "读取 {img} 中的文字标注信息",
        "{img} 的图廓注记帮我转成文本",
    ),
    "parse_document": (
        "我传的那份文档 {doc}，帮我把要点捋一捋",
        "{doc} 这个文件太长了，概括下重点",
        "总结一下文档 {doc} 讲了什么",
        "文档 {doc} 的核心内容提炼出来",
        "把 {doc} 里的章节要点列一列",
        "帮我读文档 {doc}，给个摘要",
        "{doc} 内容整理成几条要点",
    ),
    "web_search": (
        "后天广州会不会下暴雨，出门要不要带伞",
        "查查 2026 年新发布的开源遥感数据集有哪些",
        "最近高分卫星影像的官方采购价格是多少",
        "今年自然资源部有没有出新的遥感监测政策",
        "下周成都的天气趋势帮我查下",
        "这两天哪里有台风预警，查一下",
        "搜下最新的 Landsat 数据下载渠道变化",
        "帮我查今天北京的空气质量指数",
    ),
}

_SPECTRAL_TERMS = {
    "nbr": "火烧迹地指数 NBR",
    "ndwi": "水体指数 NDWI",
    "ndbi": "建筑指数 NDBI",
    "evi": "增强植被指数 EVI",
    "savi": "土壤调节植被 SAVI",
    "ndmi": "水分指数 NDMI",
}
_COMPOSITE_TERMS = {"true_color": "真彩色", "false_color": "假彩色"}
_DETECT_TARGETS = ("飞机", "船", "车", "油罐", "桥")


def realize_positive(intent: IntentSpec, *, img: str | None, doc: str | None, rng: Random) -> str:
    templates = POSITIVE_BANKS[intent.wants]  # type: ignore[index]
    tpl = rng.choice(templates)
    term = ""
    if intent.wants == "calculate_spectral_index":
        term = _SPECTRAL_TERMS[str(intent.arguments.get("index_type"))]
    elif intent.wants == "render_band_composite":
        term = _COMPOSITE_TERMS[str(intent.arguments.get("mode"))]
    target = rng.choice(_DETECT_TARGETS)
    crs = str(intent.arguments.get("dst_crs", ""))
    text = tpl.format(img=img or "", doc=doc or "", term=term, target=target, crs=crs)
    text = _maybe_typo(text, rng, 0.25)
    return _wrap(text, rng)


# ---------------------------------------------------------------------------
# hard_negative 骨架库。
NEGATION_BANK = (
    "先别动手算，就跟我讲讲 {topic} 是怎么回事",
    "我现在不需要你跑 {topic}，只想听原理",
    "{topic} 别处理，解释清楚概念就行",
    "不用调用什么工具，{topic} 的思路给我讲讲",
    "先不要执行 {topic}，说说它适合什么场景",
    "停，{topic} 这步先不做，原理是什么",
)
CONCEPT_BANK = (
    "{topic} 在遥感里到底意味着什么",
    "想了解下 {topic} 这个概念，别给我跑数据",
    "科普一下 {topic} 呗",
    "{topic} 和普通照片处理的区别是啥",
    "为什么大家都用 {topic}，优缺点呢",
    "{topic} 的取值范围一般是多少，怎么解读",
)
MISSING_ID_EMPTY_BANK = (
    "把刚说的那张图做个 {task}",
    "上面那景影像帮我跑 {task}，对了我还没给你 ID",
    "处理一下我那张图的 {task}",
)
# 清单里有图但用户只用指代词——直压 v1 "不许自动映射唯一影像" 规则。
MISSING_ID_PRONOUN_BANK = (
    "就这张图，跑 {task}",
    "对刚才传的那个直接做 {task}",
    "那张图的 {task} 安排一下",
)
NON_OWNER_BANK = (
    "影像 {img} 帮我算个 {task}",
    "{img} 这景做一下 {task}",
    "用 {img} 跑 {task}",
    "{img}，任务是{task}，开始吧",
    "麻烦处理 {img} 的{task}",
)
GENERAL_BANK = (
    "给我写段项目周报开头",
    "把 land cover 翻译成中文",
    "用 python 写个二分查找",
    "讲讲什么是过拟合",
    "算下 3721 加 8964 等于几",
    "推荐几本科幻小说",
    "帮我润色一段答辩稿",
    "Excel 怎么做数据透视表",
)
CONTRADICTION_BANK = (
    "用 NDVI 这个算法看看 {img} 里有几条船",
    "拿云掩膜工具把文档 {doc} 总结一下",
    "用 OCR 帮我判断 {img} 的植被覆盖多少",
    "靠重投影功能数一数 {img} 里的车",
    "用水体提取工具识别 {img} 里的飞机",
    "拿波段合成功能翻译文档 {doc}",
)

_NEG_TOPICS = ("NDVI", "水体提取", "云掩膜", "目标检测", "地物分割")
_CONCEPT_TOPICS = ("近红外波段", "NDVI", "假彩色", "云阴影", "NBR")
_NEG_TASKS = ("NDVI", "水体掩膜", "地物分割", "云检测", "重投影")

# task 文本 -> 该 task 对应的 capability。missing_id/corrupted_id 在新口径（唯一图+残缺ID/指代→call
# 补全）下，标注 capability 必须跟 query 里实际写的 task 走，不能写死。重投影需 dst_crs，单列默认值。
_TASK_TO_CAPABILITY = {
    "NDVI": ("calculate_ndvi", {}),
    "水体掩膜": ("extract_water_mask", {}),
    "地物分割": ("segment_landcover", {}),
    "云检测": ("cloud_shadow_mask", {}),
    "重投影": ("clip_reproject_raster", {"dst_crs": "EPSG:4326"}),
}

# 补全口径专用 task 子集：只含单参工具，不含重投影（dst_crs 在指代/缺ID语境下无法确定）。
_CALL_COMPLETION_TASKS = ("NDVI", "水体掩膜", "地物分割", "云检测")


def task_capability(task: str) -> tuple[str, dict]:
    """task 文本 → (capability, arguments)。供 missing_id/corrupted_id 调用方推导标注，
    保证 query 写的 task 与 expected_capability 同源（修写死 calculate_ndvi 的根因）。"""
    cap, args = _TASK_TO_CAPABILITY[task]
    return cap, dict(args)


def realize_negation(rng: Random) -> str:
    return _wrap(rng.choice(NEGATION_BANK).format(topic=rng.choice(_NEG_TOPICS)), rng)


def realize_concept(rng: Random) -> str:
    return _wrap(rng.choice(CONCEPT_BANK).format(topic=rng.choice(_CONCEPT_TOPICS)), rng)


def realize_missing_id(rng: Random, *, pronoun_variant: bool) -> tuple[str, str]:
    """返回 (query, task)。task 供调用方推导 capability，避免写死与 query 脱钩。

    不含"重投影"——它需 query 里没有的 dst_crs，指代/缺ID 语境下无法给出确定目标坐标系，
    强标 EPSG:4326 会制造新错标。只用 4 个单参 task（NDVI/水体掩膜/地物分割/云检测）。
    """
    bank = MISSING_ID_PRONOUN_BANK if pronoun_variant else MISSING_ID_EMPTY_BANK
    task = rng.choice(_CALL_COMPLETION_TASKS)
    return _wrap(rng.choice(bank).format(task=task), rng), task


def realize_non_owner(rng: Random, *, img: str) -> str:
    return _wrap(rng.choice(NON_OWNER_BANK).format(img=img, task=rng.choice(_NEG_TASKS)), rng)


def realize_general(rng: Random) -> str:
    return _wrap(rng.choice(GENERAL_BANK), rng)


def realize_contradiction(rng: Random, *, img: str, doc: str) -> str:
    return _wrap(rng.choice(CONTRADICTION_BANK).format(img=img, doc=doc), rng)


# ---------------------------------------------------------------------------
# 边界歧义：方向化骨架（提到易混概念但明确只要其中一个工具）。
BOUNDARY_BANKS: dict[str, tuple[str, ...]] = {
    "ocr_not_detect": (
        "{img} 上的文字给我读出来，不是让你找飞机",
        "我要 {img} 的图面注记内容，别做目标检测",
        "认字！{img} 里印的地名，不是检测车辆",
        "{img} 这图我只关心上面写了啥字，目标别管",
    ),
    "detect_not_ocr": (
        "{img} 里把船找出来，我不要图上的文字",
        "检测 {img} 的飞机位置，注记文字不用管",
        "{img} 找目标：车辆，别给我做 OCR",
        "框出 {img} 中的油罐，文字识别就免了",
    ),
    "water_not_index": (
        "我要 {img} 水域的范围掩膜，不是算什么指数",
        "把 {img} 的水体边界提出来，别只给 NDWI 数值",
        "{img} 圈水域，要掩膜结果不要指数图",
        "提取 {img} 实际的水面分布，不是指数计算",
    ),
    "index_not_water": (
        "只要 {img} 的 NDWI 指数，不用提取水体矢量",
        "{img} 算个 NDWI 就行，别做水域提取",
        "给 {img} 出 NDWI 指数图，水体掩膜不需要",
        "{img} 我要的是水体指数分布，不是范围圈定",
    ),
    "segment_not_detect": (
        "{img} 整幅按地类分块，不是找单个目标",
        "对 {img} 做整图地物分割，不要目标框",
        "{img} 我要地表分类图，别给我检测结果",
        "把 {img} 的建筑植被水体分区，不是数飞机",
    ),
    "detect_not_segment": (
        "只找 {img} 里的船，不用整图分类",
        "{img} 检测桥梁就好，地物分割先不做",
        "定位 {img} 中的飞机，不需要 landcover",
        "{img} 找车，别跑分割",
    ),
    "parse_not_ocr": (
        "文档 {doc} 给我总结要点，不是图片认字",
        "{doc} 是个 PDF，提炼内容，不用 OCR 影像",
        "帮我梳理文档 {doc} 的结构，这不是扫描图识字",
        "{doc} 文档解析走起，要章节摘要",
    ),
    "ocr_not_parse": (
        "{img} 是张扫描地图，读上面的字，不是解析什么文档",
        "识别 {img} 图面文字，我没有要传 PDF",
        "{img} 上的注记认出来就行，别走文档总结",
        "这景 {img} 的地图标注文字提取下，不是文档解析",
    ),
}

# 方向 → (正确 capability, 额外参数)。
BOUNDARY_DIRECTIONS: dict[str, tuple[str, dict[str, object]]] = {
    "ocr_not_detect": ("ocr_recognize", {}),
    "detect_not_ocr": ("detect_objects", {}),
    "water_not_index": ("extract_water_mask", {}),
    "index_not_water": ("calculate_spectral_index", {"index_type": "ndwi"}),
    "segment_not_detect": ("segment_landcover", {}),
    "detect_not_segment": ("detect_objects", {}),
    "parse_not_ocr": ("parse_document", {}),
    "ocr_not_parse": ("ocr_recognize", {}),
}


def realize_boundary(direction: str, *, img: str | None, doc: str | None, rng: Random) -> str:
    text = rng.choice(BOUNDARY_BANKS[direction]).format(img=img or "", doc=doc or "")
    text = _maybe_typo(text, rng, 0.15)
    return _wrap(text, rng)


# ---------------------------------------------------------------------------
# 复合层。
COMPOUND_WEB_BANK = (
    "下周末杭州天气怎么样，再帮我查下当地民宿价格行情",
    "查一下最新的耕地保护政策，另外找几个高分辨率农业遥感公开数据集",
    "明天去南京出差，天气怎样？再查下高铁晚点情况",
    "搜下今年遥感大会的举办时间，顺便查下举办地的酒店价格",
    "帮我查现在卫星影像云服务的市场价，再找官方的产品文档链接",
    "看下这周末上海限行规定，以及天气适不适合外拍",
)
UNSUPPORTED_MULTI_BANK = (
    "{img} 帮我同时算 NDVI 又提水体",
    "先给 {img} 去云再马上做地物分割",
    "{img} 重投影完顺手把船和飞机都检测了",
    "一口气把 {img} 的文字读出来再算个 NBR",
    "{img} 既要真彩色预览也要目标检测，一起出",
    "把 {img} 的云掩膜和水体掩膜一次性都做了",
    "{img} 先查元数据，接着直接分割，一条龙",
)


def realize_compound_web(rng: Random) -> str:
    return _wrap(rng.choice(COMPOUND_WEB_BANK), rng)


def realize_unsupported_multi(rng: Random, *, img: str) -> str:
    return _wrap(rng.choice(UNSUPPORTED_MULTI_BANK).format(img=img), rng)


# ---------------------------------------------------------------------------
# 噪声层。
def realize_noise(base: str, rng: Random) -> str:
    """脏文本扰动：强制错别字 + 可选啰嗦填充/去标点。不碰 ID（错别字表只含中文词）。"""

    text = _maybe_typo(base, rng, 1.0)
    if rng.random() < 0.5:
        text = text + " " + "嗯" * rng.randint(3, 8)
    if rng.random() < 0.5:
        text = text.replace("，", " ").replace("。", " ")
    return text


CORRUPTED_ID_BANK = (
    "影像 {bad} 的{task}跑一下",
    "对 {bad} 做{task}，应该是这个 ID 吧",
    "{bad} 这景帮我做{task}，ID 我记不全了",
    "好像是 {bad}？给它做{task}",
    "{bad} 做个{task}，记错了的话你帮我看下清单",
)


def corrupt_id(full_id: str, rng: Random) -> str:
    """确定性损坏 12-hex ID：截断或注入非 hex 字符。结果必然 ≠ 原 ID。"""

    mode = rng.choice(("trunc6", "trunc8", "badchar"))
    if mode == "trunc6":
        return full_id[:6]
    if mode == "trunc8":
        return full_id[:8]
    return full_id[:4] + "g" + full_id[5:]


def match_corrupted_id(bad_id: str, candidates: tuple[str, ...]) -> str | None:
    """把损坏 ID 匹配回候选完整 ID。与 corrupt_id 三种损坏方式严格对齐：

    - 截断型(trunc6/trunc8)：bad_id 是真 ID 的前缀 → full.startswith(bad_id)
    - 坏字符型(badchar)：等长，仅含非 hex 字符的位当通配，其余位逐字符相等

    返回唯一匹配的完整 ID；0 个或多个匹配 → None（歧义，调用方应判 none）。
    """

    hexset = set("0123456789abcdef")
    matches: list[str] = []
    for full in candidates:
        if len(bad_id) < len(full) and full.startswith(bad_id):
            matches.append(full)  # 截断前缀匹配
        elif len(bad_id) == len(full) and all(
            (b == f) or (b not in hexset) for b, f in zip(bad_id, full)
        ):
            matches.append(full)  # 等长、非hex位当通配
    return matches[0] if len(matches) == 1 else None



def realize_corrupted_id(rng: Random, *, bad_id: str) -> tuple[str, str]:
    """返回 (query, task)。task 供调用方推导 capability，避免写死与 query 脱钩。"""
    task = rng.choice(_CALL_COMPLETION_TASKS)
    return _wrap(rng.choice(CORRUPTED_ID_BANK).format(bad=bad_id, task=task), rng), task

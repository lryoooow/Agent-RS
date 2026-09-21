"""Generate editable platform diagrams using only the Python standard library.

Run from any directory: python scripts/generate_platform_diagrams.py
PNG export: see docs/diagrams/README.md.
"""

from __future__ import annotations

from html import escape
from pathlib import Path
import unicodedata
import xml.etree.ElementTree as ET


OUT = Path(__file__).resolve().parents[1] / "docs" / "diagrams"
C = {
    "ink": "#111827", "muted": "#64748b", "line": "#d1d5db",
    "blue": "#2563eb", "green": "#059669", "purple": "#7c3aed",
    "orange": "#ea580c", "blue_bg": "#eff6ff", "green_bg": "#ecfdf5",
    "purple_bg": "#faf5ff", "orange_bg": "#fff7ed",
}


def text_width(value: str, size: float) -> float:
    return sum(1 if unicodedata.east_asian_width(c) in "WF" else .57 for c in value) * size


class Diagram:
    def __init__(self, title: str, subtitle: str, height: int):
        self.height = height
        self.lines: list[str] = []
        self.add(f'<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="{height}" viewBox="0 0 1400 {height}" role="img" aria-labelledby="title desc">')
        self.add(f'<title id="title">{escape(title)}</title>')
        self.add(f'<desc id="desc">{escape(subtitle)}</desc>')
        self.add('<style>text {font-family:"Microsoft YaHei","PingFang SC","Noto Sans CJK SC",Arial,sans-serif;} path,line,rect,polygon,ellipse {stroke-linejoin:round;stroke-linecap:round;}</style>')
        self.add('<defs>')
        for name in ("blue", "green", "purple", "orange"):
            self.add(f'<marker id="arrow-{name}" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto" markerUnits="userSpaceOnUse"><polygon points="0 0,10 3.5,0 7" fill="{C[name]}"/></marker>')
        self.add('</defs>')
        self.rect(0, 0, 1400, height, fill="#ffffff", stroke="none", radius=0)
        self.text(56, 53, "AGENT-RS  /  REMOTE SENSING", 14, "blue", weight=700)
        self.text(56, 100, title, 32, weight=700)
        self.text(56, 130, subtitle, 16, "muted")

    def add(self, line: str):
        self.lines.append(line)

    def rect(self, x, y, w, h, *, fill="#ffffff", stroke=None, radius=10, dash=False):
        extra = ' stroke-dasharray="6 5"' if dash else ''
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke or C["line"]}" stroke-width="1.5"{extra}/>')

    def text(self, x, y, value, size=18, color="ink", *, anchor="start", weight=400):
        assert 0 <= x <= 1400 and 0 <= y <= self.height, (value, x, y)
        self.add(f'<text x="{x}" y="{y}" text-anchor="{anchor}" fill="{C.get(color, color)}" font-size="{size}" font-weight="{weight}">{escape(value)}</text>')

    def box(self, x, y, w, h, title, details=(), *, tint=None, double=False, io=False):
        fill = C[f"{tint}_bg"] if tint else "#ffffff"
        if io:
            self.add(f'<polygon points="{x+16},{y} {x+w},{y} {x+w-16},{y+h} {x},{y+h}" fill="{fill}" stroke="{C["line"]}" stroke-width="1.5"/>')
        else:
            self.rect(x, y, w, h, fill=fill)
        if double:
            self.rect(x+4, y+4, w-8, h-8, fill="none", stroke="#bfdbfe", radius=7)
        assert text_width(title, 20) <= w-40, title
        self.text(x+w/2, y+30, title, 20, anchor="middle", weight=700)
        for i, detail in enumerate(details):
            assert text_width(detail, 15) <= w-32, detail
            self.text(x+w/2, y+56+i*23, detail, 15, "muted", anchor="middle")

    def group(self, x, y, w, h, label):
        self.rect(x, y, w, h, fill="#f8fafc", dash=True, radius=14)
        self.text(x+22, y+31, label, 17, "muted", weight=700)

    def arrow(self, points, *, kind="blue", label=None, at=None, dash=False, end=True):
        data = "M " + " L ".join(f"{x},{y}" for x, y in points)
        dashed = ' stroke-dasharray="6 5"' if dash else ''
        marker = f' marker-end="url(#arrow-{kind})"' if end else ''
        self.add(f'<path d="{data}" fill="none" stroke="{C[kind]}" stroke-width="2"{dashed}{marker}/>')
        if label:
            assert at is not None
            self.label(*at, label, color=kind)

    def label(self, x, y, value, *, color="muted"):
        w = text_width(value, 14)+16
        self.rect(x-w/2, y-15, w, 23, fill="#ffffff", stroke="none", radius=4)
        self.text(x, y+2, value, 14, color, anchor="middle")

    def diamond(self, cx, cy, hw, hh, title, detail=None):
        self.add(f'<polygon points="{cx},{cy-hh} {cx+hw},{cy} {cx},{cy+hh} {cx-hw},{cy}" fill="{C["blue_bg"]}" stroke="#93c5fd" stroke-width="1.5"/>')
        self.text(cx, cy+(0 if detail else 7), title, 19, anchor="middle", weight=700)
        if detail:
            self.text(cx, cy+25, detail, 14, "muted", anchor="middle")

    def cylinder(self, x, y, w, h, title, detail):
        self.add(f'<path d="M {x},{y+14} A {w/2},14 0 0 1 {x+w},{y+14} L {x+w},{y+h-14} A {w/2},14 0 0 1 {x},{y+h-14} Z" fill="{C["green_bg"]}" stroke="#a7d8c9" stroke-width="1.5"/>')
        self.add(f'<ellipse cx="{x+w/2}" cy="{y+14}" rx="{w/2}" ry="14" fill="none" stroke="#a7d8c9" stroke-width="1.5"/>')
        self.text(x+w/2, y+49, title, 18, anchor="middle", weight=700)
        self.text(x+w/2, y+75, detail, 14, "muted", anchor="middle")

    def footer(self, y, note):
        self.arrow([(56, y), (94, y)])
        self.text(105, y+5, "请求 / 数据", 14, "muted")
        self.arrow([(265, y), (303, y)], kind="green")
        self.text(314, y+5, "上下文 / 存储", 14, "muted")
        self.arrow([(494, y), (532, y)], kind="purple")
        self.text(543, y+5, "结果反馈", 14, "muted")
        self.arrow([(695, y), (733, y)], kind="orange", dash=True)
        self.text(744, y+5, "异常 / 拒绝", 14, "muted")
        self.text(56, y+38, note, 13, "muted")

    def save(self, name):
        self.add('</svg>')
        data = "\n".join(self.lines)+"\n"
        ET.fromstring(data)
        OUT.mkdir(parents=True, exist_ok=True)
        target = OUT / f"{name}.svg"
        target.write_text(data, encoding="utf-8")
        print(target)


def architecture():
    d = Diagram("平台架构图", "自然语言编排 · 遥感专业计算 · 空间成果回流", 1530)
    d.group(40, 164, 1320, 156, "01  交互层")
    d.box(64, 214, 420, 82, "智能工作台", ["React + MapLibre · 对话 / ROI / 图层"], tint="blue")
    d.box(524, 214, 426, 82, "卫星影像与知识中心", ["检索 / 导入 / 档案 / 文档与图谱"], tint="blue")
    d.box(1000, 214, 336, 82, "卫星轨道态势", ["Satvis 内嵌工作区 · 独立入口"])
    d.arrow([(274, 296), (274, 348), (380, 348), (380, 386)])
    d.arrow([(737, 296), (737, 348), (650, 348), (650, 386)], label="HTTP / SSE", at=(516, 347), end=True)
    d.box(64, 386, 886, 90, "02  FastAPI 业务入口", ["登录与用户归属 · 对话 / 影像 / 场景 / 知识 / 报告 API"], tint="blue")
    d.box(1000, 370, 336, 106, "平台约束", ["请求 ID / 统一错误 / 用户隔离", "工具配额 / 并发控制 / 超时"])
    d.group(40, 536, 920, 314, "03  AutoGen 编排层  ·  engine 统一适配")
    d.arrow([(500, 476), (500, 580)], label="可信请求", at=(500, 506))
    d.box(320, 580, 360, 70, "结构化路由", ["完整命中标准作业才进入 GraphFlow"], tint="blue")
    d.arrow([(430, 650), (430, 680), (263, 680), (263, 724)], label="自由 / 不确定请求", at=(263, 691))
    d.arrow([(570, 650), (570, 680), (737, 680), (737, 724)], label="完整标准作业", at=(737, 691))
    d.box(88, 724, 350, 94, "主 Agent", ["全部已启用工具 · 自主工具循环", "main_agent"], tint="blue", double=True)
    d.box(562, 724, 350, 94, "GraphFlow", ["固定领域节点顺序 · 报告收尾", "节点内由 Agent 选择工具"], tint="blue", double=True)

    d.group(1000, 536, 336, 314, "上下文与知识")
    d.box(1020, 582, 296, 72, "可信上下文", ["当前影像 / 波段角色 / ROI"])
    d.box(1020, 676, 296, 72, "RAG 与长期记忆", ["相关片段检索 · 回合内缓存"])
    d.text(1168, 782, "历史与已有成果 · Token 预算", 15, "muted", anchor="middle")
    d.text(1168, 810, "分别注入主 Agent / 流内节点", 15, "muted", anchor="middle")
    d.arrow([(1020, 618), (960, 618)], kind="green")

    d.arrow([(263, 818), (263, 882), (500, 882)], end=False)
    d.arrow([(737, 818), (737, 882), (500, 882)], end=False)
    d.arrow([(500, 882), (500, 922)], label="工具调用", at=(500, 901))
    d.box(88, 922, 824, 112, "04  单一工具注册表 + 统一执行管线", ["Pydantic 契约 → 配额 / 参数 / 资源归属 / 分析前置校验", "任务登记与心跳 → 影像 staging → runner → 终态记录"], tint="purple")
    d.group(40, 1106, 920, 158, "05  能力执行层")
    d.arrow([(500, 1034), (500, 1074)], end=False)
    d.arrow([(500, 1074), (203, 1074), (203, 1152)])
    d.arrow([(500, 1074), (510, 1074), (510, 1152)])
    d.arrow([(500, 1074), (817, 1074), (817, 1152)])
    d.box(66, 1152, 274, 92, "MCP / Docker", ["栅格质检 / 指数 / 预处理", "YOLO11s-OBB 目标检测"])
    d.box(373, 1152, 274, 92, "SAM3 本地服务", ["HTTP /infer · GPU 推理", "开放词汇实例分割"])
    d.box(680, 1152, 274, 92, "共享业务工具", ["STAC 检索 / 导入 / 地图", "联网搜索 / 文档 / 报告"])

    d.group(1000, 906, 336, 358, "数据与成果存储")
    d.cylinder(1020, 952, 296, 102, "PostgreSQL + pgvector", "会话 / 元数据 / 向量 / 任务")
    d.cylinder(1020, 1082, 296, 102, "本地文件 / MinIO", "影像文件 / 分析产物 / 报告")
    d.text(1168, 1220, "知识图谱按用户存储于 PostgreSQL", 14, "muted", anchor="middle")
    d.arrow([(912, 978), (1020, 978)], kind="green", dash=True, label="状态", at=(967, 978))

    for x in (203, 510, 817):
        d.arrow([(x, 1244), (x, 1292), (500, 1292)], kind="purple", end=False)
    d.arrow([(500, 1292), (500, 1338)], kind="purple", label="结构化结果", at=(500, 1315))
    d.box(64, 1338, 886, 92, "06  结果回流与交付", ["工具摘要回到 Agent · SSE 更新地图与对话 · 会话成果保存", "按需基于真实结果生成 Word 报告 · 下载 GeoTIFF / GeoJSON / PNG"], tint="green")
    d.box(1000, 1338, 336, 92, "外部依赖", ["兼容模型端点 / Embedding", "STAC 数据源 / 搜索 / 地图"])
    d.footer(1470, "图为职责与主调用路径；共享存储和外部依赖按需访问，省略重复连线。SAM3 与 MCP 的运行边界分别标注。")
    d.save("agent-rs-platform-architecture")


def workflow():
    d = Diagram("遥感分析流程图", "从数据与任务出发，经受控计算，回到地图成果与可核查报告", 1930)
    d.box(80, 172, 360, 96, "本地影像", ["上传 GeoTIFF", "保留坐标与波段语义"], io=True, tint="green")
    d.box(520, 172, 360, 96, "公开影像", ["STAC 搜索 → 预览 / 导入", "区域 / 时间 / 云量"], io=True, tint="green")
    d.box(960, 172, 360, 96, "地图选区", ["prepare_map_roi 按需取图", "底图仅 RGB，无 NIR / SWIR"], io=True, tint="green")
    for x in (260, 700, 1140):
        d.arrow([(x, 268), (x, 308), (700, 308)], end=False)
    d.arrow([(700, 308), (700, 352)])
    d.box(460, 352, 480, 90, "确认分析对象", ["当前影像 ID · 空间范围 · 波段角色", "可在对话工具循环中继续取图 / 导入"])
    d.arrow([(700, 442), (700, 492)])
    d.box(460, 492, 480, 90, "提交自然语言任务", ["选中影像 + 可选 ROI + 用户要求", "装配历史、已有成果与相关知识"], tint="blue")
    d.box(1010, 492, 310, 90, "检索与上下文", ["RAG / 长期记忆按需注入", "每次模型调用受预算约束"])
    d.arrow([(1010, 537), (940, 537)], kind="green")
    d.arrow([(700, 582), (700, 648)])
    d.diamond(700, 712, 188, 64, "完整标准作业？", "结构化路由")
    d.arrow([(512, 712), (320, 712), (320, 822)], label="否 / 不确定 / 路由失败", at=(320, 764))
    d.arrow([(888, 712), (1080, 712), (1080, 822)], label="是", at=(1080, 764))
    d.box(110, 822, 420, 96, "主 Agent", ["自由任务自主选择工具", "无影像时可走快车道"], tint="blue", double=True)
    d.box(870, 822, 420, 96, "GraphFlow", ["按固定顺序执行领域节点", "标准作业由报告节点收尾"], tint="blue", double=True)
    d.arrow([(320, 918), (320, 956), (700, 956)], end=False)
    d.arrow([(1080, 918), (1080, 956), (700, 956)], end=False)
    d.arrow([(700, 956), (700, 1004)])
    d.box(490, 1004, 420, 88, "当前 Agent / 流节点", ["选择本步工具与参数"], tint="blue")
    d.arrow([(700, 1092), (700, 1166)], label="需要工具", at=(700, 1129))
    d.box(490, 1166, 420, 96, "校验与登记", ["配额 / 参数 / 资源归属 / 分析前置条件", "登记任务 · 准备影像 · 执行期心跳"], tint="purple")
    d.arrow([(700, 1262), (700, 1340)], label="校验通过", at=(700, 1302))
    d.box(490, 1340, 420, 94, "调用能力", ["MCP 栅格 / YOLO · HTTP SAM3", "或影像检索、导入、报告等共享工具"])
    d.arrow([(700, 1434), (700, 1508)], kind="purple")
    d.box(490, 1508, 420, 100, "收集执行结果", ["摘要回到模型 · 产物进入回合状态", "终态记录 / SSE 阶段与地图更新"], tint="green")
    # Separate channels preserve the visible distinction between data and control.
    d.diamond(1110, 1558, 140, 64, "还需下一步？")
    d.arrow([(910, 1558), (970, 1558)], kind="purple")
    d.arrow([(1110, 1494), (1338, 1494), (1338, 1048), (910, 1048)], kind="purple", label="是：工具循环 / 下一节点", at=(1120, 1048))
    d.arrow([(1110, 1622), (1110, 1690), (700, 1690), (700, 1740)], label="否：汇总", at=(1000, 1690))

    d.box(100, 1166, 300, 118, "拒绝或执行失败", ["给出真实原因与已完成部分", "修改前提后才重新执行", "未执行内容不生成分析结论"], tint="orange")
    d.arrow([(490, 1214), (400, 1214)], kind="orange", dash=True, label="拒绝", at=(445, 1214))
    d.arrow([(490, 1387), (250, 1387), (250, 1284)], kind="orange", dash=True, label="失败", at=(359, 1387))
    d.arrow([(100, 1225), (60, 1225), (60, 1787), (438.3, 1787)], kind="orange", dash=True, label="反馈原因", at=(250, 1787))
    d.box(430, 1740, 540, 98, "交付成果", ["地图图层 + 分析说明 + 可下载文件", "按需生成报告：本轮成功结果 + 会话已存成果"], tint="green", io=True)
    d.footer(1870, "图聚焦需要工具的分析任务，纯问答可直接返回；底图可在工具循环中获取，报告按需生成。循环也表示 GraphFlow 节点推进。")
    d.save("agent-rs-analysis-workflow")


if __name__ == "__main__":
    architecture()
    workflow()

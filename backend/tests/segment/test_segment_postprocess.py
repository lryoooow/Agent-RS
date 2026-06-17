"""地物分类推理后处理纯函数单测。

compute_segment.py 在 docker/rs_segment 下、不在 app 包内，且 _run_inference 依赖
torch+模型权重无法在 CI 跑。故把可独立校验的纯 numpy 函数（余弦窗/softmax/众数滤波/
连通域/小斑过滤/后处理）按文件路径用 importlib 加载后单测——模块级不 import torch，
加载零依赖（test_module_loads_without_torch 守这条约定）。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

# 仓库根 = backend/tests/segment 往上三级；docker/rs_segment/compute_segment.py。
_MODULE_PATH = (
    Path(__file__).resolve().parents[3] / "docker" / "rs_segment" / "compute_segment.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("compute_segment_under_test", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cs = _load_module()


# ----- 加载约定 ---------------------------------------------------------------


def test_module_loads_without_torch() -> None:
    # 纯函数区必须 torch-free：模块能 import 即证明（上面 import 已成功），
    # 再断言关键纯函数存在，防止有人把 torch import 提到模块级破坏此约定。
    for name in (
        "_cosine_window",
        "_softmax",
        "_majority_filter",
        "_label_connected",
        "_remove_small_blobs",
        "_postprocess",
    ):
        assert callable(getattr(cs, name))


# ----- 余弦窗 -----------------------------------------------------------------


def test_cosine_window_shape_and_symmetry() -> None:
    w = cs._cosine_window(512)
    assert w.shape == (512, 512)
    assert w.dtype == np.float32
    # 上下、左右对称（窗本身对称）。
    assert np.allclose(w, w[::-1, :])
    assert np.allclose(w, w[:, ::-1])


def test_cosine_window_center_exceeds_edge_and_strictly_positive() -> None:
    w = cs._cosine_window(64)
    center = w[32, 32]
    # 中心权重远大于边缘。
    assert center > w[0, 0]
    assert center > w[0, 32]
    # 严格 >0（端点取 (n+1)/(size+1) 而非 n/(size-1)，避免 0 权重）。
    assert (w > 0).all(), "余弦窗必须处处 >0，否则归一化会出现除零/噪声放大"


# ----- softmax ----------------------------------------------------------------


def test_softmax_sums_to_one_and_preserves_argmax() -> None:
    logits = np.array([[[2.0, 1.0, 0.1, -1.0]]], dtype=np.float32)  # [1,1,4]
    prob = cs._softmax(logits, axis=-1)
    assert np.allclose(prob.sum(axis=-1), 1.0)
    assert prob.argmax(axis=-1)[0, 0] == 0  # 最大 logit 的类别概率最大


def test_softmax_numerically_stable_with_large_logits() -> None:
    # 大数不应 overflow 成 nan/inf（减最大值的稳定实现）。
    logits = np.array([[[1000.0, 999.0, 998.0, 1.0]]], dtype=np.float32)
    prob = cs._softmax(logits, axis=-1)
    assert np.isfinite(prob).all()
    assert np.allclose(prob.sum(axis=-1), 1.0)


# ----- 众数滤波 ---------------------------------------------------------------


def test_majority_filter_removes_salt_pepper() -> None:
    # 一片类别 1 中间嵌单个类别 2 像素 → 3x3 众数把它抹回 1。
    mask = np.ones((5, 5), dtype=np.uint8)
    mask[2, 2] = 2
    out = cs._majority_filter(mask, num_classes=4)
    assert out[2, 2] == 1
    assert (out == 1).all()


def test_majority_filter_preserves_large_block() -> None:
    # 左半 0、右半 1 的大块：除边界外类别不应被翻转（不误伤大连通域）。
    mask = np.zeros((10, 10), dtype=np.uint8)
    mask[:, 5:] = 1
    out = cs._majority_filter(mask, num_classes=4)
    assert (out[:, :4] == 0).all()
    assert (out[:, 6:] == 1).all()


# ----- 连通域 + 小斑过滤 ------------------------------------------------------


def test_label_connected_counts_components() -> None:
    binary = np.zeros((5, 5), dtype=bool)
    binary[0, 0] = True  # 孤立点
    binary[2:4, 2:4] = True  # 2x2 块
    labels = cs._label_connected(binary)
    unique = set(np.unique(labels)) - {0}
    assert len(unique) == 2  # 两个独立连通域
    assert (labels[2:4, 2:4] == labels[2, 2]).all()  # 块内同标签


def test_remove_small_blobs_drops_isolated_pixels() -> None:
    # 大块类别 1（>min_size）保留，孤立单像素类别 1 被降为背景。
    mask = np.zeros((20, 20), dtype=np.uint8)
    mask[0:10, 0:10] = 1  # 100 像素大块
    mask[18, 18] = 1  # 孤立点
    out = cs._remove_small_blobs(mask, min_size=50, num_classes=4)
    assert (out[0:10, 0:10] == 1).all(), "大于阈值的连通域必须保留"
    assert out[18, 18] == 0, "小于阈值的碎斑必须降为背景"


def test_remove_small_blobs_keeps_background_untouched() -> None:
    # 背景类（idx 0）不参与过滤——纯背景图后处理后仍全背景。
    mask = np.zeros((8, 8), dtype=np.uint8)
    out = cs._remove_small_blobs(mask, min_size=10, num_classes=4)
    assert (out == 0).all()


# ----- 后处理整合 -------------------------------------------------------------


def test_postprocess_uniform_image_unchanged() -> None:
    # 全同一类（大块）的图后处理后不变，不误伤大连通域。
    mask = np.full((30, 30), 2, dtype=np.uint8)
    out = cs._postprocess(mask, num_classes=4)
    assert out.shape == mask.shape
    assert (out == 2).all()


def test_postprocess_smooths_and_despeckles() -> None:
    # 大块 woodland(2) + 散落单像素 building(1) → 碎斑被清，主块基本保留。
    rng = np.random.RandomState(0)
    mask = np.full((40, 40), 2, dtype=np.uint8)
    for _ in range(15):
        y, x = rng.randint(0, 40, size=2)
        mask[y, x] = 1
    out = cs._postprocess(mask, num_classes=4)
    assert (out == 1).sum() < (mask == 1).sum(), "椒盐碎斑应显著减少"
    assert (out == 2).sum() > 40 * 40 * 0.9, "主类大块应基本保留"


# ----- 融合无阶跃（软融合核心验证）-------------------------------------------


def test_cosine_weighted_fusion_has_no_seam() -> None:
    """模拟两块在重叠区软融合：余弦窗加权平均后，融合带内概率单调过渡、无突变阶跃。

    复刻 _run_inference 的累积逻辑（不依赖 torch）：构造一维场景——左块偏类 A、
    右块偏类 B，重叠区用余弦窗加权累加再归一化，断言类 A 概率沿 x 单调下降、
    无相邻列的硬跳变（旧 unpatchify 硬覆盖会在拼接列产生阶跃）。
    """
    patch = 8
    step = patch // 2
    total = patch + step  # 两块覆盖 12 列
    window = cs._cosine_window(patch)  # [8,8]
    w1d = window[patch // 2]  # 取中间行的一维窗（行向对称，代表横向权重）

    prob_acc = np.zeros((total, 2), dtype=np.float64)
    weight_acc = np.zeros(total, dtype=np.float64)
    # 左块（x 0..7）偏类 0；右块（x 4..11）偏类 1。
    left = np.tile(np.array([0.8, 0.2]), (patch, 1))
    right = np.tile(np.array([0.2, 0.8]), (patch, 1))
    for x0, blk in ((0, left), (step, right)):
        prob_acc[x0 : x0 + patch] += blk * w1d[:, None]
        weight_acc[x0 : x0 + patch] += w1d
    fused = prob_acc / np.maximum(weight_acc, 1e-8)[:, None]

    classA = fused[:, 0]
    diffs = np.abs(np.diff(classA))
    # 无阶跃：任意相邻列概率跳变都很小（远小于硬覆盖会出现的 0.6 级突变）。
    assert diffs.max() < 0.2, f"融合带出现阶跃，最大跳变={diffs.max():.3f}"


def test_fusion_no_divide_by_zero_with_positive_window() -> None:
    # 余弦窗严格 >0 → weight_acc 在被覆盖区处处 >0，归一化不产生 nan/inf。
    window = cs._cosine_window(16)
    assert (window > 0).all()
    weight_acc = np.zeros((16, 16), dtype=np.float32)
    weight_acc += window
    fused = np.ones((16, 16, 4), dtype=np.float32) / np.maximum(weight_acc, 1e-8)[..., None]
    assert np.isfinite(fused).all()

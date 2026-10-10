"""A5：EVI/SAVI/MSAVI 必须在反射率域计算；去 clip；比值类指数不定标标注。

历史 bug：compute_spectral_index 直接用原始 DN 计算带常数公式，再用
np.clip(±1) 掩盖错误（nir=3000/red=1000/blue=800 的 S2 DN 算出 EVI=1.666
被截成 1.0；真值 0.3846）。修复（工作单 A5）：
1. 统一定标：由文件明确的逐波段 scale/offset/反射率单位计算；
   传感器名、成像日期和 float 数值范围均不能替代定标证据。
2. 未知产品的原始比值只能标 calibrated: false，不能当定量反射率指数；
   已知 S2/Landsat 产品缺失定标证据时必须拒绝。
3. 去掉 clip，越界值如实保留并在 stats 计数 out_of_range_pct。

所有期望值独立手算（见各用例注释），不来自实现。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

RS_TOOLS_DIR = Path(__file__).resolve().parents[3] / "docker" / "rs_tools"
sys.path.insert(0, str(RS_TOOLS_DIR))

from compute_spectral_index import compute  # noqa: E402
from raster_utils import StaleS2CompositeError, UncalibratedInputError  # noqa: E402

# 反射率像元（工作单 A5 指定）：nir=0.30, red=0.10, blue=0.08
NIR_R, RED_R, BLUE_R = 0.30, 0.10, 0.08
# 对应 S2 L2A DN（/10000 定标后回到同一组反射率）
NIR_DN, RED_DN, BLUE_DN = 3000, 1000, 800


def _write_tif(path: Path, bands: list[float], dtype: str, *, tags=None) -> None:
    data = np.stack([np.full((1, 1), v, dtype=dtype) for v in bands])
    with rasterio.open(
        path, "w", driver="GTiff", height=1, width=1, count=len(bands),
        dtype=dtype, transform=from_origin(0, 1, 1, 1),
    ) as dst:
        dst.write(data)
        if dtype == "float32" and not tags:
            dst.units = ("reflectance",) * len(data)
        if tags:
            dst.update_tags(**tags)


def test_evi_reflectance_matches_hand_computation(tmp_path: Path) -> None:
    """手算：EVI = 2.5*(0.30-0.10)/(0.30+6*0.10-7.5*0.08+1)
    = 2.5*0.20/(0.30+0.60-0.60+1) = 0.5/1.3 = 0.384615…（工作单 A5 给定 0.3846）"""
    inp = tmp_path / "refl.tif"
    _write_tif(inp, [BLUE_R, 0.09, RED_R, NIR_R, 0.15], "float32")

    stats = compute(input_path=str(inp), output_dir=str(tmp_path / "out"), index_type="evi")

    assert stats["mean"] == pytest.approx(0.384615, abs=1e-4)
    assert stats["calibrated"] is True
    assert stats["out_of_range_pct"] == 0.0


def test_savi_reflectance_matches_hand_computation(tmp_path: Path) -> None:
    """手算：SAVI(L=0.5) = 1.5*(0.30-0.10)/(0.30+0.10+0.5) = 0.3/0.9 = 0.333333…
    （工作单 A5 给定 0.3333）"""
    inp = tmp_path / "refl.tif"
    _write_tif(inp, [BLUE_R, 0.09, RED_R, NIR_R, 0.15], "float32")

    stats = compute(input_path=str(inp), output_dir=str(tmp_path / "out"), index_type="savi")

    assert stats["mean"] == pytest.approx(0.333333, abs=1e-4)
    assert stats["calibrated"] is True


def test_evi_savi_s2_dn_calibration_matches_reflectance(tmp_path: Path) -> None:
    """S2 L2A DN（3000/1000/800）经 DN/10000 定标后与反射率输入结果一致。

    该合成测试明确声明 scale=.0001、offset=0；零偏置来自文件参数，
    不是由传感器名或成像日期推断。
    """
    inp = tmp_path / "s2.tif"
    _write_tif(inp, [BLUE_DN, 900, RED_DN, NIR_DN, 1500], "uint16",
               tags={"SENSOR": "Sentinel-2B", "REFL_SCALE": ".0001", "REFL_OFFSET": "0"})

    evi = compute(input_path=str(inp), output_dir=str(tmp_path / "o_evi"), index_type="evi")
    savi = compute(input_path=str(inp), output_dir=str(tmp_path / "o_savi"), index_type="savi")

    assert evi["mean"] == pytest.approx(0.384615, abs=1e-4)
    assert savi["mean"] == pytest.approx(0.333333, abs=1e-4)
    assert evi["calibrated"] is True and savi["calibrated"] is True


def test_landsat_c2_l2_calibration(tmp_path: Path) -> None:
    """Landsat C2 L2：反射率 = DN*0.0000275-0.2（USGS 产品指南）。

    手算：取 nir DN = (0.30+0.2)/0.0000275 = 18181.8…，red DN = (0.10+0.2)/0.0000275
    = 10909.1…，blue DN = (0.08+0.2)/0.0000275 = 10181.8…。定标后回到
    0.30/0.10/0.08，SAVI = 0.3333。
    """
    scale, offset = 0.0000275, -0.2
    nir_dn, red_dn, blue_dn = ((0.30 - offset) / scale, (0.10 - offset) / scale, (0.08 - offset) / scale)
    inp = tmp_path / "lc.tif"
    _write_tif(inp, [blue_dn, 11000, red_dn, nir_dn, 12000], "int32",
               tags={"SENSOR": "Landsat 9", "REFL_SCALE": ".0000275", "REFL_OFFSET": "-.2"})

    savi = compute(input_path=str(inp), output_dir=str(tmp_path / "out"), index_type="savi")

    assert savi["mean"] == pytest.approx(0.333333, abs=1e-4)
    assert savi["calibrated"] is True


@pytest.mark.parametrize("index_type", ["evi", "savi", "msavi"])
def test_reflectance_indices_reject_uncalibrated_input(tmp_path: Path, index_type: str) -> None:
    """异常：无定标信息（GF-2 上传 DN，无传感器标签）-> uncalibrated_input，
    不允许静默按 DN 计算（工作单 A2/A5）。"""
    inp = tmp_path / "gf2.tif"
    _write_tif(inp, [BLUE_DN, 900, RED_DN, NIR_DN, 1500], "uint16")

    with pytest.raises(UncalibratedInputError, match="uncalibrated_input"):
        compute(input_path=str(inp), output_dir=str(tmp_path / "out"), index_type=index_type)


def test_ratio_index_on_uncalibrated_dn_marks_calibrated_false(tmp_path: Path) -> None:
    """正常：比值类指数对线性缩放不敏感，无定标 DN 照算但标注 calibrated: false。

    手算：NDWI = (900-3000)/(900+3000) = -2100/3900 = -7/13 = -0.538462。
    """
    inp = tmp_path / "gf2.tif"
    _write_tif(inp, [BLUE_DN, 900, RED_DN, NIR_DN, 1500], "uint16")

    stats = compute(input_path=str(inp), output_dir=str(tmp_path / "out"), index_type="ndwi")

    assert stats["calibrated"] is False
    assert stats["mean"] == pytest.approx(-7.0 / 13.0, abs=1e-4)


def test_out_of_range_values_are_counted_not_clipped(tmp_path: Path) -> None:
    """A5.3：去掉 clip——越界值如实写进数据文件，并在 stats 计数。

    手算：构造 swir=-0.5、nir=0.1（负反射率在 Landsat 偏置定标后真实存在），
    NDBI = (swir-nir)/(swir+nir) = (-0.6)/(-0.4) = 1.5 > 1（越界）。
    旧代码 clip 会把它截成 1.0 并掩盖。
    """
    inp = tmp_path / "oor.tif"
    _write_tif(inp, [0.2, 0.2, 0.2, 0.1, -0.5], "float32")

    stats = compute(input_path=str(inp), output_dir=str(tmp_path / "out"), index_type="ndbi")

    assert stats["mean"] == pytest.approx(1.5, abs=1e-4)
    assert stats["out_of_range_pct"] == 100.0
    with rasterio.open(tmp_path / "out" / stats["output_tif"]) as src:
        assert float(src.read(1)[0, 0]) == pytest.approx(1.5, abs=1e-6)


def test_evi_dn_regression_historical_clip_bug(tmp_path: Path) -> None:
    """回归锁定（历史 bug，工作单 A5）：S2 DN 3000/1000/800 直算 EVI 会得到
    2.5*2000/3001 = 1.666…，旧代码再 clip 成 1.0。修复后定标计算得 0.3846。

    此处显式声明 offset=0，检验指定参数的数学效果。"""
    inp = tmp_path / "s2.tif"
    _write_tif(inp, [BLUE_DN, 900, RED_DN, NIR_DN, 1500], "uint16",
               tags={"SENSOR": "Sentinel-2B", "REFL_SCALE": ".0001", "REFL_OFFSET": "0"})

    stats = compute(input_path=str(inp), output_dir=str(tmp_path / "out"), index_type="evi")

    assert stats["mean"] == pytest.approx(0.384615, abs=1e-4)
    assert stats["mean"] != pytest.approx(1.0, abs=1e-3)
    with rasterio.open(tmp_path / "out" / stats["output_tif"]) as src:
        assert float(src.read(1)[0, 0]) == pytest.approx(0.384615, abs=1e-4)


# ---------------- S2 L2A BOA offset（2026-10-07 D3 核实落地） ----------------
# ESA SentiWiki（https://sentiwiki.copernicus.eu/web/s2-products）：PB>=04.00
# （2022-01-25 起）L2A 反射率 = (DN + BOA_ADD_OFFSET)/10000，多数波段
# BOA_ADD_OFFSET=-1000。earth-search sentinel-2-c1-l2a 条目 raster:bands
# {scale 0.0001, offset -0.1} 与之一致。stac compose 把参数写入 REFL_* 标签。
# DN 取真实 PB05 场景量级：nir=4000/red=2000/blue=1800 → ρ=0.30/0.10/0.08。
NIR_DN_B04, RED_DN_B04, BLUE_DN_B04 = 4000, 2000, 1800
REFL_TAGS = {"SENSOR": "Sentinel-2C", "REFL_SCALE": "0.0001", "REFL_OFFSET": "-0.1"}


def test_s2_boa_offset_tags_evi_savi_hand_computed(tmp_path: Path) -> None:
    """带 REFL 标签的 S2 DN：定标 ρ=(DN-1000)/10000 后回到 0.30/0.10/0.08，
    EVI=0.384615、SAVI=0.333333（手算公式见文件头 A5 用例）。

    同 DN 若明确声明 offset=0，则得到 ρ=0.40/0.20/0.18、EVI=0.4。
    两个计算结果锁定偏置参数的作用；这不表示该参数适合真实产品。
    """
    inp = tmp_path / "s2_boa.tif"
    _write_tif(inp, [BLUE_DN_B04, 1900, RED_DN_B04, NIR_DN_B04, 2800], "uint16",
               tags=REFL_TAGS)

    evi = compute(input_path=str(inp), output_dir=str(tmp_path / "o_evi"), index_type="evi")
    savi = compute(input_path=str(inp), output_dir=str(tmp_path / "o_savi"), index_type="savi")

    assert evi["mean"] == pytest.approx(0.384615, abs=1e-4)
    assert savi["mean"] == pytest.approx(0.333333, abs=1e-4)
    assert evi["calibrated"] is True

    zero_offset = tmp_path / "s2_zero_offset.tif"
    # 显式零偏置对照；缺失参数的 S2 则由后面的用例拒绝。
    _write_tif(zero_offset, [BLUE_DN_B04, 1900, RED_DN_B04, NIR_DN_B04, 2800], "uint16",
               tags={"SENSOR": "Sentinel-2C", "REFL_SCALE": ".0001", "REFL_OFFSET": "0"})
    evi_zero_offset = compute(input_path=str(zero_offset), output_dir=str(tmp_path / "o_evi2"), index_type="evi")
    assert evi_zero_offset["mean"] == pytest.approx(0.4, abs=1e-3)  # 显式零偏置对照


def test_s2_boa_offset_malformed_tags_do_not_fall_back(tmp_path: Path) -> None:
    """Damaged metadata must not turn into an apparently valid uncalibrated result."""
    inp = tmp_path / "s2_bad_tags.tif"
    _write_tif(inp, [1800, 2500, 2000, 4000, 2800], "uint16",
               tags={"SENSOR": "Sentinel-2C", "ACQUISITIONDATE": "2021-06-01T10:00:00Z",
                     "REFL_SCALE": "oops", "REFL_OFFSET": "-0.1"})
    with pytest.raises(ValueError, match="invalid_calibration"):
        compute(input_path=str(inp), output_dir=str(tmp_path / "out"), index_type="ndwi")


# ---------------- 定标兜底：修复前合成的旧 S2 缓存（D3 收尾，2026-10-08 后） ----------------
# 旧合成文件缺少 REFL_* 参数时，成像日期不能证明是否被重新处理。
# S2 各成像日期均必须要求可验证的 scale/offset/反射率单位；不猜零偏置。
# 示例 DN：nir=4000/red=2000/blue=1800；明确 scale=.0001、offset=-.1 时
# 反射率为 .30/.10/.08。历史某景误差不推广为所有影像的固定误差。
STALE_DN_BANDS = [BLUE_DN_B04, 1900, RED_DN_B04, NIR_DN_B04, 2800]
OLD_DATE = "2021-06-01T10:00:00Z"   # 2022-01-25（PB 04.00 生效日）之前
NEW_DATE = "2024-06-01T10:30:00Z"   # 之后


def test_stale_s2_composite_new_date_raises_for_all_index_kinds(tmp_path: Path) -> None:
    """旧缓存无标签 + 新日期 → stale_s2_composite，含常数公式（EVI）与
    比值类（NDWI）都必须拒绝——比值类对偏置同样敏感，
    不得静默继续。"""
    inp = tmp_path / "stale_new.tif"
    _write_tif(inp, STALE_DN_BANDS, "uint16",
               tags={"SENSOR": "Sentinel-2C", "ACQUISITIONDATE": NEW_DATE})

    for index in ("evi", "ndwi"):
        with pytest.raises(StaleS2CompositeError, match="stale_s2_composite"):
            compute(input_path=str(inp), output_dir=str(tmp_path / "out"), index_type=index)


def test_stale_s2_composite_no_date_conservative_raise(tmp_path: Path) -> None:
    """异常：无标签 + 无 ACQUISITIONDATE → 保守视为可能受影响，同样报错
    （文件层面无证据可排除 PB>=04.00）。"""
    inp = tmp_path / "s2_nodate.tif"
    _write_tif(inp, STALE_DN_BANDS, "uint16", tags={"SENSOR": "Sentinel-2C"})

    with pytest.raises(StaleS2CompositeError, match="stale_s2_composite"):
        compute(input_path=str(inp), output_dir=str(tmp_path / "out"), index_type="evi")


@pytest.mark.parametrize("date_tag", [NEW_DATE, "2024-06-01", "not-a-date"])
def test_stale_s2_composite_bad_or_recent_date_strings_raise(tmp_path: Path, date_tag: str) -> None:
    """边界：仅日期部分（无时间）、非法日期字符串 → 分别按新日期 / 拿不到
    日期处理，均拒绝。"""
    inp = tmp_path / "s2_d.tif"
    _write_tif(inp, STALE_DN_BANDS, "uint16",
               tags={"SENSOR": "Sentinel-2C", "ACQUISITIONDATE": date_tag})

    with pytest.raises(StaleS2CompositeError, match="stale_s2_composite"):
        compute(input_path=str(inp), output_dir=str(tmp_path / "out"), index_type="evi")


@pytest.mark.parametrize("date_tag", [OLD_DATE, "2022-01-24T23:59:59Z", "2022-01-25T00:00:01Z"])
def test_no_tag_acquisition_dates_never_prove_processing_baseline(tmp_path: Path, date_tag: str) -> None:
    """Old images can be reprocessed: date alone cannot prove zero BOA offset."""
    inp = tmp_path / "s2_unproven.tif"
    _write_tif(inp, STALE_DN_BANDS, "uint16", tags={"SENSOR": "Sentinel-2C", "ACQUISITIONDATE": date_tag})
    with pytest.raises(StaleS2CompositeError, match="stale_s2_composite"):
        compute(input_path=str(inp), output_dir=str(tmp_path / "out"), index_type="evi")


def test_tagged_path_unaffected_by_date_guard(tmp_path: Path) -> None:
    """正常：带 REFL_* 标签的路径完全不受兜底影响（有标签即有定标出处，
    日期与守卫无关；无日期也可）。手算 EVI=0.384615（见 BOA 一节）。"""
    inp = tmp_path / "s2_tagged_nodate.tif"
    _write_tif(inp, STALE_DN_BANDS, "uint16",
               tags={"SENSOR": "Sentinel-2C", "REFL_SCALE": "0.0001", "REFL_OFFSET": "-0.1"})

    stats = compute(input_path=str(inp), output_dir=str(tmp_path / "out"), index_type="evi")

    assert stats["mean"] == pytest.approx(0.384615, abs=1e-4)


def test_non_s2_without_tags_keeps_original_uncalibrated_behavior(tmp_path: Path) -> None:
    """非 S2 无标签 → 原行为：含常数公式报 uncalibrated_input（而非
    stale_s2_composite），比值类照算标 calibrated: false（由既有用例
    test_reflectance_indices_reject_uncalibrated_input /
    test_ratio_index_on_uncalibrated_dn_marks_calibrated_false 锁定，
    此处再从守卫视角复核一次 EVI 分支）。"""
    inp = tmp_path / "gf2_no_sensor.tif"
    _write_tif(inp, STALE_DN_BANDS, "uint16")

    with pytest.raises(UncalibratedInputError, match="uncalibrated_input"):
        compute(input_path=str(inp), output_dir=str(tmp_path / "out"), index_type="evi")

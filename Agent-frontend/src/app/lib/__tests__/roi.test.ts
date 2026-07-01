import { describe, it, expect } from "vitest";
import {
  geoRoiFromCorners,
  pixelRoiFromCorners,
  isDegenerateRoi,
  roiContextLine,
  type GeoRoi,
  type PixelRoi,
} from "../roi";

describe("geoRoiFromCorners", () => {
  it("normalizes corners so west<east, south<north regardless of drag direction", () => {
    // 从右上拖到左下：仍要得到归一化的 [west, south, east, north]
    const roi = geoRoiFromCorners([120, 30], [110, 20]);
    expect(roi.kind).toBe("geo");
    expect(roi.bbox).toEqual([110, 20, 120, 30]);
  });

  it("handles already-ordered corners", () => {
    const roi = geoRoiFromCorners([100, 10], [105, 25]);
    expect(roi.bbox).toEqual([100, 10, 105, 25]);
  });
});

describe("pixelRoiFromCorners", () => {
  it("clamps relative coords into 0..1 and orders them", () => {
    // 越界值（负 / >1）必须钳制；任意拖拽方向归一化
    const roi = pixelRoiFromCorners([1.4, -0.2], [0.3, 0.6]);
    expect(roi.kind).toBe("pixel");
    expect(roi.rel).toEqual([0.3, 0, 1, 0.6]);
  });

  it("keeps in-range values intact", () => {
    const roi = pixelRoiFromCorners([0.2, 0.3], [0.5, 0.8]);
    expect(roi.rel).toEqual([0.2, 0.3, 0.5, 0.8]);
  });
});

describe("isDegenerateRoi", () => {
  it("flags zero-width / zero-height selections (误点)", () => {
    expect(isDegenerateRoi({ kind: "geo", bbox: [100, 20, 100, 30] })).toBe(true);
    expect(isDegenerateRoi({ kind: "pixel", rel: [0.2, 0.5, 0.7, 0.5] })).toBe(true);
  });

  it("accepts a real area", () => {
    expect(isDegenerateRoi({ kind: "geo", bbox: [100, 20, 110, 30] })).toBe(false);
    expect(isDegenerateRoi({ kind: "pixel", rel: [0.1, 0.1, 0.4, 0.6] })).toBe(false);
  });
});

describe("roiContextLine", () => {
  it("geo ROI: mentions lon/lat range and the full-image caveat", () => {
    const roi: GeoRoi = { kind: "geo", bbox: [110.5, 20.25, 120.75, 30.5] };
    const line = roiContextLine(roi);
    expect(line).toContain("经度");
    expect(line).toContain("纬度");
    expect(line).toContain("左上[110.5, 30.5]");
    expect(line).toContain("右上[120.75, 30.5]");
    expect(line).toContain("左下[110.5, 20.25]");
    expect(line).toContain("右下[120.75, 20.25]");
    // 关键：必须声明工具仍按整幅影像计算，防止模型谎称只算了选区
    expect(line).toContain("整幅影像");
  });

  it("pixel ROI: describes relative position in percent and the caveat", () => {
    const roi: PixelRoi = { kind: "pixel", rel: [0.2, 0.1, 0.6, 0.5] };
    const line = roiContextLine(roi);
    expect(line).toContain("20%");
    expect(line).toContain("60%");
    expect(line).toContain("无地理坐标");
    expect(line).toContain("整幅影像");
  });
});

import { describe, it, expect } from "vitest";
import {
  pickGraticuleStep,
  buildGraticule,
  formatGraticuleLabel,
  type LngLatBounds,
} from "../graticule";

describe("pickGraticuleStep", () => {
  it("picks a coarse step for a wide (zoomed-out) view", () => {
    const step = pickGraticuleStep({ west: -180, south: -80, east: 180, north: 80 });
    // 跨度 360 → target 60 → 取 <=60 的最大候选 30
    expect(step).toBe(30);
  });

  it("picks a fine step for a narrow (zoomed-in) view", () => {
    const step = pickGraticuleStep({ west: 116.0, south: 39.9, east: 116.6, north: 40.1 });
    // 跨度 0.6 → target 0.1 → 取 <=0.1 的最大候选 0.1
    expect(step).toBeLessThanOrEqual(0.1);
    expect(step).toBeGreaterThan(0);
  });

  it("returns a value from the candidate set (整齐间隔)", () => {
    const candidates = [30, 10, 5, 2, 1, 0.5, 0.25, 0.1, 0.05, 0.02, 0.01];
    const step = pickGraticuleStep({ west: 100, south: 20, east: 112, north: 32 });
    expect(candidates).toContain(step);
  });
});

describe("formatGraticuleLabel", () => {
  it("labels east/west and north/south with sign", () => {
    expect(formatGraticuleLabel(116, "lon")).toBe("116°E");
    expect(formatGraticuleLabel(-74, "lon")).toBe("74°W");
    expect(formatGraticuleLabel(40, "lat")).toBe("40°N");
    expect(formatGraticuleLabel(-33.5, "lat")).toBe("33.5°S");
  });
});

describe("buildGraticule", () => {
  it("produces line + label features within bounds", () => {
    const bounds: LngLatBounds = { west: 100, south: 20, east: 112, north: 32 };
    const fc = buildGraticule(bounds);
    expect(fc.type).toBe("FeatureCollection");
    const lines = fc.features.filter((f) => f.properties?.kind === "line");
    const labels = fc.features.filter((f) => f.properties?.kind === "label");
    expect(lines.length).toBeGreaterThan(0);
    // 每条线配一个标签
    expect(labels.length).toBe(lines.length);
  });

  it("clamps latitude lines to [-85, 85] (Web Mercator 极区)", () => {
    const fc = buildGraticule({ west: -10, south: -89, east: 10, north: 89 });
    const latValues = fc.features
      .filter((f) => f.geometry.type === "LineString")
      .map((f) => (f.geometry as GeoJSON.LineString).coordinates)
      // 横线（纬线）：两端 lng 不同、lat 相同
      .filter((c) => c[0][1] === c[1][1])
      .map((c) => c[0][1]);
    for (const lat of latValues) {
      expect(lat).toBeGreaterThanOrEqual(-85);
      expect(lat).toBeLessThanOrEqual(85);
    }
  });

  it("边界：a tiny view still yields at least one line, 不退化为空", () => {
    const fc = buildGraticule({ west: 116.39, south: 39.9, east: 116.41, north: 39.92 });
    const lines = fc.features.filter((f) => f.properties?.kind === "line");
    expect(lines.length).toBeGreaterThan(0);
  });

  it("边界：caps total lines under extreme zoom-out spans (不卡死)", () => {
    const fc = buildGraticule({ west: -180, south: -85, east: 180, north: 85 });
    const lines = fc.features.filter((f) => f.properties?.kind === "line");
    // MAX_LINES=200 per axis → 总线数有上限
    expect(lines.length).toBeLessThanOrEqual(400);
  });
});

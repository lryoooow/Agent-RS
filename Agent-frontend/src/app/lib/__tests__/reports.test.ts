import { describe, it, expect } from "vitest";
import { reportsFromTurns, reportsToMarkdown } from "../reports";
import type { ChatTurn, GeospatialResult, RasterInspectResult } from "../../types";

function turnWithGeo(id: string, geo: GeospatialResult): ChatTurn {
  return { id, role: "assistant", content: "", geospatialResult: geo };
}

describe("reportsFromTurns", () => {
  it("ndvi: emits min/max/mean/std stats", () => {
    const turns = [
      turnWithGeo("t1", {
        type: "ndvi",
        imagery_id: "abcdef123456",
        result_url: "/x.png",
        bounds: null,
        stats: { min: -0.1, max: 0.85, mean: 0.42, std: 0.2 },
      }),
    ];
    const r = reportsFromTurns(turns);
    expect(r).toHaveLength(1);
    expect(r[0].kind).toContain("NDVI");
    const mean = r[0].stats.find((s) => s.label === "mean");
    expect(mean?.value).toBe("0.42");
  });

  it("detection: lists count + per-class", () => {
    const turns = [
      turnWithGeo("t1", {
        type: "detection",
        imagery_id: "abcdef123456",
        result_url: "/x.png",
        bounds: null,
        detection_count: 7,
        score_threshold: 0.5,
        classes: [
          { name: "ship", label: "船舶", count: 5, color: "#fff" },
          { name: "harbor", label: "港口", count: 2, color: "#fff" },
        ],
      }),
    ];
    const r = reportsFromTurns(turns);
    expect(r[0].title).toContain("7");
    expect(r[0].stats.find((s) => s.label === "船舶")?.value).toBe("5");
  });

  it("segmentation: lists per-class percentage", () => {
    const turns = [
      turnWithGeo("t1", {
        type: "segmentation",
        imagery_id: "abcdef123456",
        result_url: "/x.png",
        bounds: null,
        total_pixels: 1000,
        classes: [{ name: "building", label: "建筑", pixel_count: 250, percentage: 25, color: "#fff" }],
      }),
    ];
    const r = reportsFromTurns(turns);
    expect(r[0].stats.find((s) => s.label === "建筑")?.value).toBe("25%");
  });

  it("raster_inspect (toolResult): size/bands/crs", () => {
    const tool: RasterInspectResult = {
      type: "raster_inspect",
      imagery_id: "abcdef123456",
      width: 2048,
      height: 1024,
      band_count: 4,
      crs: "EPSG:32650",
      bounds: null,
      dtype: "uint16",
      pixel_size: null,
      nodata: null,
      capabilities: { has_blue: true, has_green: true, has_red: true, has_nir: true, has_swir: false },
      per_band_stats: [],
    };
    const turns: ChatTurn[] = [{ id: "t1", role: "assistant", content: "", toolResult: tool }];
    const r = reportsFromTurns(turns);
    expect(r[0].kind).toBe("影像质检");
    expect(r[0].stats.find((s) => s.label === "尺寸")?.value).toBe("2048 × 1024");
    expect(r[0].stats.find((s) => s.label === "坐标系")?.value).toBe("EPSG:32650");
  });

  it("边界：preview results are not reported (非分析结果)", () => {
    const turns = [
      turnWithGeo("t1", { type: "preview", imagery_id: "abcdef123456", result_url: "/x.png", bounds: null }),
    ];
    expect(reportsFromTurns(turns)).toEqual([]);
  });

  it("边界：missing/NaN stat falls back to N/A, 不崩", () => {
    const turns = [
      turnWithGeo("t1", {
        type: "ndvi",
        imagery_id: "abcdef123456",
        result_url: "/x.png",
        bounds: null,
        stats: { min: NaN as unknown as number, max: 0.8, mean: 0.4, std: 0.2 },
      }),
    ];
    const r = reportsFromTurns(turns);
    expect(r[0].stats.find((s) => s.label === "min")?.value).toBe("N/A");
  });
});

describe("reportsToMarkdown", () => {
  it("empty → placeholder", () => {
    expect(reportsToMarkdown([])).toContain("暂无");
  });

  it("emits a markdown table with title + stats", () => {
    const md = reportsToMarkdown([
      {
        id: "t1-geo",
        turnId: "t1",
        imageryId: "abcdef123456",
        kind: "NDVI 植被指数",
        title: "NDVI 计算",
        stats: [{ label: "mean", value: "0.42" }],
        execution: { mode: "docker_mcp", fallback_used: false },
      },
    ]);
    expect(md).toContain("## NDVI 计算");
    expect(md).toContain("| mean | 0.42 |");
    expect(md).toContain("docker_mcp");
  });
});

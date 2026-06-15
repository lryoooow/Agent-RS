import { describe, expect, it } from "vitest";
import { parseGeospatialResult } from "./chat-events";

// Regression guard for a historical bug: parseGeospatialResult silently dropped
// `detection` and `segmentation` results even though the backend emits them
// (backend/app/agent/tools/{detect,segment}/runner.py) and types.ts defines them.
// Before the fix these two types returned undefined → detection/segmentation map
// layers never rendered. These cases must keep passing.

const BASE = {
  imagery_id: "abc123def456",
  result_url: "/api/imagery/abc123def456/results/x.png",
  bounds: [-121.6, 38.0, -121.5, 38.1],
};

describe("parseGeospatialResult — all 6 contract types accepted", () => {
  it("parses preview", () => {
    const r = parseGeospatialResult({ type: "preview", ...BASE });
    expect(r?.type).toBe("preview");
  });

  it("parses ndvi with stats", () => {
    const r = parseGeospatialResult({
      type: "ndvi",
      ...BASE,
      stats: { min: -0.1, max: 0.9, mean: 0.41, std: 0.2 },
    });
    expect(r?.type).toBe("ndvi");
  });

  it("parses spectral_index", () => {
    const r = parseGeospatialResult({
      type: "spectral_index",
      ...BASE,
      index_type: "NDWI",
      stats: { min: -1, max: 1, mean: 0.1, std: 0.3, nodata_pct: 2 },
    });
    expect(r?.type).toBe("spectral_index");
  });

  it("parses composite", () => {
    const r = parseGeospatialResult({
      type: "composite",
      ...BASE,
      mode: "false_color",
      bands_used: [8, 4, 3],
    });
    expect(r?.type).toBe("composite");
  });

  // ★ The regression cases — these were silently dropped before the fix.
  it("parses detection and keeps classes/count (regression)", () => {
    const r = parseGeospatialResult({
      type: "detection",
      ...BASE,
      detection_count: 38,
      score_threshold: 0.5,
      classes: [
        { name: "ship", label: "船舶", count: 21, color: "#fbbf24" },
        { name: "small-vehicle", label: "车辆", count: 11, color: "#f97316" },
      ],
    });
    expect(r?.type).toBe("detection");
    if (r?.type === "detection") {
      expect(r.detection_count).toBe(38);
      expect(r.classes).toHaveLength(2);
      expect(r.classes[0]).toMatchObject({ name: "ship", count: 21, color: "#fbbf24" });
    }
  });

  it("parses segmentation and keeps classes/percentage (regression)", () => {
    const r = parseGeospatialResult({
      type: "segmentation",
      ...BASE,
      total_pixels: 1000000,
      classes: [
        { name: "building", label: "建筑", pixel_count: 250000, percentage: 25, color: "#fb7185" },
        { name: "water", label: "水体", pixel_count: 120000, percentage: 12, color: "#38bdf8" },
      ],
    });
    expect(r?.type).toBe("segmentation");
    if (r?.type === "segmentation") {
      expect(r.total_pixels).toBe(1000000);
      expect(r.classes).toHaveLength(2);
      expect(r.classes[1]).toMatchObject({ name: "water", percentage: 12 });
    }
  });
});

describe("parseGeospatialResult — defensive boundaries (test plan item 24)", () => {
  it("returns undefined for null / non-object", () => {
    expect(parseGeospatialResult(null)).toBeUndefined();
    expect(parseGeospatialResult("nope")).toBeUndefined();
  });

  it("returns undefined for unknown type", () => {
    expect(parseGeospatialResult({ type: "heatmap", ...BASE })).toBeUndefined();
  });

  it("returns undefined when required fields missing", () => {
    expect(parseGeospatialResult({ type: "detection" })).toBeUndefined();
    expect(parseGeospatialResult({ type: "ndvi", ...BASE })).toBeUndefined(); // no stats
  });

  it("accepts null bounds (no-geo result still valid)", () => {
    const r = parseGeospatialResult({
      type: "detection",
      imagery_id: "x",
      result_url: "/y.png",
      bounds: null,
      detection_count: 0,
      classes: [],
    });
    expect(r?.type).toBe("detection");
    expect(r?.bounds).toBeNull();
  });

  it("rejects malformed bounds (length != 4)", () => {
    const r = parseGeospatialResult({
      type: "detection",
      imagery_id: "x",
      result_url: "/y.png",
      bounds: [1, 2, 3],
      detection_count: 0,
      classes: [],
    });
    expect(r).toBeUndefined();
  });

  it("tolerates detection with missing class fields (defaults applied)", () => {
    const r = parseGeospatialResult({
      type: "detection",
      ...BASE,
      classes: [{ name: "plane" }],
    });
    expect(r?.type).toBe("detection");
    if (r?.type === "detection") {
      expect(r.detection_count).toBe(0);
      expect(r.classes[0]).toMatchObject({ name: "plane", count: 0, color: "#888888" });
    }
  });
});

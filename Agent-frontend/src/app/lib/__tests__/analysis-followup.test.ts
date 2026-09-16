import { expect, it } from "vitest";
import { parseGeospatialResult, parseToolResult } from "../chat-events";

it("retains real detection model and protected download URLs in SSE/history parsing", () => {
  const result = parseGeospatialResult({ type: "detection", imagery_id: "fec6252c9325",
    bounds: [114.18, 24.85, 114.23, 24.90],
    result_url: "/api/imagery/fec6252c9325/results/detection.png", detection_count: 4,
    model_name: "YOLO11s-OBB", bands_used: [1, 2, 3], device: "K100_AI",
    vector_url: "/api/imagery/fec6252c9325/results/detection.geojson",
    detections_url: "/api/imagery/fec6252c9325/results/detection.json", classes: [] });
  expect(result?.type).toBe("detection");
  if (result?.type !== "detection") throw new Error("missing result");
  expect(result.bands_used).toEqual([1, 2, 3]);
  expect(result.vector_url).toContain(".geojson");
  expect(result.model_name).toBe("YOLO11s-OBB");
});

it("keeps source and analysis grids distinct after stream and history parsing", () => {
  const result = parseToolResult({ type: "raster_inspect", imagery_id: "fec6252c9325",
    width: 4096, height: 4096, band_count: 4, resampled: true,
    source_grid: { width: 6144, height: 6144, pixel_size: [0.8, 0.8] },
    analysis_grid: { width: 4096, height: 4096, pixel_size: [1.2, 1.2] },
    bounds_wgs84: [114.18, 24.85, 114.23, 24.90], center_wgs84: [114.205, 24.875] });
  expect(result?.source_grid?.width).toBe(6144);
  expect(result?.analysis_grid?.pixel_size).toEqual([1.2, 1.2]);
  expect(result?.resampled).toBe(true);
  expect(result?.center_wgs84).toEqual([114.205, 24.875]);
});

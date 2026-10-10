import { describe, expect, it } from "vitest";
import { createStreamHandlers, parseGeospatialResult } from "../chat-events";
import { layersFromTurns } from "../layers";
import { reportsFromTurns } from "../reports";
import type { ChatTurn } from "../../types";

import { maskPayload } from "./mask-fixtures";

describe("mask result contract", () => {
  it.each(["water_mask", "cloud_mask"])("accepts %s from streamed done and preserves counts/method", (type) => {
    let turns: ChatTurn[] = [{ id: "answer", role: "assistant", content: "" }];
    const handlers = createStreamHandlers(update => { turns = typeof update === "function" ? update(turns) : update; }, "answer");
    handlers.onDone?.({ geospatial_result: maskPayload(type) });
    expect(turns[0].geospatialResult).toMatchObject(maskPayload(type));
  });
  it("preserves null official cloud amounts without zero coercion", () => {
    const payload = maskPayload();
    const parsed = parseGeospatialResult({ ...payload, stats: { method: "heuristic", cloud_pct: null, shadow_pct: null, clear_pct: null, candidate_bright_pct: 12, candidate_dark_pct: 5 } });
    expect(parsed).toMatchObject({ stats: { cloud_pct: null, candidate_bright_pct: 12, method: "heuristic" } });
  });
  it("keeps historical masks without claiming a method", () => {
    expect(parseGeospatialResult({ ...maskPayload(), stats: { cloud_pct: 20 } })).toMatchObject({ stats: { cloud_pct: 20 } });
  });
  it.each([NaN, Infinity, -1, 101, "60"])("rejects invalid water percentages %s", value => {
    expect(parseGeospatialResult({ ...maskPayload("water_mask"), stats: { water_pct: value } })).toBeUndefined();
  });
  it("rejects cross-origin images, malformed grids and impossible count totals", () => {
    expect(parseGeospatialResult({ ...maskPayload(), result_url: "https://evil.example/mask.png" })).toBeUndefined();
    expect(parseGeospatialResult({ ...maskPayload(), bounds: [114, NaN, 115, 25] })).toBeUndefined();
    expect(parseGeospatialResult({ ...maskPayload(), stats: { total_pixels: 10, valid_pixels: 12, nodata_pixels: 0 } })).toBeUndefined();
  });
  it.each(["ndvi", "spectral_index"])("preserves calibrated provenance and counts on %s", type => {
    const payload = maskPayload("water_mask");
    expect(parseGeospatialResult({ ...payload, type, index_type: "evi", stats: { ...payload.stats, min: 0, max: 1, mean: .6, std: .1, index_type: "evi" } })).toMatchObject({ stats: { calibration: payload.stats.calibration, resolved_bands: { green: 2, nir: 4 }, total_pixels: 100 } });
  });
  it("keeps declared band input quantity and discards unrelated payload fields", () => {
    const payload = maskPayload("water_mask");
    const parsed = parseGeospatialResult({ ...payload, stats: { ...payload.stats, calibration: { method: "declared_reflectance", bands: { green: { band_index: 2, scale: .0001, offset: -.1, input_quantity: "dn", quantity: "surface_reflectance", applied: true, input_applied: false } } }, unrelated_raw_context: "not-analysis-metadata" } });
    expect(parsed).toMatchObject({ stats: { calibration: { bands: { green: { input_quantity: "dn", quantity: "surface_reflectance", input_applied: false } } } } });
    expect(JSON.stringify(parsed)).not.toContain("not-analysis-metadata");
  });
  it("adds masks above imagery and keeps per-run controls", () => {
    const mask = parseGeospatialResult(maskPayload())!;
    const turns: ChatTurn[] = [{ id: "mask", role: "assistant", content: "", geospatialResult: mask }, { id: "preview", role: "assistant", content: "", geospatialResult: { type: "preview", imagery_id: "image", result_url: "/preview.png", bounds: [114, 24, 115, 25] } }];
    const layers = layersFromTurns(turns, {});
    expect(layers.map(layer => layer.name)).toEqual(["影像预览", "云/云影质量标记"]);
    expect(layers[1].legend?.map(entry => entry.label).join(" ")).toMatch(/未知.*雪.*地形/);
    expect(layersFromTurns(turns, { [layers[1].id]: { visible: false, opacity: .2 } })[1]).toMatchObject({ visible: false, opacity: .2 });
    const next = { ...mask, result_url: "/another-run.png" };
    expect(layersFromTurns([...turns, { ...turns[0], id: "next", geospatialResult: next }], {})).toHaveLength(3);
  });
  it("exports heuristic candidates rather than null cloud amounts", () => {
    const result = parseGeospatialResult({ ...maskPayload(), stats: { method: "heuristic", cloud_pct: null, candidate_bright_pct: 12, candidate_dark_pct: 5 } })!;
    const entries = reportsFromTurns([{ id: "r", role: "assistant", content: "", geospatialResult: result }]);
    expect(entries[0].title).toContain("疑似亮暗");
    expect(entries[0].stats).toContainEqual({ label: "疑似亮区", value: "12%" });
    expect(entries[0].stats.some(stat => stat.label === "云量")).toBe(false);
  });
});

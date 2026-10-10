import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GeospatialSummary } from "../GeospatialSummary";
import { parseGeospatialResult } from "../../lib/chat-events";
import { maskPayload } from "../../lib/__tests__/mask-fixtures";

describe("mask result cards", () => {
  it("shows quality provenance, unknown/snow/terrain and valid denominator", () => {
    render(<GeospatialSummary result={parseGeospatialResult(maskPayload())!} />);
    expect(screen.getByText("云标记：20%")).toBeInTheDocument();
    expect(screen.getByText("未知：10%")).toBeInTheDocument();
    expect(screen.getByText("雪/冰：10%")).toBeInTheDocument();
    expect(screen.getByText("地形阴影：10%")).toBeInTheDocument();
    expect(screen.getByText(/sentinel2_scl.*sentinel2/)).toBeInTheDocument();
    expect(screen.getByText(/占比分母：全网格/)).toBeInTheDocument();
    expect(screen.getByText(/未标记不保证可分析/)).toBeInTheDocument();
  });
  it("does not turn null cloud amounts into 0% for the heuristic", () => {
    const payload = maskPayload();
    render(<GeospatialSummary result={parseGeospatialResult({ ...payload, stats: { method: "heuristic", cloud_pct: null, shadow_pct: null, clear_pct: null, candidate_bright_pct: 12, candidate_dark_pct: null } })!} />);
    expect(screen.getByText("疑似亮暗区（未验证）")).toBeInTheDocument();
    expect(screen.getByText("疑似亮区：12%")).toBeInTheDocument();
    expect(screen.getByText("疑似暗区：未返回")).toBeInTheDocument();
    expect(screen.queryByText(/云标记：/)).not.toBeInTheDocument();
    expect(screen.queryByText(/0%/)).not.toBeInTheDocument();
  });
  it("distinguishes missing quality amounts from a legitimate zero cloud flag", () => {
    render(<GeospatialSummary result={parseGeospatialResult({ ...maskPayload(), stats: { method: "quality_mask", cloud_pct: null, shadow_pct: 0 } })!} />);
    expect(screen.getByText("云标记：未返回")).toBeInTheDocument();
    expect(screen.getByText("云影标记：0%")).toBeInTheDocument();
  });
  it("labels historical cloud masks without a method as unknown", () => {
    render(<GeospatialSummary result={parseGeospatialResult({ ...maskPayload(), stats: { cloud_pct: 20 } })!} />);
    expect(screen.getByText("云/云影历史结果（来源未知）")).toBeInTheDocument();
    expect(screen.getByText(/不能当作可信云量/)).toBeInTheDocument();
  });
  it("shows water threshold/calibration without losing report action", () => {
    const generate = vi.fn();
    render(<GeospatialSummary result={parseGeospatialResult(maskPayload("water_mask"))!} onGenerateReport={generate} />);
    expect(screen.getByText("水体：60%")).toBeInTheDocument();
    expect(screen.getByText("NDWI 阈值：0")).toBeInTheDocument();
    expect(screen.getByText("定标来源：declared_reflectance")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "生成 Word 报告" }));
    expect(generate).toHaveBeenCalledWith("image");
  });
  it("shows uncalibrated spectral ratios as relative, not reflectance", () => {
    const payload = maskPayload("water_mask");
    render(<GeospatialSummary result={parseGeospatialResult({ ...payload, type: "ndvi", stats: { min: 0, max: 1, mean: .6, std: .1, calibrated: false, calibration: { method: "uncalibrated_relative" }, total_pixels: 100, valid_pixels: 90 } })!} />);
    expect(screen.getByText("定标来源：未定标，相对值")).toBeInTheDocument();
    expect(screen.getByText("有效像元：90")).toBeInTheDocument();
  });
});

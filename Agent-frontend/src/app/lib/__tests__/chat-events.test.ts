import { describe, it, expect } from "vitest";
import { parseGeospatialResult } from "../chat-events";
import { layersFromTurns } from "../layers";
import type { ChatTurn } from "../../types";

describe("parseGeospatialResult — report 类型", () => {
  it("接受合法的 report 结果（带 download_url）", () => {
    const parsed = parseGeospatialResult({
      type: "report",
      imagery_id: "d722c20e1234",
      filename: "report_x.docx",
      download_url: "/api/imagery/d722c20e1234/results/report_x.docx",
    });
    expect(parsed).toEqual({
      type: "report",
      imagery_id: "d722c20e1234",
      filename: "report_x.docx",
      download_url: "/api/imagery/d722c20e1234/results/report_x.docx",
    });
  });

  it("report 缺 download_url 时拒绝（非法输入）", () => {
    expect(
      parseGeospatialResult({ type: "report", imagery_id: "d722c20e1234", filename: "x.docx" }),
    ).toBeUndefined();
  });

  it("report 不要求 result_url（与图层类不同形态）", () => {
    // 回归守门：report 走独立分支，不应被通用的 result_url 必填校验拦掉。
    const parsed = parseGeospatialResult({
      type: "report",
      imagery_id: "abcdef012345",
      download_url: "/api/imagery/abcdef012345/results/r.docx",
    });
    expect(parsed?.type).toBe("report");
    // filename 缺省时回退默认名
    expect((parsed as { filename: string }).filename).toBe("report.docx");
  });

  it("仍正确解析既有 segmentation（未回归）", () => {
    const parsed = parseGeospatialResult({
      type: "segmentation",
      imagery_id: "d722c20e1234",
      result_url: "/api/imagery/d722c20e1234/results/seg.png",
      bounds: null,
      classes: [{ label: "背景", percentage: 91.307, pixel_count: 913, color: "#000" }],
    });
    expect(parsed?.type).toBe("segmentation");
  });
});

describe("layersFromTurns — report 不进地图图层", () => {
  it("report 结果不产生地图图层（无 result_url/bounds）", () => {
    const turns: ChatTurn[] = [
      {
        id: "t1",
        role: "system",
        content: "分析报告已生成",
        geospatialResult: {
          type: "report",
          imagery_id: "d722c20e1234",
          filename: "r.docx",
          download_url: "/api/imagery/d722c20e1234/results/r.docx",
        },
      },
    ];
    expect(layersFromTurns(turns, {})).toEqual([]);
  });

  it("report 与 segmentation 混合时，只有 segmentation 成图层", () => {
    const turns: ChatTurn[] = [
      {
        id: "t1",
        role: "assistant",
        content: "",
        geospatialResult: {
          type: "segmentation",
          imagery_id: "d722c20e1234",
          result_url: "/api/imagery/d722c20e1234/results/seg.png",
          bounds: null,
          total_pixels: 1000,
          classes: [],
        },
      },
      {
        id: "t2",
        role: "system",
        content: "报告已生成",
        geospatialResult: {
          type: "report",
          imagery_id: "d722c20e1234",
          filename: "r.docx",
          download_url: "/api/imagery/d722c20e1234/results/r.docx",
        },
      },
    ];
    const layers = layersFromTurns(turns, {});
    expect(layers).toHaveLength(1);
    expect(layers[0].kind).toBe("segmentation");
  });
});

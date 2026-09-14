import { describe, it, expect } from "vitest";
import { createStreamHandlers, parseGeospatialResult } from "../chat-events";
import { layersFromTurns } from "../layers";
import type { ChatTurn } from "../../types";

describe("思考摘要安全边界", () => {
  it("忽略服务端任意 label，使用本地固定文案并按阶段去重", () => {
    let turns: ChatTurn[] = [{ id: "assistant", role: "assistant", content: "" }];
    const setTurns = (update: ChatTurn[] | ((previous: ChatTurn[]) => ChatTurn[])) => {
      turns = typeof update === "function" ? update(turns) : update;
    };
    const stream = createStreamHandlers(setTurns, "assistant");

    stream.onThinkingSummary?.({ stage: "context", label: "RAW_CHAIN_SECRET" });
    stream.onThinkingSummary?.({ stage: "context", label: "第二次恶意覆盖" });

    expect(turns[0].thinkingSummary).toEqual([
      {
        stage: "context",
        status: "active",
      },
    ]);
    expect(JSON.stringify(turns)).not.toContain("RAW_CHAIN_SECRET");
  });
});

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

// ───────────────────────── scene_search（影像检索卡片） ─────────────────────────

describe("parseGeospatialResult scene_search", () => {
  const valid = {
    type: "scene_search",
    scenes: [
      {
        key: "ab12cd34ef56",
        satellite: "Sentinel-2B",
        item_id: "S2B_X",
        datetime: "2026-08-11T03:11:32+00:00",
        cloud_cover: 5.5,
        bbox: [113.9, 22.4, 114.3, 22.7],
        resolution_m: 10,
        display_name: "S2B_X",
        preview_url: "/api/scenes/ab12cd34ef56/preview",
        download_url: "/api/scenes/ab12cd34ef56/download",
      },
    ],
    notes: [],
  };

  it("解析合法的检索卡片", () => {
    const result = parseGeospatialResult(valid);
    expect(result?.type).toBe("scene_search");
    if (result?.type === "scene_search") {
      expect(result.scenes).toHaveLength(1);
      expect(result.scenes[0].key).toBe("ab12cd34ef56");
      expect(result.scenes[0].preview_url).toContain("/api/scenes/");
    }
  });

  it("缺 preview_url / bbox 的场景项被丢弃而不是整卡失效", () => {
    const result = parseGeospatialResult({
      ...valid,
      scenes: [valid.scenes[0], { key: "x", satellite: "S" }, { ...valid.scenes[0], bbox: [1, 2] }],
    });
    expect(result?.type).toBe("scene_search");
    if (result?.type === "scene_search") expect(result.scenes).toHaveLength(1);
  });

  it("scenes 非数组时整体拒绝", () => {
    expect(parseGeospatialResult({ type: "scene_search", scenes: "nope" })).toBeUndefined();
  });
});

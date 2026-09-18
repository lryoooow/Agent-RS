import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RightPanel } from "../RightPanel";
import type { RSLayer } from "../../lib/layers";

const layer: RSLayer = {
  id: "sam3-long-result",
  name: "SAM3 建筑道路农田水体开放词汇实例分割结果",
  sublabel: "包含很长的分析成果文件名和多个目标概念",
  kind: "segmentation",
  visible: true,
  opacity: 0.72,
  color: "#fb7185",
  imageryId: "abcdef012345",
  legend: [{ color: "#fb7185", label: "建筑目标及其非常长的分类说明" }],
  meta: { "结果文件": "sam3_building_road_farmland_water_very_long_result_filename.png" },
};

describe("图层悬浮面板", () => {
  beforeEach(() => {
    localStorage.clear();
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 1280 });
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 900 });
  });

  it("允许用键盘调整宽高并恢复默认大小", () => {
    render(<RightPanel layers={[layer]} onToggle={vi.fn()} onOpacity={vi.fn()} onRemove={vi.fn()} />);
    const panel = screen.getByTestId("layer-panel");
    expect(panel).toHaveStyle({ width: "360px", height: "560px" });

    fireEvent.keyDown(screen.getByRole("button", { name: "调整图层面板宽度" }), { key: "ArrowLeft" });
    fireEvent.keyDown(screen.getByRole("button", { name: "调整图层面板高度" }), { key: "ArrowUp" });
    expect(panel).toHaveStyle({ width: "370px", height: "550px" });

    fireEvent.doubleClick(screen.getByRole("button", { name: "调整图层面板宽高" }));
    expect(panel).toHaveStyle({ width: "360px", height: "560px" });
  });

  it("长名称、图例和元数据使用换行布局而不是裁掉右侧内容", () => {
    render(<RightPanel layers={[layer]} onToggle={vi.fn()} onOpacity={vi.fn()} onRemove={vi.fn()} />);
    expect(screen.getByText(layer.name)).toHaveClass("break-words");
    fireEvent.click(screen.getByRole("button", { name: "图例" }));
    expect(screen.getByText(layer.legend![0].label)).toHaveClass("break-words");
    expect(screen.getByText(layer.meta!["结果文件"])).toHaveClass("break-words");
    expect(screen.getByTestId("layer-panel-scroll")).toHaveClass("overflow-x-hidden");
  });
});

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RoiAnalysisPanel } from "../RoiAnalysisPanel";
import { apiFetch } from "../../lib/http";
vi.mock("../../lib/http",()=>({apiFetch:vi.fn()}));
const roi={kind:"geo" as const,bbox:[114,24,114.01,24.01] as [number,number,number,number]};
describe("ROI actions",()=>{
  it("enables map extraction without an uploaded image and keeps search separate",async()=>{
    vi.mocked(apiFetch).mockResolvedValue(new Response(JSON.stringify({status:"ready",source:"current_map",message:"将直接使用地图影像"})));
    const onRun=vi.fn(),onSearch=vi.fn();
    render(<RoiAnalysisPanel roi={roi} source="current_map" activeImageryId={null} loading={false} onSourceChange={vi.fn()} onRun={onRun} onSearch={onSearch} onClear={vi.fn()}/>);
    await waitFor(()=>expect(screen.getByRole("button",{name:"提取建筑"})).toBeEnabled());
    fireEvent.click(screen.getByRole("button",{name:"提取建筑"}));
    expect(onRun).toHaveBeenCalledWith("building");expect(onSearch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button",{name:"搜索此区域影像"}));expect(onSearch).toHaveBeenCalledOnce();
  });
  it("cannot reuse an earlier box readiness while the new box is being checked",async()=>{
    let finish!: (value:Response)=>void;
    vi.mocked(apiFetch).mockResolvedValueOnce(new Response(JSON.stringify({status:"ready",message:"ready"})))
      .mockReturnValueOnce(new Promise(resolve=>{finish=resolve;}));
    const props={source:"current_map" as const,activeImageryId:null,loading:false,onSourceChange:vi.fn(),onRun:vi.fn(),onSearch:vi.fn(),onClear:vi.fn()};
    const view=render(<RoiAnalysisPanel roi={roi} {...props}/>);
    await waitFor(()=>expect(screen.getByRole("button",{name:"提取建筑"})).toBeEnabled());
    view.rerender(<RoiAnalysisPanel roi={{kind:"geo",bbox:[110,20,120,30]}} {...props}/>);
    expect(screen.getByRole("button",{name:"提取建筑"})).toBeDisabled();
    await act(async()=>finish(new Response(JSON.stringify({status:"blocked",message:"选区过大"}))));
    expect(screen.getByRole("button",{name:"提取建筑"})).toBeDisabled();
  });
});

import { expect, it } from "vitest";
import { layersFromTurns } from "../layers";
import { roiIntersectsBounds } from "../roi";
import type { ChatTurn } from "../../types";
it("draws imagery below distinct ROI artifacts, preserving newest on top", () => {
  const turns: ChatTurn[] = [
    {id:"a",role:"assistant",content:"",geospatialResult:{type:"segmentation",imagery_id:"fec6252c9325",result_url:"/roi-a.png",bounds:[1,2,3,4],total_pixels:1,classes:[]}},
    {id:"b",role:"system",content:"",geospatialResult:{type:"preview",imagery_id:"fec6252c9325",result_url:"/preview.png",bounds:[1,2,3,4]}},
    {id:"c",role:"assistant",content:"",geospatialResult:{type:"segmentation",imagery_id:"fec6252c9325",result_url:"/roi-b.png",bounds:[2,3,4,5],total_pixels:1,classes:[]}},
  ];
  const layers=layersFromTurns(turns,{});
  expect(layers.map(l=>l.url)).toEqual(["/preview.png","/roi-a.png","/roi-b.png"]);
  const hidden=layersFromTurns(turns,{[layers[1].id]:{visible:false}});
  expect(hidden[1].visible).toBe(false);
  expect(hidden[2].visible).toBe(true);
});
it("detects the actual old-image ROI mismatch but accepts the imported scene",()=>{
  const roi={kind:"geo" as const,bbox:[114.276528,25.109657,114.298709,25.127011] as [number,number,number,number]};
  expect(roiIntersectsBounds(roi,[114.18,24.84,114.23,24.90])).toBe(false);
  expect(roiIntersectsBounds(roi,[112.79,23.48,115.07,25.61])).toBe(true);
  expect(roiIntersectsBounds(roi,null)).toBeNull();
});

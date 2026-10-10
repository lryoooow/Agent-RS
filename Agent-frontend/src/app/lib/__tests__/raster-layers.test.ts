import { layersFromTurns } from "../layers";
import { parseGeospatialResult } from "../chat-events";
import { maskPayload } from "./mask-fixtures";
import { expect,it,vi } from "vitest";
import type { Map as MapLibreMap } from "maplibre-gl";
import { syncRasterOverlays } from "../raster-layers";
import type { RSLayer } from "../layers";
it("updates changed sources and restores stacking after visibility toggles",()=>{
  const sources: Record<string,any>={};
  let layers: any[]=[{id:"base",type:"raster"},{id:"roi",type:"fill"},{id:"map-reference-roads",type:"line"},{id:"map-reference-labels",type:"raster"}];
  const updates=vi.fn();
  const map={
    getStyle:()=>({layers:[...layers],sources:structuredClone(sources)}),
    getLayer:(id:string)=>layers.find(l=>l.id===id),
    getSource:(id:string)=>sources[id] ? {updateImage:(value:any)=>{updates(id,value);Object.assign(sources[id],value);}} : undefined,
    addSource:(id:string,value:any)=>{sources[id]=value;},
    addLayer:(value:any)=>layers.push(value),
    setPaintProperty:vi.fn(),
    moveLayer:(id:string)=>{const value=layers.find(l=>l.id===id);layers=layers.filter(l=>l.id!==id);layers.push(value);},
    removeLayer:(id:string)=>{layers=layers.filter(l=>l.id!==id);},
    removeSource:(id:string)=>{delete sources[id];},
  } as unknown as MapLibreMap;
  const image={id:"image",name:"image",sublabel:"",kind:"imagery",visible:true,opacity:1,color:"",imageryId:"a",url:"a.png",bounds:[1,2,3,4]} as RSLayer & {bounds:[number,number,number,number]};
  const result={...image,id:"result",kind:"segmentation" as const,url:"result.png"};
  syncRasterOverlays(map,[image,result],s=>s);
  expect(layers.map(l=>l.id)).toEqual(["base","rs-img-image","rs-img-result","map-reference-roads","map-reference-labels","roi"]);
  syncRasterOverlays(map,[result],s=>s);
  syncRasterOverlays(map,[image,{...result,url:"new-result.png",bounds:[2,3,4,5]}],s=>s);
  expect(updates).toHaveBeenCalledWith("rs-src-result",{url:"new-result.png",coordinates:[[2,5],[4,5],[4,3],[2,3]]});
  expect(layers.map(l=>l.id)).toEqual(["base","rs-img-image","rs-img-result","map-reference-roads","map-reference-labels","roi"]);
  updates.mockClear();syncRasterOverlays(map,[image,{...result,url:"new-result.png",bounds:[2,3,4,5]}],s=>s);
  expect(updates).not.toHaveBeenCalled();
});

it("renders water/cloud masks above uploaded imagery and below geographic labels/ROI", () => {
 const sources: Record<string, any> = {};
 let layers: any[] = [{ id: "base", type: "raster" }, { id: "roi", type: "fill" }, { id: "map-reference-labels", type: "raster" }];
 const map = {
   getStyle: () => ({ layers: [...layers], sources: structuredClone(sources) }),
   getLayer: (id: string) => layers.find(layer => layer.id === id),
   getSource: (id: string) => sources[id],
   addSource: (id: string, value: any) => { sources[id] = value; },
   addLayer: (value: any) => layers.push(value), setPaintProperty: vi.fn(),
   moveLayer: (id: string) => { const value = layers.find(layer => layer.id === id); layers = layers.filter(layer => layer.id !== id); layers.push(value); },
   removeLayer: (id: string) => { layers = layers.filter(layer => layer.id !== id); },
   removeSource: (id: string) => { delete sources[id]; },
 } as unknown as MapLibreMap;
 const results = [parseGeospatialResult(maskPayload("water_mask"))!, parseGeospatialResult(maskPayload())!, parseGeospatialResult({ ...maskPayload(), type: "preview" })!];
 const derived = layersFromTurns(results.map((geospatialResult, index) => ({ id: String(index), role: "assistant", content: "", geospatialResult })), {}).filter((layer): layer is RSLayer & { bounds: [number, number, number, number] } => layer.bounds != null);
 syncRasterOverlays(map, derived, url => url);
 expect(layers.map(layer => layer.id)).toEqual(["base", ...derived.map(layer => `rs-img-${layer.id}`), "map-reference-labels", "roi"]);
 expect(sources[`rs-src-${derived[2].id}`].coordinates).toEqual([[114, 25], [115, 25], [115, 24], [114, 24]]);
 syncRasterOverlays(map, derived.slice(0, 2), url => url);
 expect(layers.map(layer => layer.id)).not.toContain(`rs-img-${derived[2].id}`);
 syncRasterOverlays(map, derived, url => url);
 expect(layers.map(layer => layer.id)).toEqual(["base", ...derived.map(layer => `rs-img-${layer.id}`), "map-reference-labels", "roi"]);
});

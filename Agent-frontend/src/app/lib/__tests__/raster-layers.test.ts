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

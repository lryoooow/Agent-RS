import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource, type ImageSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  Eye,
  EyeOff,
  Images,
  Layers3,
  Loader2,
  MapPin,
  Orbit,
  PlusCircle,
  Search,
  Satellite,
} from "lucide-react";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { ScrollArea } from "./ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { Slider } from "./ui/slider";
import {
  absoluteUrl,
  downloadSceneTif,
  fetchScenePreview,
  searchImagery,
  type SceneCard,
} from "../lib/imagery-search-api";
import { createSatelliteStyle, REFERENCE_PREFIX } from "../lib/map-style";
import type { Roi } from "../lib/roi";

export type SatelliteWorkspaceMode = "orbit" | "imagery";

export interface ScenePreviewRequest {
  token: number;
  scene: SceneCard;
}

const PREVIEW_SOURCE = "catalogue-preview-source";
const PREVIEW_LAYER = "catalogue-preview-layer";
const FOOTPRINT_SOURCE = "catalogue-preview-footprint-source";
const FOOTPRINT_LAYER = "catalogue-preview-footprint-layer";

const SATVIS_URL = (() => {
  const params = new URLSearchParams({
    ui: "full",
    lang: "zh-CN",
    layers: "NaturalEarth",
    scene: "3D",
    pixelratio: "1",
  });
  return `/satvis/index.html?${params.toString()}`;
})();

function validBounds(bounds: number[]): bounds is [number, number, number, number] {
  return bounds.length === 4 && bounds.every(Number.isFinite) && bounds[0] < bounds[2] && bounds[1] < bounds[3];
}

function imageCoordinates(bounds: [number, number, number, number]) {
  const [west, south, east, north] = bounds;
  return [
    [west, north],
    [east, north],
    [east, south],
    [west, south],
  ] as [[number, number], [number, number], [number, number], [number, number]];
}

function footprint(bounds: [number, number, number, number]) {
  const [west, south, east, north] = bounds;
  return {
    type: "Feature" as const,
    properties: {},
    geometry: {
      type: "Polygon" as const,
      coordinates: [[[west, north], [east, north], [east, south], [west, south], [west, north]]],
    },
  };
}

export function SatelliteWorkspace({
  active,
  mode,
  onModeChange,
  roi,
  roiSelectionVersion = 0,
  onSceneImport,
  onActivateImagery,
  onOpenWorkspace,
  previewRequest,
}: {
  active: boolean;
  mode: SatelliteWorkspaceMode;
  onModeChange: (mode: SatelliteWorkspaceMode) => void;
  roi: Roi | null;
  roiSelectionVersion?: number;
  onSceneImport: (key: string) => Promise<string | null>;
  onActivateImagery: (imageryId: string) => Promise<void>;
  onOpenWorkspace: () => void;
  previewRequest?: ScenePreviewRequest | null;
}) {
  const [orbitLoaded, setOrbitLoaded] = useState(false);
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const catalogueMapRef = useRef<maplibregl.Map | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const previewObjectUrlRef = useRef<string | null>(null);
  const previewAbortRef = useRef<AbortController | null>(null);
  const previewVersionRef = useRef(0);

  const [place, setPlace] = useState("");
  const [bbox, setBbox] = useState<number[] | null>(null);
  const [bboxLabel, setBboxLabel] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [cloudMax, setCloudMax] = useState(30);
  const [cloudUnlimited, setCloudUnlimited] = useState(false);
  const [source, setSource] = useState<"auto" | "sentinel2" | "landsat">("auto");
  const [limit, setLimit] = useState(10);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scenes, setScenes] = useState<SceneCard[]>([]);
  const [notes, setNotes] = useState<string[]>([]);
  const [searched, setSearched] = useState(false);
  const [importing, setImporting] = useState<string | null>(null);
  const [imported, setImported] = useState<Record<string, string>>({});
  const [activated, setActivated] = useState<Record<string, boolean>>({});
  const [downloading, setDownloading] = useState<string | null>(null);
  const [downloaded, setDownloaded] = useState<Record<string, string>>({});

  const [previewing, setPreviewing] = useState<string | null>(null);
  const [selectedScene, setSelectedScene] = useState<SceneCard | null>(null);
  const [previewVisible, setPreviewVisible] = useState(true);
  const [previewOpacity, setPreviewOpacity] = useState(0.9);

  useEffect(() => {
    if (active) setOrbitLoaded(true);
  }, [active]);

  useEffect(() => {
    if (roiSelectionVersion > 0 && active && roi?.kind === "geo") {
      setBbox([...roi.bbox]);
      setBboxLabel(`工作台框选区域 ${roi.bbox.map((value) => Number(value.toFixed(4))).join(", ")}`);
      setPlace("");
      onModeChange("imagery");
    }
  }, [active, onModeChange, roi, roiSelectionVersion]);

  // The catalogue owns its map. It never receives the workbench map ref, so a
  // search, preview or fit operation cannot move the analysis workspace.
  useEffect(() => {
    if (!active || mode !== "imagery" || !mapContainerRef.current || catalogueMapRef.current) return;
    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: createSatelliteStyle(true),
      center: [104, 35],
      zoom: 3.4,
      attributionControl: false,
      locale: {
        "AttributionControl.ToggleAttribution": "显示或隐藏地图版权信息",
        "Map.Title": "影像档案目录地图",
        "NavigationControl.ResetBearing": "拖动可旋转地图，点击恢复正北",
        "NavigationControl.ZoomIn": "放大地图",
        "NavigationControl.ZoomOut": "缩小地图",
      },
    });
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
    // The catalogue can already accept its own sources once the style exists.
    // Do not wait for every remote basemap/vector tile: a slow reference service
    // must not block a same-origin scene preview.
    map.once("styledata", () => setMapReady(true));
    catalogueMapRef.current = map;
  }, [active, mode]);

  useEffect(() => {
    if (!active || mode !== "imagery" || !mapReady) return;
    const frame = requestAnimationFrame(() => catalogueMapRef.current?.resize());
    return () => cancelAnimationFrame(frame);
  }, [active, mapReady, mode]);

  useEffect(() => () => {
    previewAbortRef.current?.abort();
    if (previewObjectUrlRef.current) URL.revokeObjectURL(previewObjectUrlRef.current);
    catalogueMapRef.current?.remove();
    catalogueMapRef.current = null;
  }, []);

  useEffect(() => {
    const map = catalogueMapRef.current;
    if (!mapReady || !map?.getLayer(PREVIEW_LAYER)) return;
    map.setPaintProperty(PREVIEW_LAYER, "raster-opacity", previewOpacity);
  }, [mapReady, previewOpacity]);

  useEffect(() => {
    const map = catalogueMapRef.current;
    if (!mapReady || !map?.getLayer(PREVIEW_LAYER)) return;
    map.setLayoutProperty(PREVIEW_LAYER, "visibility", previewVisible ? "visible" : "none");
    if (map.getLayer(FOOTPRINT_LAYER)) map.setLayoutProperty(FOOTPRINT_LAYER, "visibility", previewVisible ? "visible" : "none");
  }, [mapReady, previewVisible]);

  const previewOnMap = useCallback(async (scene: SceneCard) => {
    const map = catalogueMapRef.current;
    if (!map || !mapReady) return;
    if (!validBounds(scene.bbox)) {
      setError(`影像 ${scene.item_id} 缺少有效地理范围，无法叠加预览。`);
      return;
    }

    const requestVersion = ++previewVersionRef.current;
    previewAbortRef.current?.abort();
    const abort = new AbortController();
    previewAbortRef.current = abort;
    setPreviewing(scene.key);
    setError(null);

    try {
      const blob = await fetchScenePreview(scene.preview_url, { signal: abort.signal });
      const objectUrl = URL.createObjectURL(blob);
      if (requestVersion !== previewVersionRef.current || abort.signal.aborted) {
        URL.revokeObjectURL(objectUrl);
        return;
      }

      const coordinates = imageCoordinates(scene.bbox);
      const oldObjectUrl = previewObjectUrlRef.current;
      const imageSource = map.getSource(PREVIEW_SOURCE) as ImageSource | undefined;
      if (imageSource) imageSource.updateImage({ url: objectUrl, coordinates });
      else map.addSource(PREVIEW_SOURCE, { type: "image", url: objectUrl, coordinates });

      const firstReferenceLayer = map.getStyle().layers?.find((layer) => layer.id.startsWith(REFERENCE_PREFIX))?.id;
      if (!map.getLayer(PREVIEW_LAYER)) {
        map.addLayer({ id: PREVIEW_LAYER, type: "raster", source: PREVIEW_SOURCE, paint: { "raster-opacity": previewOpacity, "raster-fade-duration": 120 } }, firstReferenceLayer);
      }

      const outline = footprint(scene.bbox);
      const outlineSource = map.getSource(FOOTPRINT_SOURCE) as GeoJSONSource | undefined;
      if (outlineSource) outlineSource.setData(outline);
      else map.addSource(FOOTPRINT_SOURCE, { type: "geojson", data: outline });
      if (!map.getLayer(FOOTPRINT_LAYER)) {
        map.addLayer({ id: FOOTPRINT_LAYER, type: "line", source: FOOTPRINT_SOURCE, paint: { "line-color": "#2dd4bf", "line-width": 2, "line-opacity": 0.95 } }, firstReferenceLayer);
      }

      previewObjectUrlRef.current = objectUrl;
      if (oldObjectUrl) setTimeout(() => URL.revokeObjectURL(oldObjectUrl), 1_000);
      setSelectedScene(scene);
      setPreviewVisible(true);
      map.setLayoutProperty(PREVIEW_LAYER, "visibility", "visible");
      map.setLayoutProperty(FOOTPRINT_LAYER, "visibility", "visible");
      const [west, south, east, north] = scene.bbox;
      map.fitBounds([[west, south], [east, north]], { padding: 54, duration: 700 });
    } catch (exc) {
      if (!abort.signal.aborted) setError(`预览 ${scene.item_id} 失败：${exc instanceof Error ? exc.message : "未知错误"}`);
    } finally {
      if (requestVersion === previewVersionRef.current) setPreviewing(null);
    }
  }, [mapReady, previewOpacity]);

  useEffect(() => {
    if (!active || mode !== "imagery" || !mapReady || !previewRequest) return;
    void previewOnMap(previewRequest.scene);
  }, [active, mapReady, mode, previewOnMap, previewRequest]);

  const useCurrentView = () => {
    const map = catalogueMapRef.current;
    if (!map) return;
    const bounds = map.getBounds();
    const next = [Number(bounds.getWest().toFixed(4)), Number(bounds.getSouth().toFixed(4)), Number(bounds.getEast().toFixed(4)), Number(bounds.getNorth().toFixed(4))];
    setBbox(next);
    setBboxLabel(`目录地图当前视野 ${next.join(", ")}`);
    setPlace("");
  };

  const useRoi = () => {
    if (roi?.kind !== "geo") return;
    setBbox([...roi.bbox]);
    setBboxLabel(`工作台框选区域 ${roi.bbox.map((value) => Number(value.toFixed(4))).join(", ")}`);
    setPlace("");
  };

  const runSearch = async () => {
    if (!bbox && !place.trim()) {
      setError("请填写地名，或使用目录地图当前视野 / 工作台框选区域设定检索范围。");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await searchImagery({ bbox: bbox ?? undefined, place: place.trim() || undefined, start_date: startDate || undefined, end_date: endDate || undefined, cloud_max: cloudUnlimited ? undefined : cloudMax, source, limit });
      setScenes(response.scenes);
      setNotes(response.notes);
      setSearched(true);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "检索失败，请稍后重试。");
    } finally {
      setLoading(false);
    }
  };

  const downloadTif = async (scene: SceneCard) => {
    setDownloading(scene.key);
    setError(null);
    try {
      const result = await downloadSceneTif(scene.key, scene.item_id);
      setDownloaded((previous) => ({ ...previous, [scene.key]: `${result.filename}（${(result.sizeBytes / 1024 / 1024).toFixed(1)} MB）` }));
    } catch (exc) {
      setError(`下载 ${scene.item_id} 失败：${exc instanceof Error ? exc.message : "未知错误"}`);
    } finally {
      setDownloading(null);
    }
  };

  const importToPlatform = async (scene: SceneCard) => {
    setImporting(scene.key);
    setError(null);
    try {
      const imageryId = await onSceneImport(scene.key);
      if (!imageryId) throw new Error("导入未完成，请查看平台提示。");
      setImported((previous) => ({ ...previous, [scene.key]: imageryId }));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "导入失败，请稍后重试。");
    } finally {
      setImporting(null);
    }
  };

  const activateImagery = async (sceneKey: string, imageryId: string) => {
    setError(null);
    try {
      await onActivateImagery(imageryId);
      setActivated((previous) => ({ ...previous, [sceneKey]: true }));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "设置分析影像失败。");
    }
  };

  const resultSummary = useMemo(() => {
    if (loading) return "正在检索公开影像档案…";
    if (!searched) return "设置条件后开始检索";
    return `${scenes.length} 景影像 · 点击预览可叠加到目录地图`;
  }, [loading, scenes.length, searched]);

  return (
    <section aria-label="卫星影像" className={`${active ? "fixed" : "hidden"} inset-x-0 bottom-0 top-[72px] z-[35] flex min-h-0 flex-col bg-background`}>
      <header className="flex h-[54px] shrink-0 items-center justify-between border-b border-border bg-card/95 px-4 backdrop-blur">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-xl border border-primary/25 bg-primary/10"><Satellite className="size-4.5 text-primary" /></div>
          <div className="hidden sm:block"><h1 className="text-[14px] font-semibold">卫星影像中心</h1><div className="font-mono text-[10px] text-muted-foreground">轨道态势与影像档案独立运行</div></div>
        </div>
        <div className="grid grid-cols-2 rounded-xl border border-border bg-muted p-1">
          <button type="button" aria-current={mode === "orbit" ? "page" : undefined} onClick={() => onModeChange("orbit")} className={`flex h-9 items-center justify-center gap-2 rounded-lg px-5 text-[13px] font-medium transition-colors ${mode === "orbit" ? "bg-card text-primary shadow-sm" : "text-muted-foreground hover:text-foreground"}`}><Orbit className="size-4" />轨道态势</button>
          <button type="button" aria-current={mode === "imagery" ? "page" : undefined} onClick={() => onModeChange("imagery")} className={`flex h-9 items-center justify-center gap-2 rounded-lg px-5 text-[13px] font-medium transition-colors ${mode === "imagery" ? "bg-card text-primary shadow-sm" : "text-muted-foreground hover:text-foreground"}`}><Images className="size-4" />影像档案</button>
        </div>
        <Button variant="outline" size="sm" className="h-9 text-[12px]" onClick={onOpenWorkspace}>返回工作台</Button>
      </header>

      <div className={`relative min-h-0 flex-1 bg-black ${mode === "orbit" ? "block" : "hidden"}`}>
        {orbitLoaded && <iframe src={SATVIS_URL} title="Satvis 卫星轨道态势" className="absolute inset-0 size-full border-0" allow="fullscreen" />}
      </div>

      <div className={`min-h-0 flex-1 ${mode === "imagery" ? "grid md:grid-cols-[280px_minmax(0,1fr)_350px]" : "hidden"}`}>
        <aside className="z-10 flex min-h-0 flex-col border-r border-border bg-sidebar">
          <div className="border-b border-border px-4 py-3"><div className="flex items-center gap-2 text-[13px] font-semibold"><Search className="size-4 text-primary" />影像检索条件</div><p className="mt-1 text-[10.5px] text-muted-foreground">检索只操作目录地图，不改变工作台视角</p></div>
          <ScrollArea className="min-h-0 flex-1"><div className="flex flex-col gap-4 p-4">
            <div className="flex flex-col gap-1.5">
              <Label className="text-[12px]">区域</Label>
              <div className="flex items-center gap-2"><MapPin className="size-3.5 shrink-0 text-muted-foreground" /><Input value={place} onChange={(event) => { setPlace(event.target.value); setBbox(null); setBboxLabel(""); }} placeholder="地名，如 杭州市" className="h-8 bg-input-background text-[12px]" /></div>
              <div className="grid grid-cols-2 gap-2"><Button variant="outline" size="sm" className="h-8 text-[11px]" onClick={useCurrentView}>目录地图视野</Button><Button variant="outline" size="sm" className="h-8 text-[11px]" onClick={useRoi} disabled={roi?.kind !== "geo"}>工作台框选</Button></div>
              {bboxLabel && <p className="font-mono text-[9.5px] leading-relaxed text-muted-foreground">{bboxLabel}</p>}
            </div>

            <div className="grid grid-cols-2 gap-2"><div className="flex flex-col gap-1.5"><Label className="text-[12px]">开始日期</Label><Input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} className="h-8 bg-input-background font-mono text-[11px]" /></div><div className="flex flex-col gap-1.5"><Label className="text-[12px]">结束日期</Label><Input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} className="h-8 bg-input-background font-mono text-[11px]" /></div></div>

            <div className="flex flex-col gap-2"><div className="flex items-center justify-between"><Label className="text-[12px]">云量上限</Label><span className="font-mono text-[10px] text-muted-foreground">{cloudUnlimited ? "不限" : `≤ ${cloudMax}%`}</span></div><Slider value={[cloudMax]} min={0} max={100} step={5} onValueChange={([value]) => setCloudMax(value)} disabled={cloudUnlimited} /><label className="flex items-center gap-1.5 text-[11px] text-muted-foreground"><input type="checkbox" checked={cloudUnlimited} onChange={(event) => setCloudUnlimited(event.target.checked)} className="size-3 accent-[var(--primary)]" />不限制云量</label></div>

            <div className="grid grid-cols-2 gap-2">
              <div className="flex flex-col gap-1.5"><Label className="text-[12px]">数据源</Label><Select value={source} onValueChange={(value) => setSource(value as typeof source)}><SelectTrigger className="h-8 bg-input-background text-[12px]"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="auto">自动（双源）</SelectItem><SelectItem value="sentinel2">Sentinel-2</SelectItem><SelectItem value="landsat">Landsat</SelectItem></SelectContent></Select></div>
              <div className="flex flex-col gap-1.5"><Label className="text-[12px]">结果数</Label><Select value={String(limit)} onValueChange={(value) => setLimit(Number(value))}><SelectTrigger className="h-8 bg-input-background text-[12px]"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="5">5 景</SelectItem><SelectItem value="10">10 景</SelectItem><SelectItem value="20">20 景</SelectItem></SelectContent></Select></div>
            </div>

            <Button onClick={runSearch} disabled={loading} className="h-9 text-[12.5px]">{loading ? <Loader2 className="size-3.5 animate-spin" /> : <Search className="size-3.5" />}检索影像</Button>
            {error && <div className="flex items-start gap-1.5 rounded-lg border border-destructive/40 bg-destructive/10 p-2 text-[11px] text-destructive"><AlertTriangle className="mt-0.5 size-3.5 shrink-0" />{error}</div>}
            {notes.length > 0 && <p className="text-[10px] leading-relaxed text-muted-foreground">{notes.join("；")}</p>}
          </div></ScrollArea>
        </aside>

        <main className="relative min-h-[320px] overflow-hidden bg-black">
          <div ref={mapContainerRef} className="absolute left-0 top-0 size-full" aria-label="影像档案目录地图" />
          {!mapReady && <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-background/70 text-[12px] text-muted-foreground"><Loader2 className="mr-2 size-4 animate-spin" />正在加载目录地图…</div>}
          {selectedScene && <div className="absolute bottom-5 left-1/2 z-10 w-[min(520px,calc(100%-32px))] -translate-x-1/2 rounded-xl border border-white/15 bg-black/80 p-3 text-white shadow-2xl backdrop-blur">
            <div className="flex items-center justify-between gap-3"><div className="min-w-0"><div className="truncate text-[12px] font-medium">{selectedScene.display_name}</div><div className="mt-0.5 font-mono text-[9.5px] text-white/60">{selectedScene.datetime.slice(0, 10)} · {selectedScene.resolution_m ?? "?"}m · {selectedScene.item_id}</div></div><Button variant="outline" size="sm" className="h-7 shrink-0 border-white/20 bg-white/5 px-2 text-[10px] text-white hover:bg-white/10" onClick={() => setPreviewVisible((value) => !value)}>{previewVisible ? <EyeOff className="size-3" /> : <Eye className="size-3" />}{previewVisible ? "隐藏" : "显示"}</Button></div>
            <div className="mt-2 flex items-center gap-2"><Layers3 className="size-3.5 text-primary" /><span className="text-[10px] text-white/60">透明度</span><Slider value={[Math.round(previewOpacity * 100)]} min={10} max={100} step={5} onValueChange={([value]) => setPreviewOpacity(value / 100)} className="flex-1" /><span className="w-8 text-right font-mono text-[9.5px] text-white/60">{Math.round(previewOpacity * 100)}%</span></div>
          </div>}
        </main>

        <aside className="z-10 flex min-h-0 flex-col border-l border-border bg-sidebar">
          <div className="border-b border-border px-4 py-3"><div className="flex items-center gap-2 text-[13px] font-semibold"><Images className="size-4 text-primary" />检索结果</div><p className="mt-1 font-mono text-[10px] text-muted-foreground">{resultSummary}</p></div>
          <ScrollArea className="min-h-0 flex-1"><div className="flex flex-col gap-2.5 p-4">
            {!searched && !loading && <p className="text-[11.5px] leading-relaxed text-muted-foreground">支持 Sentinel-2 地表反射率与 Landsat 8/9。预览在当前页面叠加，导入后不会自动跳转或替换工作台影像。</p>}
            {loading && <div className="flex items-center gap-2 text-[11.5px] text-muted-foreground"><Loader2 className="size-3.5 animate-spin" />正在检索公开影像档案…</div>}
            {scenes.map((scene) => {
              const imageryId = imported[scene.key];
              const isPreviewing = previewing === scene.key;
              return <article key={scene.key} className={`overflow-hidden rounded-xl border bg-card transition-colors ${selectedScene?.key === scene.key ? "border-primary/60 ring-1 ring-primary/25" : "border-border"}`}>
                <button type="button" className="relative block w-full cursor-pointer text-left" onClick={() => void previewOnMap(scene)} title="在目录地图叠加该景影像"><img src={absoluteUrl(scene.preview_url)} alt={scene.display_name} loading="lazy" className="h-32 w-full bg-muted object-cover" />{isPreviewing && <span className="absolute inset-0 flex items-center justify-center bg-black/55 text-[11px] text-white"><Loader2 className="mr-2 size-4 animate-spin" />正在叠加预览</span>}</button>
                <div className="flex flex-col gap-1.5 p-2.5">
                  <div className="flex items-center justify-between gap-2"><span className="truncate text-[12px] font-medium">{scene.satellite}</span><Badge variant="secondary" className="font-mono text-[10px]">{scene.resolution_m ?? "?"}m</Badge></div>
                  <p className="truncate font-mono text-[9.5px] text-muted-foreground">{scene.datetime.slice(0, 10)} · 云量 {scene.cloud_cover != null ? `${scene.cloud_cover}%` : "—"} · {scene.item_id}</p>
                  <div className="mt-1 grid grid-cols-3 gap-1.5"><Button variant="outline" size="sm" className="h-7 px-1 text-[10.5px]" disabled={isPreviewing} onClick={() => void previewOnMap(scene)}>{isPreviewing ? <Loader2 className="size-3 animate-spin" /> : <Eye className="size-3" />}预览</Button><Button variant="outline" size="sm" className="h-7 px-1 text-[10.5px]" disabled={downloading === scene.key} onClick={() => void downloadTif(scene)}>{downloading === scene.key ? <Loader2 className="size-3 animate-spin" /> : <Download className="size-3" />}TIF</Button><Button variant="secondary" size="sm" className="h-7 px-1 text-[10.5px]" disabled={!!imageryId || importing === scene.key} onClick={() => void importToPlatform(scene)}>{imageryId ? <CheckCircle2 className="size-3 text-primary" /> : importing === scene.key ? <Loader2 className="size-3 animate-spin" /> : <PlusCircle className="size-3" />}{imageryId ? "已导入" : "导入"}</Button></div>
                  {downloaded[scene.key] && <p className="font-mono text-[9.5px] text-muted-foreground">已下载 {downloaded[scene.key]}</p>}
                  {imageryId && <div className="mt-1 rounded-lg border border-primary/25 bg-primary/5 p-2"><p className="font-mono text-[9.5px] text-primary">平台影像 {imageryId}</p><div className="mt-1.5 grid grid-cols-2 gap-1.5"><Button variant={activated[scene.key] ? "secondary" : "outline"} size="sm" className="h-7 text-[10px]" disabled={activated[scene.key]} onClick={() => void activateImagery(scene.key, imageryId)}>{activated[scene.key] ? <CheckCircle2 className="size-3" /> : <Satellite className="size-3" />}{activated[scene.key] ? "已设为分析影像" : "设为分析影像"}</Button><Button size="sm" className="h-7 text-[10px]" onClick={onOpenWorkspace}>前往工作台</Button></div></div>}
                </div>
              </article>;
            })}
          </div></ScrollArea>
        </aside>
      </div>
    </section>
  );
}

import { useCallback, useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import type { Map as MapLibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Layers, Crosshair, Eye, EyeOff, Plus, Minus, Search, Loader2, SquareDashedMousePointer, Grid3x3, Columns2, Pentagon, MapPin, Ruler, Trash2, ChevronDown } from "lucide-react";
import type { RSLayer } from "../lib/layers";
import type { MapAnnotation } from "../types";
import { ImageViewer } from "./ImageViewer";
import { geoRoiFromCorners, isDegenerateRoi, type PixelRoi, type Roi } from "../lib/roi";
import { buildGraticule } from "../lib/graticule";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";

// 默认视图（无影像时的世界中心，随首个带 bounds 的结果 fitBounds 覆盖）。
const DEFAULT_CENTER: [number, number] = [115.9, 22.9];
const DEFAULT_ZOOM = 9;

// MapLibre paint 属性必须是字面量颜色，不能解析 CSS 变量（hsl(var(--primary)) 会被校验器拒绝）。
// 取主题色 --primary(#2bb8c2) 与深色底 #0a0e14 的字面量，供绘图/标注图层使用。
const PRIMARY_COLOR = "#2bb8c2";
const DARK_BG = "#0a0e14";

const SAT_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
  sources: {
    esri: {
      type: "raster",
      tiles: [
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      ],
      tileSize: 256,
      attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
    },
    esriRef: {
      type: "raster",
      tiles: [
        "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
      ],
      tileSize: 256,
    },
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "#0a0e14" } },
    { id: "esri", type: "raster", source: "esri" },
    { id: "esriRef", type: "raster", source: "esriRef", layout: { visibility: "none" } },
  ],
};

function absoluteUrl(url: string) {
  if (!url) return url;
  return url.startsWith("http") ? url : `${window.location.origin}${url}`;
}

export function MapView({
  mapRef: externalMapRef,
  layers,
  roi,
  onSelectRegion,
  onClearRegion,
  onAnnotationsChange,
}: {
  mapRef?: React.MutableRefObject<MapLibreMap | null>;
  layers: RSLayer[];
  roi: Roi | null;
  onSelectRegion: (roi: Roi) => void;
  onClearRegion: () => void;
  onAnnotationsChange?: (annotations: MapAnnotation[]) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const ref2 = useRef<HTMLDivElement>(null); // 卷帘第二张地图容器
  const mapRef = useRef<maplibregl.Map | null>(null);
  const mapRef2 = useRef<maplibregl.Map | null>(null);
  const fittedRef = useRef<string | null>(null); // 记录已 fit 过的 imageryId，避免每次重渲都跳视图
  const [ready, setReady] = useState(false);
  const [coords, setCoords] = useState<[number, number]>(DEFAULT_CENTER);
  const [zoom, setZoom] = useState(DEFAULT_ZOOM);
  const [labels, setLabels] = useState(false);
  const searchMarkerRef = useRef<maplibregl.Marker | null>(null);
  const [searchText, setSearchText] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  // geo 框选：拖拽态用屏幕像素矩形显示，松手 unproject 成经纬度 bbox。
  const [selectMode, setSelectMode] = useState(false);
  const drawRef = useRef<{ x0: number; y0: number } | null>(null);
  const [drawRect, setDrawRect] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  // 经纬网开关 + 卷帘对比开关。
  const [graticule, setGraticule] = useState(false);
  const [swipe, setSwipe] = useState(false);
  const [swipePct, setSwipePct] = useState(50); // 分隔条位置（容器宽度百分比）
  const swipeDragRef = useRef(false);
  const scaleCtrlRef = useRef<maplibregl.ScaleControl | null>(null);
  // 原生绘图：当前模式 + 已提交标注 + 进行中要素顶点。
  const [drawMode, setDrawMode] = useState<"polygon" | "point" | "line_string" | null>(null);
  const [annotations, setAnnotations] = useState<MapAnnotation[]>([]); // 已完成标注（GeoJSON Feature）
  const draftRef = useRef<[number, number][]>([]); // 进行中要素的顶点（lng,lat）
  const annotationsRef = useRef<MapAnnotation[]>([]); // 镜像 annotations 供事件回调读最新值（防 stale-closure）
  const hasRoi = roi !== null;
  const hasAnnotations = annotations.length > 0;

  // 从 localStorage 加载标注（挂载时一次）。
  useEffect(() => {
    const saved = localStorage.getItem("map_annotations");
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) setAnnotations(parsed as MapAnnotation[]);
      } catch (e) {
        console.error("Failed to load annotations:", e);
      }
    }
  }, []);

  // 镜像 annotations 到 ref：事件回调（按 drawMode 重注册）据此读到最新已提交标注，杜绝 stale-closure。
  useEffect(() => {
    annotationsRef.current = annotations;
  }, [annotations]);

  // 保存标注到 localStorage + 通知父组件（透传给智能体上下文）。
  const saveAnnotations = (newAnnotations: MapAnnotation[]) => {
    setAnnotations(newAnnotations);
    localStorage.setItem("map_annotations", JSON.stringify(newAnnotations));
    if (onAnnotationsChange) {
      onAnnotationsChange(newAnnotations);
    }
  };

  const clearAnnotationsOnly = () => {
    draftRef.current = [];
    renderDraft();
    setDrawMode(null);
    saveAnnotations([]);
  };

  const clearAll = () => {
    clearAnnotationsOnly();
    onClearRegion();
  };

  // 可见的叠加结果图层（非 imagery），用于判断卷帘是否可用：需要至少 1 个结果图层叠在底图/影像上。
  const overlayCount = layers.filter((l) => l.visible && l.kind !== "imagery").length;

  // 地名搜索：Nominatim 公开地理编码（无需 key），取首个结果 flyTo 并落一个临时标记。
  const runSearch = async () => {
    const q = searchText.trim();
    const map = mapRef.current;
    if (!q || searching || !map) return;
    setSearching(true);
    setSearchError(null);
    try {
      const url =
        "https://nominatim.openstreetmap.org/search?format=json&limit=1&q=" +
        encodeURIComponent(q);
      const resp = await fetch(url, { headers: { "Accept-Language": "zh-CN,zh" } });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data: Array<{ lon: string; lat: string }> = await resp.json();
      if (!data.length) {
        setSearchError("未找到该位置");
        return;
      }
      const lng = Number(data[0].lon);
      const lat = Number(data[0].lat);
      if (!Number.isFinite(lng) || !Number.isFinite(lat)) {
        setSearchError("位置坐标无效");
        return;
      }
      searchMarkerRef.current?.remove();
      searchMarkerRef.current = new maplibregl.Marker({ color: "#2dd4bf" })
        .setLngLat([lng, lat])
        .addTo(map);
      map.flyTo({ center: [lng, lat], zoom: 12, duration: 900 });
    } catch {
      setSearchError("搜索失败，请重试");
    } finally {
      setSearching(false);
    }
  };

  // 带地理坐标的图层走 image source 叠加；无坐标的走缩略图兜底。
  const geoLayers = layers.filter(
    (l): l is RSLayer & { bounds: [number, number, number, number] } =>
      l.visible && Array.isArray(l.bounds) && l.bounds.length === 4 && !!l.url,
  );
  const thumbnailLayers = layers.filter(
    (l) => l.visible && (!Array.isArray(l.bounds) || l.bounds.length !== 4) && !!l.url,
  );

  // init map
  useEffect(() => {
    if (!ref.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: ref.current,
      style: SAT_STYLE,
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
      attributionControl: false,
    });
    map.on("mousemove", (e) => setCoords([e.lngLat.lng, e.lngLat.lat]));
    map.on("zoom", () => setZoom(map.getZoom()));
    // 比例尺（左下，公制）；深色样式由全局 CSS 覆盖。
    const scaleCtrl = new maplibregl.ScaleControl({ maxWidth: 120, unit: "metric" });
    map.addControl(scaleCtrl, "bottom-left");
    scaleCtrlRef.current = scaleCtrl;
    map.on("load", () => {
      setReady(true);
      map.resize();
    });
    mapRef.current = map;
    // 同步到外部 ref（供 App 提取地图上下文）
    if (externalMapRef) {
      externalMapRef.current = map;
    }
    return () => {
      map.remove();
      mapRef.current = null;
      if (externalMapRef) {
        externalMapRef.current = null;
      }
    };
  }, [externalMapRef]);

  // keep canvas sized to container (fixes blank map on refresh)
  useEffect(() => {
    const el = ref.current;
    const map = mapRef.current;
    if (!el || !map) return;
    const ro = new ResizeObserver(() => map.resize());
    ro.observe(el);
    const r1 = requestAnimationFrame(() => map.resize());
    const t1 = setTimeout(() => map.resize(), 250);
    return () => {
      ro.disconnect();
      cancelAnimationFrame(r1);
      clearTimeout(t1);
    };
  }, []);

  // toggle reference labels
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    map.setLayoutProperty("esriRef", "visibility", labels ? "visible" : "none");
  }, [labels, ready]);

  // 框选态下禁用地图拖拽平移，避免与画框冲突。
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    if (selectMode) map.dragPan.disable();
    else map.dragPan.enable();
  }, [selectMode, ready]);

  // 经纬网：开关时增删图层，并在 moveend 时按当前视图重算「整齐」间隔。
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const srcId = "rs-grat-src";
    const lineId = "rs-grat-line";
    const labelId = "rs-grat-label";

    const removeGraticule = () => {
      if (map.getLayer(labelId)) map.removeLayer(labelId);
      if (map.getLayer(lineId)) map.removeLayer(lineId);
      if (map.getSource(srcId)) map.removeSource(srcId);
    };

    const rebuild = () => {
      const b = map.getBounds();
      const data = buildGraticule({
        west: b.getWest(),
        south: b.getSouth(),
        east: b.getEast(),
        north: b.getNorth(),
      });
      const src = map.getSource(srcId) as maplibregl.GeoJSONSource | undefined;
      if (src) {
        src.setData(data);
      } else {
        map.addSource(srcId, { type: "geojson", data });
        map.addLayer({
          id: lineId,
          type: "line",
          source: srcId,
          filter: ["==", ["get", "kind"], "line"],
          paint: { "line-color": "#94a3b8", "line-opacity": 0.35, "line-width": 0.5 },
        });
        map.addLayer({
          id: labelId,
          type: "symbol",
          source: srcId,
          filter: ["==", ["get", "kind"], "label"],
          layout: {
            "text-field": ["get", "label"],
            "text-size": 10,
            "text-offset": [0.6, 0.6],
            "text-anchor": "top-left",
            "text-allow-overlap": false,
          },
          paint: { "text-color": "#cbd5e1", "text-halo-color": "#0a0e14", "text-halo-width": 1 },
        });
      }
    };

    if (!graticule) {
      removeGraticule();
      return;
    }
    rebuild();
    map.on("moveend", rebuild);
    return () => {
      map.off("moveend", rebuild);
    };
  }, [graticule, ready]);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const srcId = "rs-roi-src";
    const fillId = "rs-roi-fill";
    const lineId = "rs-roi-line";
    const geoRoi = roi && roi.kind === "geo" ? roi : null;

    if (!geoRoi) {
      if (map.getLayer(lineId)) map.removeLayer(lineId);
      if (map.getLayer(fillId)) map.removeLayer(fillId);
      if (map.getSource(srcId)) map.removeSource(srcId);
      return;
    }
    const [west, south, east, north] = geoRoi.bbox;
    const polygon: GeoJSON.Feature = {
      type: "Feature",
      properties: {},
      geometry: {
        type: "Polygon",
        coordinates: [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
      },
    };
    const src = map.getSource(srcId) as maplibregl.GeoJSONSource | undefined;
    if (src) {
      src.setData(polygon);
    } else {
      map.addSource(srcId, { type: "geojson", data: polygon });
      map.addLayer({ id: fillId, type: "fill", source: srcId, paint: { "fill-color": "#2dd4bf", "fill-opacity": 0.15 } });
      map.addLayer({ id: lineId, type: "line", source: srcId, paint: { "line-color": "#2dd4bf", "line-width": 2 } });
    }
  }, [roi, ready]);

  // D1 已提交标注渲染：单一 FeatureCollection 源 + Polygon(fill+line)/LineString(line)/Point(circle) 三层。
  // 首次建源建层，之后 setData；并在 load/标注变更时恢复已存标注（取代旧 MapboxDraw 的 draw.set）。
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const srcId = "rs-anno-src";
    const data: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: annotations as GeoJSON.Feature[],
    };
    const src = map.getSource(srcId) as maplibregl.GeoJSONSource | undefined;
    if (src) {
      src.setData(data);
      return;
    }
    map.addSource(srcId, { type: "geojson", data });
    map.addLayer({
      id: "rs-anno-fill",
      type: "fill",
      source: srcId,
      filter: ["==", ["geometry-type"], "Polygon"],
      paint: { "fill-color": PRIMARY_COLOR, "fill-opacity": 0.15 },
    });
    map.addLayer({
      id: "rs-anno-line",
      type: "line",
      source: srcId,
      filter: ["in", ["geometry-type"], ["literal", ["Polygon", "LineString"]]],
      paint: { "line-color": PRIMARY_COLOR, "line-width": 2 },
    });
    map.addLayer({
      id: "rs-anno-point",
      type: "circle",
      source: srcId,
      filter: ["==", ["geometry-type"], "Point"],
      paint: {
        "circle-radius": 6,
        "circle-color": PRIMARY_COLOR,
        "circle-stroke-color": DARK_BG,
        "circle-stroke-width": 1.5,
      },
    });
  }, [annotations, ready]);

  // D2 草稿预览：进行中要素的顶点(circle)+连线(line)。建一次源/层，由 renderDraft 写入。
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const srcId = "rs-draft-src";
    if (map.getSource(srcId)) return;
    map.addSource(srcId, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    map.addLayer({
      id: "rs-draft-line",
      type: "line",
      source: srcId,
      filter: ["==", ["geometry-type"], "LineString"],
      paint: { "line-color": PRIMARY_COLOR, "line-width": 2, "line-dasharray": [2, 1] },
    });
    map.addLayer({
      id: "rs-draft-point",
      type: "circle",
      source: srcId,
      filter: ["==", ["geometry-type"], "Point"],
      paint: {
        "circle-radius": 4,
        "circle-color": DARK_BG,
        "circle-stroke-color": PRIMARY_COLOR,
        "circle-stroke-width": 2,
      },
    });
  }, [ready]);

  // 把 draftRef 顶点写进草稿源：每个顶点一个 Point，≥2 点再加一条连线（polygon 也用折线预览即可）。
  const renderDraft = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;
    const src = map.getSource("rs-draft-src") as maplibregl.GeoJSONSource | undefined;
    if (!src) return;
    const pts = draftRef.current;
    const features: GeoJSON.Feature[] = pts.map((p) => ({
      type: "Feature",
      properties: {},
      geometry: { type: "Point", coordinates: p },
    }));
    if (pts.length >= 2) {
      features.push({
        type: "Feature",
        properties: {},
        geometry: { type: "LineString", coordinates: pts },
      });
    }
    src.setData({ type: "FeatureCollection", features });
  }, []);

  // 切换绘图模式：再点同一模式→退出；与框选互斥；切换时丢弃未完成草稿。
  const toggleDrawMode = useCallback(
    (mode: "polygon" | "point" | "line_string") => {
      draftRef.current = [];
      renderDraft();
      setSelectMode(false);
      setDrawMode((prev) => (prev === mode ? null : mode));
    },
    [renderDraft],
  );

  // D3 绘图交互：按 drawMode 重注册 click/dblclick → 回调天然读到最新 drawMode，经 ref 读写已提交标注（无 stale-closure）。
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !drawMode) return;

    // 绘图时禁用双击缩放，避免双击「结束」误触发地图缩放。
    map.doubleClickZoom.disable();
    const canvas = map.getCanvas();
    const prevCursor = canvas.style.cursor;
    canvas.style.cursor = "default";

    const commit = (feature: MapAnnotation) => {
      saveAnnotations([...annotationsRef.current, feature]);
      draftRef.current = [];
      renderDraft();
    };

    const onClick = (e: maplibregl.MapMouseEvent) => {
      const pt: [number, number] = [e.lngLat.lng, e.lngLat.lat];
      if (drawMode === "point") {
        commit({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: pt } });
        setDrawMode(null);
        return;
      }
      draftRef.current = [...draftRef.current, pt];
      renderDraft();
    };

    const onDblClick = (e: maplibregl.MapMouseEvent) => {
      // dblclick 前会先触发一次 click（已 append 一个重复点），这里去掉它。
      const pts = draftRef.current.slice(0, -1);
      if (drawMode === "line_string") {
        if (pts.length >= 2) {
          commit({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: pts } });
        } else {
          draftRef.current = [];
          renderDraft();
        }
      } else if (drawMode === "polygon") {
        if (pts.length >= 3) {
          const ring = [...pts, pts[0]]; // 闭合环
          commit({ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [ring] } });
        } else {
          draftRef.current = [];
          renderDraft();
        }
      }
      setDrawMode(null);
    };

    map.on("click", onClick);
    map.on("dblclick", onDblClick);
    return () => {
      map.off("click", onClick);
      map.off("dblclick", onDblClick);
      map.doubleClickZoom.enable();
      canvas.style.cursor = prevCursor;
      // 退出绘图模式时清掉未完成草稿。
      draftRef.current = [];
      renderDraft();
    };
  }, [drawMode, ready, renderDraft]);

  // sync real raster overlays (image source per geo layer)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;

    const wantLayerIds = new Set(geoLayers.map((l) => `rs-img-${l.id}`));
    const wantSourceIds = new Set(geoLayers.map((l) => `rs-src-${l.id}`));

    // 清理不再需要的旧图层/源（id 前缀 rs-）。
    const style = map.getStyle();
    (style.layers ?? []).forEach((l) => {
      if (l.id.startsWith("rs-img-") && !wantLayerIds.has(l.id) && map.getLayer(l.id)) {
        map.removeLayer(l.id);
      }
    });
    Object.keys(style.sources ?? {}).forEach((id) => {
      if (id.startsWith("rs-src-") && !wantSourceIds.has(id) && map.getSource(id)) {
        map.removeSource(id);
      }
    });

    // 按 layers 顺序添加（imagery 在前作为底图）。
    for (const layer of geoLayers) {
      const srcId = `rs-src-${layer.id}`;
      const layerId = `rs-img-${layer.id}`;
      const [west, south, east, north] = layer.bounds;
      try {
        if (!map.getSource(srcId)) {
          map.addSource(srcId, {
            type: "image",
            url: absoluteUrl(layer.url!),
            coordinates: [
              [west, north],
              [east, north],
              [east, south],
              [west, south],
            ],
          });
        }
        if (!map.getLayer(layerId)) {
          map.addLayer({
            id: layerId,
            type: "raster",
            source: srcId,
            paint: { "raster-opacity": layer.opacity, "raster-fade-duration": 200 },
          });
        } else {
          map.setPaintProperty(layerId, "raster-opacity", layer.opacity);
        }
      } catch (err) {
        console.error(`[MapView] failed to add layer ${layerId}`, err);
      }
    }

    // 首次出现某影像时 fitBounds 一次（之后不再打断用户视图）。
    const focus = geoLayers[geoLayers.length - 1];
    if (focus && fittedRef.current !== focus.imageryId) {
      const [west, south, east, north] = focus.bounds;
      map.fitBounds([west, south, east, north], { padding: 48, duration: 700 });
      fittedRef.current = focus.imageryId;
    }
    if (geoLayers.length === 0) fittedRef.current = null;
  }, [geoLayers, ready]);

  // 卷帘对比：懒实例化第二张地图（仅 swipe 开启时创建、关闭即销毁）。
  // 第二张图渲染「底图 + 除最上结果图层外的所有 geo 图层」，主图渲染全部图层；
  // 第二张图覆盖在左侧、用 clip-path 裁到分隔条处 → 左边「少最上结果」、右边「完整」的对比。
  // 双向同步相机，避免单画布无法逐图层裁剪的限制（maplibre 社区标准做法）。
  useEffect(() => {
    const primary = mapRef.current;
    if (!primary || !ready || !ref2.current) return;
    if (!swipe) return;

    const compareLayers = geoLayers.slice(0, -1); // 去掉最上面那个结果图层
    const second = new maplibregl.Map({
      container: ref2.current,
      style: SAT_STYLE,
      center: primary.getCenter(),
      zoom: primary.getZoom(),
      bearing: primary.getBearing(),
      pitch: primary.getPitch(),
      attributionControl: false,
      interactive: false, // 由主图驱动，避免双向拖拽打架
    });

    second.on("load", () => {
      second.setLayoutProperty("esriRef", "visibility", labels ? "visible" : "none");
      for (const layer of compareLayers) {
        const [west, south, east, north] = layer.bounds;
        const srcId = `rs2-src-${layer.id}`;
        const layerId = `rs2-img-${layer.id}`;
        try {
          second.addSource(srcId, {
            type: "image",
            url: absoluteUrl(layer.url!),
            coordinates: [[west, north], [east, north], [east, south], [west, south]],
          });
          second.addLayer({
            id: layerId,
            type: "raster",
            source: srcId,
            paint: { "raster-opacity": layer.opacity },
          });
        } catch (err) {
          console.error(`[MapView/swipe] failed to add ${layerId}`, err);
        }
      }
    });

    // 主图移动 → 同步第二图相机。
    const sync = () => {
      second.jumpTo({
        center: primary.getCenter(),
        zoom: primary.getZoom(),
        bearing: primary.getBearing(),
        pitch: primary.getPitch(),
      });
    };
    primary.on("move", sync);
    mapRef2.current = second;

    return () => {
      primary.off("move", sync);
      second.remove();
      mapRef2.current = null;
    };
  }, [swipe, ready, geoLayers, labels]);

  return (
    <div className="absolute inset-0 overflow-hidden bg-background">
      <div ref={ref} className="size-full" />

      {/* 卷帘对比：第二张地图覆盖在左侧，clip-path 裁到分隔条处；分隔条可拖拽 */}
      <div
        ref={ref2}
        className="absolute inset-0 z-[12]"
        style={{
          clipPath: `inset(0 ${100 - swipePct}% 0 0)`,
          display: swipe ? "block" : "none",
        }}
      />
      {swipe && (
        <>
          <div
            className="absolute inset-y-0 z-[13] w-0.5 bg-primary"
            style={{ left: `${swipePct}%` }}
          />
          <div
            className="absolute inset-y-0 z-[14] -ml-3 w-6 cursor-ew-resize"
            style={{ left: `${swipePct}%` }}
            onPointerDown={(e) => {
              (e.target as Element).setPointerCapture?.(e.pointerId);
              swipeDragRef.current = true;
            }}
            onPointerMove={(e) => {
              if (!swipeDragRef.current) return;
              const rect = e.currentTarget.parentElement?.getBoundingClientRect();
              if (!rect) return;
              const pct = ((e.clientX - rect.left) / rect.width) * 100;
              setSwipePct(Math.min(95, Math.max(5, pct)));
            }}
            onPointerUp={() => {
              swipeDragRef.current = false;
            }}
          >
            <div className="absolute top-1/2 left-1/2 grid size-7 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-primary bg-card/90 text-primary backdrop-blur-md">
              <Columns2 className="size-3.5" />
            </div>
          </div>
        </>
      )}

      {/* geo 框选拖拽覆盖层：仅框选态挂载，捕获鼠标画框；松手 unproject 成经纬度 bbox。
          底图也可框选（unproject 与图层无关），不再要求已加载影像。 */}
      {selectMode && (
        <div
          className="absolute inset-0 z-[15] cursor-crosshair"
          onPointerDown={(e) => {
            (e.target as Element).setPointerCapture?.(e.pointerId);
            const rect = e.currentTarget.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            drawRef.current = { x0: x, y0: y };
            setDrawRect({ x0: x, y0: y, x1: x, y1: y });
          }}
          onPointerMove={(e) => {
            if (!drawRef.current) return;
            const rect = e.currentTarget.getBoundingClientRect();
            setDrawRect({
              x0: drawRef.current.x0,
              y0: drawRef.current.y0,
              x1: e.clientX - rect.left,
              y1: e.clientY - rect.top,
            });
          }}
          onPointerUp={() => {
            const map = mapRef.current;
            if (map && drawRef.current && drawRect) {
              const a = map.unproject([drawRect.x0, drawRect.y0]);
              const b = map.unproject([drawRect.x1, drawRect.y1]);
              const next = geoRoiFromCorners([a.lng, a.lat], [b.lng, b.lat]);
              if (!isDegenerateRoi(next)) {
                onSelectRegion(next);
                setSelectMode(false);
              }
            }
            drawRef.current = null;
            setDrawRect(null);
          }}
        >
          {drawRect && (
            <div
              className="pointer-events-none absolute rounded-sm border-2 border-dashed border-primary bg-primary/10"
              style={{
                left: Math.min(drawRect.x0, drawRect.x1),
                top: Math.min(drawRect.y0, drawRect.y1),
                width: Math.abs(drawRect.x1 - drawRect.x0),
                height: Math.abs(drawRect.y1 - drawRect.y0),
              }}
            />
          )}
        </div>
      )}

      {/* 地名搜索框（左上角，避开右侧图层面板） */}
      <div className="absolute left-4 top-[116px] z-10 w-[240px]">
        <div className="flex items-center gap-1.5 rounded-full border border-border bg-card/80 px-3 py-1.5 backdrop-blur-md focus-within:border-primary/50">
          {searching ? (
            <Loader2 className="size-3.5 shrink-0 animate-spin text-primary" />
          ) : (
            <Search className="size-3.5 shrink-0 text-muted-foreground" />
          )}
          <input
            value={searchText}
            onChange={(e) => {
              setSearchText(e.target.value);
              if (searchError) setSearchError(null);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void runSearch();
              }
            }}
            placeholder="搜索地点，回车定位"
            className="w-full bg-transparent text-[12px] text-foreground placeholder:text-muted-foreground focus:outline-none"
          />
        </div>
        {searchError && (
          <div className="mt-1 rounded-md bg-card/80 px-2.5 py-1 text-[11px] text-destructive backdrop-blur-md">
            {searchError}
          </div>
        )}
      </div>

      {/* 无地理坐标结果：可交互查看器（滚轮缩放/拖拽平移/框选），替代旧的静态图兜底 */}
      {thumbnailLayers.length > 0 && (
        <ImageViewer
          layers={thumbnailLayers}
          roi={roi && roi.kind === "pixel" ? (roi as PixelRoi) : null}
          onSelectRegion={(pixelRoi) => onSelectRegion(pixelRoi)}
          onClearRegion={onClearRegion}
        />
      )}

      {/* subtle vignette */}
      <div className="pointer-events-none absolute inset-0 shadow-[inset_0_0_140px_rgba(0,0,0,0.5)]" />

      {/* top-center readout */}
      <div className="pointer-events-none absolute left-1/2 top-[116px] -translate-x-1/2">
        <div className="flex items-center gap-2 rounded-full border border-border bg-card/80 px-3.5 py-1.5 font-mono text-[11px] tracking-tight text-foreground backdrop-blur-md">
          <span className="size-1.5 rounded-full bg-primary" />
          <span className="text-muted-foreground">LAT</span>
          <span className="tabular-nums">{coords[1].toFixed(4)}°</span>
          <span className="text-muted-foreground">LNG</span>
          <span className="tabular-nums">{coords[0].toFixed(4)}°</span>
          <span className="text-foreground/30">·</span>
          <span className="text-muted-foreground">Z</span>
          <span className="tabular-nums">{zoom.toFixed(1)}</span>
        </div>
      </div>

      {/* bottom-center control cluster */}
      <div className="absolute bottom-4 left-1/2 flex -translate-x-1/2 items-center gap-2">
        <div className="flex items-center overflow-hidden rounded-full border border-border bg-card/80 backdrop-blur-md">
          <button
            onClick={() => mapRef.current?.zoomOut({ duration: 250 })}
            className="grid size-8 place-items-center text-foreground transition-colors hover:text-primary"
            title="缩小"
          >
            <Minus className="size-3.5" />
          </button>
          <span className="h-4 w-px bg-border" />
          <button
            onClick={() => mapRef.current?.zoomIn({ duration: 250 })}
            className="grid size-8 place-items-center text-foreground transition-colors hover:text-primary"
            title="放大"
          >
            <Plus className="size-3.5" />
          </button>
        </div>

        <button
          onClick={() => setLabels((v) => !v)}
          className={`flex items-center gap-1.5 rounded-full border px-3 py-1.5 font-mono text-[11px] backdrop-blur-md transition-colors ${
            labels
              ? "border-primary/50 bg-primary/10 text-primary"
              : "border-border bg-card/80 text-foreground hover:text-primary"
          }`}
        >
          {labels ? <Eye className="size-3.5" /> : <EyeOff className="size-3.5" />}
          标注
        </button>
        {/* 经纬网开关 */}
        <button
          onClick={() => setGraticule((v) => !v)}
          className={`flex items-center gap-1.5 rounded-full border px-3 py-1.5 font-mono text-[11px] backdrop-blur-md transition-colors ${
            graticule
              ? "border-primary/50 bg-primary/10 text-primary"
              : "border-border bg-card/80 text-foreground hover:text-primary"
          }`}
          title="经纬网"
        >
          <Grid3x3 className="size-3.5" />
          网格
        </button>
        {/* 卷帘对比：需至少一个结果图层叠在底图/影像上 */}
        {overlayCount >= 1 && geoLayers.length >= 2 && (
          <button
            onClick={() => setSwipe((v) => !v)}
            className={`flex items-center gap-1.5 rounded-full border px-3 py-1.5 font-mono text-[11px] backdrop-blur-md transition-colors ${
              swipe
                ? "border-primary/50 bg-primary/10 text-primary"
                : "border-border bg-card/80 text-foreground hover:text-primary"
            }`}
            title="卷帘对比（左：去掉最上结果图层 / 右：完整）"
          >
            <Columns2 className="size-3.5" />
            卷帘
          </button>
        )}
        <button
          onClick={() => {
            const map = mapRef.current;
            const focus = geoLayers[geoLayers.length - 1];
            if (map && focus) {
              const [west, south, east, north] = focus.bounds;
              map.fitBounds([west, south, east, north], { padding: 48, duration: 700 });
            } else {
              map?.flyTo({ center: DEFAULT_CENTER, zoom: DEFAULT_ZOOM, duration: 800 });
            }
          }}
          className="flex items-center gap-1.5 rounded-full border border-border bg-card/80 px-3 py-1.5 font-mono text-[11px] text-foreground backdrop-blur-md transition-colors hover:border-primary/50 hover:text-primary"
        >
          <Crosshair className="size-3.5" />
          复位
        </button>

        {/* geo 框选：选「分析聚焦区」。底图与影像均可用（不再门控）。与绘图模式互斥。 */}
        <button
          onClick={() => {
            setSelectMode((v) => !v);
            setDrawMode(null); // 与绘图互斥
            draftRef.current = [];
            renderDraft();
          }}
          className={`flex items-center gap-1.5 rounded-full border px-3 py-1.5 font-mono text-[11px] backdrop-blur-md transition-colors ${
            selectMode
              ? "border-primary/50 bg-primary/10 text-primary"
              : "border-border bg-card/80 text-foreground hover:text-primary"
          }`}
          title="框选分析聚焦区（仅引导解读聚焦，工具仍按整幅影像计算）"
        >
          <SquareDashedMousePointer className="size-3.5" />
          {selectMode ? "框选中" : "框选"}
        </button>
        {/* 绘图工具按钮组（原生 MapLibre 事件 + GeoJSON 图层实现） */}
        {ready && (
          <>
            <button
              onClick={() => toggleDrawMode("polygon")}
              className={`flex items-center gap-1.5 rounded-full border px-3 py-1.5 font-mono text-[11px] backdrop-blur-md transition-colors ${
                drawMode === "polygon"
                  ? "border-primary/50 bg-primary/10 text-primary"
                  : "border-border bg-card/80 text-foreground hover:text-primary"
              }`}
              title="绘制多边形标注（连续单击落点，双击闭合）"
            >
              <Pentagon className="size-3.5" />
              {drawMode === "polygon" ? "双击结束" : "多边形"}
            </button>

            <button
              onClick={() => toggleDrawMode("point")}
              className={`flex items-center gap-1.5 rounded-full border px-3 py-1.5 font-mono text-[11px] backdrop-blur-md transition-colors ${
                drawMode === "point"
                  ? "border-primary/50 bg-primary/10 text-primary"
                  : "border-border bg-card/80 text-foreground hover:text-primary"
              }`}
              title="标记点位（单击落点）"
            >
              <MapPin className="size-3.5" />
              {drawMode === "point" ? "单击落点" : "点标注"}
            </button>

            <button
              onClick={() => toggleDrawMode("line_string")}
              className={`flex items-center gap-1.5 rounded-full border px-3 py-1.5 font-mono text-[11px] backdrop-blur-md transition-colors ${
                drawMode === "line_string"
                  ? "border-primary/50 bg-primary/10 text-primary"
                  : "border-border bg-card/80 text-foreground hover:text-primary"
              }`}
              title="绘制线段（连续单击落点，双击结束）"
            >
              <Ruler className="size-3.5" />
              {drawMode === "line_string" ? "双击结束" : "线段"}
            </button>

          </>
        )}

        {(hasRoi || hasAnnotations) && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                className="flex items-center gap-1.5 rounded-full border border-border bg-card/80 px-3 py-1.5 font-mono text-[11px] text-foreground backdrop-blur-md transition-colors hover:border-destructive/50 hover:text-destructive"
                title="清除"
              >
                <Trash2 className="size-3.5" />
                清除
                <ChevronDown className="size-3" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="center" side="top">
              <DropdownMenuItem disabled={!hasRoi} onClick={onClearRegion}>
                清除选区（框选）
              </DropdownMenuItem>
              <DropdownMenuItem disabled={!hasAnnotations} onClick={clearAnnotationsOnly}>
                清除标注（点/线/面）
              </DropdownMenuItem>
              <DropdownMenuItem disabled={!hasRoi && !hasAnnotations} onClick={clearAll}>
                全部清除
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}

        <div className="hidden items-center gap-2 rounded-full border border-border bg-card/80 px-3 py-1.5 font-mono text-[10px] uppercase tracking-widest text-muted-foreground backdrop-blur-md lg:flex">
          <Layers className="size-3 text-primary" />
          Esri © Imagery · WGS84
        </div>
      </div>
    </div>
  );
}

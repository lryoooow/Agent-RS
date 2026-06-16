import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Layers, Crosshair, Eye, EyeOff, Plus, Minus } from "lucide-react";
import type { RSLayer } from "../lib/layers";

// 默认视图（无影像时的世界中心，随首个带 bounds 的结果 fitBounds 覆盖）。
const DEFAULT_CENTER: [number, number] = [115.9, 22.9];
const DEFAULT_ZOOM = 9;

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

export function MapView({ layers }: { layers: RSLayer[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const fittedRef = useRef<string | null>(null); // 记录已 fit 过的 imageryId，避免每次重渲都跳视图
  const [ready, setReady] = useState(false);
  const [coords, setCoords] = useState<[number, number]>(DEFAULT_CENTER);
  const [zoom, setZoom] = useState(DEFAULT_ZOOM);
  const [labels, setLabels] = useState(false);

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
    map.on("load", () => {
      setReady(true);
      map.resize();
    });
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

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

  return (
    <div className="absolute inset-0 overflow-hidden bg-background">
      <div ref={ref} className="size-full" />

      {/* 无地理坐标结果：缩略图兜底（所有无坐标图层按原图比例叠放，影像在底/结果在上，object-contain 完整不裁剪） */}
      {thumbnailLayers.length > 0 && (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center p-6">
          <div className="relative flex items-center justify-center">
            {[...thumbnailLayers].reverse().map((l, i) => (
              <img
                key={l.id}
                src={absoluteUrl(l.url!)}
                alt={l.name}
                className={
                  i === 0
                    ? "max-h-[86vh] max-w-full rounded-lg object-contain shadow-2xl"
                    : "absolute inset-0 size-full rounded-lg object-contain"
                }
                style={{ opacity: l.opacity }}
              />
            ))}
            <p className="absolute -bottom-6 left-1/2 -translate-x-1/2 whitespace-nowrap rounded bg-card/85 px-2 py-0.5 font-mono text-[10px] text-muted-foreground backdrop-blur-md">
              无地理坐标 · 按原图比例完整展示
            </p>
          </div>
        </div>
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

        <div className="hidden items-center gap-2 rounded-full border border-border bg-card/80 px-3 py-1.5 font-mono text-[10px] uppercase tracking-widest text-muted-foreground backdrop-blur-md lg:flex">
          <Layers className="size-3 text-primary" />
          Esri © Imagery · WGS84
        </div>
      </div>
    </div>
  );
}

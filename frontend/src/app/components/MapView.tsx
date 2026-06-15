import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Crosshair, Eye, EyeOff, Plus, Minus, Layers } from "lucide-react";
import type { GeospatialResult } from "../types";
import { AOI } from "../data/rs";

// ---- layer entry model ----------------------------------------------------
// Each geospatial result becomes one map source/layer. Real result_url PNGs are
// georeferenced via `bounds` (EPSG:4326). Results without bounds are not projected;
// the App-level thumbnail handling shows them instead.
export type LayerUiState = Record<string, { visible: boolean; opacity: number }>;

type LayerEntry = {
  key: string;
  sourceId: string;
  layerId: string;
  result: GeospatialResult;
  hasGeo: boolean;
};

export function layerKeyOf(result: GeospatialResult, idx: number) {
  return `${result.type}-${result.imagery_id}-${idx}`;
}

function resolveUrl(resultUrl: string) {
  return resultUrl.startsWith("http") ? resultUrl : `${window.location.origin}${resultUrl}`;
}

// Esri World Imagery basemap — the new UI's satellite shell, preserved as-is.
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

interface MapViewProps {
  geospatialResults: GeospatialResult[];
  layerUi: LayerUiState;
}

export function MapView({ geospatialResults, layerUi }: MapViewProps) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const layerIdsRef = useRef<Set<string>>(new Set());
  const sourceIdsRef = useRef<Set<string>>(new Set());
  const [ready, setReady] = useState(false);
  const [coords, setCoords] = useState<[number, number]>(AOI.center);
  const [zoom, setZoom] = useState(AOI.zoom);
  const [labels, setLabels] = useState(false);

  const layerEntries: LayerEntry[] = useMemo(
    () =>
      geospatialResults.map((result, idx) => {
        const key = layerKeyOf(result, idx);
        return {
          key,
          sourceId: `rs-src-${key}`,
          layerId: `rs-layer-${key}`,
          result,
          hasGeo: Array.isArray(result.bounds) && result.bounds.length === 4,
        };
      }),
    [geospatialResults],
  );

  // init map (shell)
  useEffect(() => {
    if (!ref.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: ref.current,
      style: SAT_STYLE,
      center: AOI.center,
      zoom: AOI.zoom,
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
      layerIdsRef.current.clear();
      sourceIdsRef.current.clear();
      setReady(false);
    };
  }, []);

  // keep the map sized to its container (fixes blank/partial map on refresh)
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

  // sync real result layers (image source + bounds georeferencing)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;

    const currentLayerIds = new Set(layerEntries.map((e) => e.layerId));
    const currentSourceIds = new Set(layerEntries.map((e) => e.sourceId));
    layerIdsRef.current.forEach((id) => {
      if (!currentLayerIds.has(id) && map.getLayer(id)) map.removeLayer(id);
    });
    sourceIdsRef.current.forEach((id) => {
      if (!currentSourceIds.has(id) && map.getSource(id)) map.removeSource(id);
    });
    layerIdsRef.current = currentLayerIds;
    sourceIdsRef.current = currentSourceIds;

    let lastGeoBounds: [number, number, number, number] | null = null;
    layerEntries.forEach((entry) => {
      const { sourceId, layerId, result, hasGeo } = entry;
      if (!hasGeo) return;
      const ui = layerUi[entry.key];
      const opacity = ui?.opacity ?? 0.85;
      try {
        if (map.getSource(sourceId)) {
          if (map.getLayer(layerId)) map.setPaintProperty(layerId, "raster-opacity", opacity);
          return;
        }
        const [west, south, east, north] = result.bounds!;
        lastGeoBounds = [west, south, east, north];
        map.addSource(sourceId, {
          type: "image",
          url: resolveUrl(result.result_url),
          coordinates: [
            [west, north],
            [east, north],
            [east, south],
            [west, south],
          ],
        });
        map.addLayer({
          id: layerId,
          type: "raster",
          source: sourceId,
          paint: { "raster-opacity": opacity, "raster-fade-duration": 200 },
        });
      } catch (err) {
        console.error(`[MapView] failed to add layer ${sourceId}`, err);
      }
    });

    if (lastGeoBounds) map.fitBounds(lastGeoBounds, { padding: 60, maxZoom: 16 });
  }, [layerEntries, layerUi, ready]);

  // apply visibility/opacity from UI state
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    layerEntries.forEach((entry) => {
      if (!entry.hasGeo || !map.getLayer(entry.layerId)) return;
      const ui = layerUi[entry.key];
      const visible = ui?.visible !== false;
      try {
        map.setLayoutProperty(entry.layerId, "visibility", visible ? "visible" : "none");
        map.setPaintProperty(entry.layerId, "raster-opacity", ui?.opacity ?? 0.85);
      } catch (err) {
        console.error("[MapView] visibility/opacity error", err);
      }
    });
  }, [layerUi, layerEntries, ready]);

  const focusLatest = () => {
    const map = mapRef.current;
    if (!map) return;
    const geo = [...layerEntries].reverse().find((e) => e.hasGeo);
    if (geo?.result.bounds) {
      map.fitBounds(geo.result.bounds, { padding: 60, maxZoom: 16, duration: 800 });
    } else {
      map.flyTo({ center: AOI.center, zoom: AOI.zoom, duration: 800 });
    }
  };

  return (
    <div className="absolute inset-0 overflow-hidden bg-background">
      <div ref={ref} className="size-full" role="application" aria-label="遥感影像地图画布" />

      {/* subtle vignette */}
      <div className="pointer-events-none absolute inset-0 shadow-[inset_0_0_140px_rgba(0,0,0,0.5)]" />

      {/* no-geo results: shown as a centered thumbnail (can't be georeferenced) */}
      {layerEntries
        .filter((e) => !e.hasGeo && layerUi[e.key]?.visible !== false)
        .slice(-1)
        .map((e) => (
          <div
            key={e.key}
            className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center"
          >
            <img
              src={resolveUrl(e.result.result_url)}
              alt={e.result.type}
              className="max-h-[70%] max-w-[80%] rounded-lg object-contain shadow-2xl shadow-black/50"
              style={{ opacity: layerUi[e.key]?.opacity ?? 0.85 }}
            />
            <p className="mt-2 rounded-full border border-border bg-card/80 px-3 py-1 font-mono text-[10px] text-muted-foreground backdrop-blur-md">
              {e.result.type} · 无地理坐标，以缩略图展示
            </p>
          </div>
        ))}

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
          onClick={focusLatest}
          className="flex items-center gap-1.5 rounded-full border border-border bg-card/80 px-3 py-1.5 font-mono text-[11px] text-foreground backdrop-blur-md transition-colors hover:border-primary/50 hover:text-primary"
          title="定位到最新结果图层"
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

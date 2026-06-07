import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { GeospatialResult, LegendInfo } from "../../types";

export type { GeospatialResult };

interface MapPanelProps {
  endpoint: string;
  geospatialResults: GeospatialResult[];
}

type LayerEntry = {
  key: string;
  sourceId: string;
  layerId: string;
  result: GeospatialResult;
  hasGeo: boolean;
};

export function MapPanel({ geospatialResults }: MapPanelProps) {
  const mapContainer = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const layerIdsRef = useRef<Set<string>>(new Set());
  const sourceIdsRef = useRef<Set<string>>(new Set());
  const [opacity, setOpacity] = useState(0.8);
  const [mapReady, setMapReady] = useState(false);
  const [visibleLayers, setVisibleLayers] = useState<Record<string, boolean>>({});

  const layerEntries: LayerEntry[] = useMemo(
    () =>
      geospatialResults.map((result, idx) => {
        const key = `${result.type}-${result.imagery_id}-${idx}`;
        return {
          key,
          sourceId: `geo-${key}`,
          layerId: `geo-layer-${key}`,
          result,
          hasGeo: Array.isArray(result.bounds) && result.bounds.length === 4,
        };
      }),
    [geospatialResults],
  );

  const visibleLegendEntries = layerEntries.filter(
    (entry) =>
      visibleLayers[entry.key] !== false &&
      (entry.result.type === "ndvi" ||
        entry.result.type === "spectral_index" ||
        entry.result.type === "detection" ||
        entry.result.type === "segmentation"),
  );

  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: mapContainer.current,
      style: {
        version: 8,
        sources: {
          "osm-tiles": {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "&copy; OpenStreetMap",
          },
        },
        layers: [
          {
            id: "osm-layer",
            type: "raster",
            source: "osm-tiles",
            paint: { "raster-saturation": -0.8, "raster-brightness-max": 0.4 },
          },
        ],
      },
      center: [115.9, 22.9],
      zoom: 10,
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.on("load", () => setMapReady(true));
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
      layerIdsRef.current.clear();
      sourceIdsRef.current.clear();
      setMapReady(false);
    };
  }, []);

  useEffect(() => {
    setVisibleLayers((prev) => {
      const allowedKeys = new Set(layerEntries.map((entry) => entry.key));
      const next: Record<string, boolean> = {};
      layerEntries.forEach((entry) => {
        next[entry.key] = prev[entry.key] ?? true;
      });
      Object.keys(prev).forEach((key) => {
        if (!allowedKeys.has(key)) delete next[key];
      });
      return next;
    });
  }, [layerEntries]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    const currentLayerIds = new Set(layerEntries.map((entry) => entry.layerId));
    const currentSourceIds = new Set(layerEntries.map((entry) => entry.sourceId));
    layerIdsRef.current.forEach((layerId) => {
      if (!currentLayerIds.has(layerId) && map.getLayer(layerId)) {
        map.removeLayer(layerId);
      }
    });
    sourceIdsRef.current.forEach((sourceId) => {
      if (!currentSourceIds.has(sourceId) && map.getSource(sourceId)) {
        map.removeSource(sourceId);
      }
    });
    layerIdsRef.current = currentLayerIds;
    sourceIdsRef.current = currentSourceIds;

    layerEntries.forEach((entry) => {
      const { sourceId, layerId, result, hasGeo } = entry;
      if (!hasGeo) return;
      try {
        if (map.getSource(sourceId)) {
          map.setPaintProperty(layerId, "raster-opacity", opacity);
          return;
        }
        const [west, south, east, north] = result.bounds!;
        const url = result.result_url.startsWith("http")
          ? result.result_url
          : `${window.location.origin}${result.result_url}`;
        map.addSource(sourceId, {
          type: "image",
          url,
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
          paint: { "raster-opacity": opacity },
        });
        map.fitBounds([west, south, east, north], { padding: 40 });
      } catch (err) {
        console.error(`[MapPanel] Failed to add geospatial layer: ${sourceId}`, err);
      }
    });
  }, [layerEntries, opacity, mapReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    layerEntries.forEach((entry) => {
      if (!entry.hasGeo) return;
      if (!map.getLayer(entry.layerId)) return;
      const visible = visibleLayers[entry.key] !== false;
      try {
        map.setLayoutProperty(entry.layerId, "visibility", visible ? "visible" : "none");
      } catch (err) {
        console.error("[MapPanel] toggle error", err);
      }
    });
  }, [visibleLayers, layerEntries, mapReady]);

  const toggleLayer = (key: string) => {
    setVisibleLayers((prev) => ({ ...prev, [key]: prev[key] === false }));
  };

  const focusLayer = (entry: LayerEntry) => {
    const map = mapRef.current;
    if (!map || !entry.result.bounds) return;
    const [west, south, east, north] = entry.result.bounds;
    map.fitBounds([west, south, east, north], { padding: 40 });
  };

  const thumbnailEntries = layerEntries.filter(
    (entry) => !entry.hasGeo && visibleLayers[entry.key] !== false,
  );

  return (
    <div className="flex h-full flex-col border-l border-[#2a2a4a] bg-[#1a1a2e]" role="region" aria-label="影像地图预览">
      <div className="flex items-center justify-between border-b border-[#2a2a4a] px-3 py-2">
        <span className="text-sm font-medium text-[#a0a0c0]">地图</span>
        <div className="flex items-center gap-2">
          <label className="text-xs text-[#707090]">透明度</label>
          <input
            type="range"
            min="0"
            max="1"
            step="0.1"
            value={opacity}
            onChange={(e) => setOpacity(Number(e.target.value))}
            className="h-1 w-16 accent-emerald-500"
          />
        </div>
      </div>

      <div ref={mapContainer} className="relative flex-1" role="application" aria-label="遥感影像地图画布">
        {layerEntries.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center">
            <p className="text-sm text-[#505070]">上传影像后将在这里预览</p>
          </div>
        )}
        {thumbnailEntries.map((entry) => (
          <ThumbnailOverlay
            key={entry.key}
            label={layerLabel(entry.result)}
            resultUrl={entry.result.result_url}
            opacity={opacity}
          />
        ))}
      </div>

      {layerEntries.length > 0 && (
        <LayerList
          entries={layerEntries}
          visibility={visibleLayers}
          onToggle={toggleLayer}
          onFocus={focusLayer}
        />
      )}
      {visibleLegendEntries.length > 0 && <LegendList entries={visibleLegendEntries} />}
    </div>
  );
}

function ThumbnailOverlay({
  label,
  resultUrl,
  opacity,
}: {
  label: string;
  resultUrl: string;
  opacity: number;
}) {
  const url = resultUrl.startsWith("http")
    ? resultUrl
    : `${window.location.origin}${resultUrl}`;
  return (
    <div className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center">
      <img
        src={url}
        alt={label}
        className="max-h-[80%] max-w-[90%] rounded object-contain shadow-lg"
        style={{ opacity }}
      />
      <p className="mt-2 rounded bg-[#1a1a2e]/80 px-2 py-0.5 text-xs text-[#a0a0c0]">
        {label} - 无地理坐标，以缩略图展示
      </p>
    </div>
  );
}

interface LayerListProps {
  entries: LayerEntry[];
  visibility: Record<string, boolean>;
  onToggle: (key: string) => void;
  onFocus: (entry: LayerEntry) => void;
}

function LayerList({ entries, visibility, onToggle, onFocus }: LayerListProps) {
  return (
    <div className="max-h-32 overflow-y-auto border-t border-[#2a2a4a] px-3 py-2">
      <p className="mb-1 text-xs text-[#707090]">图层</p>
      <ul className="space-y-1">
        {entries.map((entry) => {
          const visible = visibility[entry.key] !== false;
          const label = layerLabel(entry.result);
          return (
            <li key={entry.key} className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => onToggle(entry.key)}
                className={`h-3.5 w-3.5 rounded border ${
                  visible
                    ? "border-emerald-400 bg-emerald-500"
                    : "border-[#3a3a5a] bg-transparent"
                }`}
                aria-label={visible ? "隐藏图层" : "显示图层"}
                title={visible ? "隐藏图层" : "显示图层"}
              />
              {entry.hasGeo ? (
                <button
                  type="button"
                  onClick={() => onFocus(entry)}
                  className="flex-1 truncate text-left text-xs text-[#a0a0c0] hover:text-emerald-400"
                  title="定位到此图层"
                >
                  {label}
                </button>
              ) : (
                <span className="flex-1 truncate text-xs text-[#707090]">
                  {label} <span className="text-[#505070]">(无坐标)</span>
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function LegendList({ entries }: { entries: LayerEntry[] }) {
  return (
    <div className="space-y-2 border-t border-[#2a2a4a] px-3 py-2">
      {entries.map((entry) => (
        <LayerLegend key={entry.key} result={entry.result} />
      ))}
    </div>
  );
}

function LayerLegend({ result }: { result: GeospatialResult }) {
  if (result.type === "segmentation") {
    if (!result.classes.length) {
      return <p className="text-xs text-[#707090]">地物分割 - 未识别到地物</p>;
    }
    return (
      <div>
        <p className="mb-1 text-xs text-[#707090]">地物分割 - 像素占比</p>
        <ul className="space-y-0.5">
          {result.classes.map((cls) => (
            <li key={cls.name} className="flex items-center gap-1.5">
              <span
                className="h-2.5 w-2.5 rounded-sm border border-[#2a2a4a]"
                style={{ backgroundColor: cls.color }}
              />
              <span className="text-[10px] text-[#a0a0c0]">
                {cls.label} ({cls.percentage.toFixed(1)}%)
              </span>
            </li>
          ))}
        </ul>
      </div>
    );
  }
  if (result.type === "detection") {
    if (!result.classes.length) {
      return <p className="text-xs text-[#707090]">目标检测 - 未检测到目标</p>;
    }
    return (
      <div>
        <p className="mb-1 text-xs text-[#707090]">
          目标检测 - 共 {result.detection_count} 个
        </p>
        <ul className="space-y-0.5">
          {result.classes.map((cls) => (
            <li key={cls.name} className="flex items-center gap-1.5">
              <span
                className="h-2.5 w-2.5 rounded-sm border border-[#2a2a4a]"
                style={{ backgroundColor: cls.color }}
              />
              <span className="text-[10px] text-[#a0a0c0]">
                {cls.label} ({cls.count})
              </span>
            </li>
          ))}
        </ul>
      </div>
    );
  }
  if (result.type !== "ndvi" && result.type !== "spectral_index") return null;
  const legend = result.legend ?? defaultLegend(result);
  return (
    <div>
      <p className="mb-1 text-xs text-[#707090]">{legend.label}</p>
      <div className="flex items-center gap-1">
        <span className="w-8 text-right text-[10px] text-[#707090]">{formatTick(legend.min)}</span>
        <div className="h-2 flex-1 rounded" style={{ background: gradientForPalette(legend.palette) }} />
        <span className="w-8 text-[10px] text-[#707090]">{formatTick(legend.max)}</span>
      </div>
    </div>
  );
}

function layerLabel(result: GeospatialResult) {
  const id = result.imagery_id.slice(0, 8);
  if (result.type === "preview") return `原图 - ${id}`;
  if (result.type === "ndvi") return `NDVI - ${id}`;
  if (result.type === "spectral_index") return `${result.index_type.toUpperCase()} - ${id}`;
  if (result.type === "composite") return `${compositeLabel(result.mode)} - ${id}`;
  if (result.type === "detection") return `目标检测 - ${id}`;
  if (result.type === "segmentation") return `地物分割 - ${id}`;
  return `图层 - ${id}`;
}

function compositeLabel(mode: string) {
  if (mode === "true_color") return "真彩色";
  if (mode === "false_color") return "假彩色";
  return "波段组合";
}

function defaultLegend(result: GeospatialResult): LegendInfo {
  if (result.type === "spectral_index") {
    const type = result.index_type.toLowerCase();
    if (type === "evi") return { label: "EVI", min: -1, max: 2.5, palette: "vegetation" };
    if (type === "savi") return { label: "SAVI", min: -1, max: 1.5, palette: "vegetation" };
    if (type === "gndvi") return { label: "GNDVI", min: -1, max: 1, palette: "vegetation" };
    if (type === "msavi") return { label: "MSAVI", min: -1, max: 1, palette: "vegetation" };
    if (type === "ndbi") return { label: "NDBI", min: -1, max: 1, palette: "built" };
    if (type === "bsi") return { label: "BSI", min: -1, max: 1, palette: "built" };
    if (type === "nbr") return { label: "NBR", min: -1, max: 1, palette: "burn" };
    if (type === "ndmi") return { label: "NDMI", min: -1, max: 1, palette: "water" };
    if (type === "ndwi" || type === "mndwi") return { label: type.toUpperCase(), min: -1, max: 1, palette: "water" };
  }
  return { label: "NDVI", min: -1, max: 1, palette: "vegetation" };
}

function gradientForPalette(palette: string) {
  if (palette === "water") {
    return "linear-gradient(to right, #7f3b08, #f6e8c3, #67a9cf, #053061)";
  }
  if (palette === "built") {
    return "linear-gradient(to right, #2c7bb6, #ffffbf, #fdae61, #a6611a)";
  }
  if (palette === "burn") {
    return "linear-gradient(to right, #006837, #ffffbf, #fdae61, #a60026)";
  }
  return "linear-gradient(to right, #a60026, #f46d43, #ffffbf, #66bd63, #006837)";
}

function formatTick(value: number) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

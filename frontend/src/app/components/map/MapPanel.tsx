import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { GeospatialResult } from "../../types";

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
  const hasNdviLayer = layerEntries.some((entry) => entry.result.type === "ndvi");

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
    <div className="flex flex-col h-full bg-[#1a1a2e] border-l border-[#2a2a4a]" role="region" aria-label="影像地图预览">
      <div className="flex items-center justify-between px-3 py-2 border-b border-[#2a2a4a]">
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
            className="w-16 h-1 accent-emerald-500"
          />
        </div>
      </div>

      <div ref={mapContainer} className="flex-1 relative" role="application" aria-label="遥感影像地图画布">
        {layerEntries.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center">
            <p className="text-[#505070] text-sm">上传影像后将在这里预览</p>
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
      {hasNdviLayer && <NdviLegend />}
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
    <div className="absolute inset-0 flex flex-col items-center justify-center z-10 pointer-events-none">
      <img
        src={url}
        alt={label}
        className="max-w-[90%] max-h-[80%] object-contain rounded shadow-lg"
        style={{ opacity }}
      />
      <p className="mt-2 text-xs text-[#a0a0c0] bg-[#1a1a2e]/80 px-2 py-0.5 rounded">
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
    <div className="px-3 py-2 border-t border-[#2a2a4a] max-h-32 overflow-y-auto">
      <p className="text-xs text-[#707090] mb-1">图层</p>
      <ul className="space-y-1">
        {entries.map((entry) => {
          const visible = visibility[entry.key] !== false;
          const label = layerLabel(entry.result);
          return (
            <li key={entry.key} className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => onToggle(entry.key)}
                className={`w-3.5 h-3.5 rounded border ${
                  visible
                    ? "bg-emerald-500 border-emerald-400"
                    : "bg-transparent border-[#3a3a5a]"
                }`}
                aria-label={visible ? "隐藏图层" : "显示图层"}
                title={visible ? "隐藏图层" : "显示图层"}
              />
              {entry.hasGeo ? (
                <button
                  type="button"
                  onClick={() => onFocus(entry)}
                  className="flex-1 text-left text-xs text-[#a0a0c0] hover:text-emerald-400 truncate"
                  title="定位到此图层"
                >
                  {label}
                </button>
              ) : (
                <span className="flex-1 text-xs text-[#707090] truncate">
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

function layerLabel(result: GeospatialResult) {
  const id = result.imagery_id.slice(0, 8);
  if (result.type === "preview") return `原图 - ${id}`;
  if (result.type === "ndvi") return `NDVI - ${id}`;
  return `图层 - ${id}`;
}

function NdviLegend() {
  return (
    <div className="px-3 py-2 border-t border-[#2a2a4a]">
      <p className="text-xs text-[#707090] mb-1">NDVI</p>
      <div className="flex items-center gap-1">
        <span className="text-[10px] text-[#707090]">-1</span>
        <div
          className="flex-1 h-2 rounded"
          style={{
            background:
              "linear-gradient(to right, #a60026, #d73027, #f46d43, #fdae61, #fee08b, #ffffbf, #d9ef8b, #a6d96a, #66bd63, #1a9850, #006837)",
          }}
        />
        <span className="text-[10px] text-[#707090]">1</span>
      </div>
    </div>
  );
}

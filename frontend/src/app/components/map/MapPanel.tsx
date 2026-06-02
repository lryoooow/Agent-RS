import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { GeospatialResult } from "../../types";

export type { GeospatialResult };

interface MapPanelProps {
  endpoint: string;
  geospatialResults: GeospatialResult[];
}

export function MapPanel({ endpoint, geospatialResults }: MapPanelProps) {
  const mapContainer = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [opacity, setOpacity] = useState(0.8);
  const [mapReady, setMapReady] = useState(false);

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
      setMapReady(false);
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    geospatialResults.forEach((result, idx) => {
      const sourceId = `ndvi-${result.imagery_id}-${idx}`;
      const layerId = `ndvi-layer-${result.imagery_id}-${idx}`;

      try {
        if (map.getSource(sourceId)) {
          map.setPaintProperty(layerId, "raster-opacity", opacity);
          return;
        }

        if (!result.bounds) return;
        const [west, south, east, north] = result.bounds;
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
        console.error(`[MapPanel] Failed to add NDVI layer: ${sourceId}`, err);
      }
    });
  }, [geospatialResults, opacity, mapReady]);

  return (
    <div className="flex flex-col h-full bg-[#1a1a2e] border-l border-[#2a2a4a]">
      <div className="flex items-center justify-between px-3 py-2 border-b border-[#2a2a4a]">
        <span className="text-sm font-medium text-[#a0a0c0]">Map Panel</span>
        <div className="flex items-center gap-2">
          <label className="text-xs text-[#707090]">Opacity</label>
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
      <div ref={mapContainer} className="flex-1 relative">
        {geospatialResults.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center">
            <p className="text-[#505070] text-sm">上传影像开始分析</p>
          </div>
        )}
      </div>
      {geospatialResults.length > 0 && <NdviLegend />}
    </div>
  );
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

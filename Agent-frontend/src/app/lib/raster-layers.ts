import type { Map as MapLibreMap, ImageSource, ImageSourceSpecification } from "maplibre-gl";
import type { RSLayer } from "./layers";
import { REFERENCE_PREFIX } from "./map-style";
export function syncRasterOverlays(map: MapLibreMap, geoLayers: (RSLayer & {bounds: [number,number,number,number]})[], absoluteUrl: (url: string)=>string) {
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
        else {
          const source = map.getSource(srcId) as ImageSource;
          const coordinates: [[number, number], [number, number], [number, number], [number, number]] = [[west,north],[east,north],[east,south],[west,south]];
          const previous = style.sources[srcId] as ImageSourceSpecification;
          if (previous.url !== absoluteUrl(layer.url!) || JSON.stringify(previous.coordinates) !== JSON.stringify(coordinates)) {
            source.updateImage({url: absoluteUrl(layer.url!), coordinates});
          }
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
        map.moveLayer(layerId);
      } catch (err) {
        console.error(`[MapView] failed to add layer ${layerId}`, err);
      }
    }

    // Imagery/results < reference names/roads < user drawing/ROI/guides.
    // Explicit groups also handle future raster labels and labels added after a ROI.
    for (const overlay of map.getStyle().layers ?? []) {
      if (overlay.id.startsWith(REFERENCE_PREFIX)) map.moveLayer(overlay.id);
    }
    for (const overlay of map.getStyle().layers ?? []) {
      if (!overlay.id.startsWith(REFERENCE_PREFIX) && !["raster", "background"].includes(overlay.type)) map.moveLayer(overlay.id);
    }

}

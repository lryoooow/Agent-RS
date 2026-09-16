import type { ExpressionSpecification, LayerSpecification, Map as MapLibreMap, StyleSpecification, SymbolLayerSpecification } from "maplibre-gl";

export const REFERENCE_PREFIX = "map-reference-";
export const LABELS_STORAGE_KEY = "agent-rs.map-labels.v1";
const SOURCE = "map-reference";
// OpenMapTiles names are geographic coordinates (Web Mercator tiles), matching
// our imagery. Prefer Chinese, then the feature's original/local name.
const NAME: ExpressionSpecification = ["coalesce", ["get", "name:zh"], ["get", "name"], ["get", "name:en"], ""];

function label(id: string, sourceLayer: string, minzoom: number, filter?: SymbolLayerSpecification["filter"], line = false, color = "#ffffff"): SymbolLayerSpecification {
  return {
    id: REFERENCE_PREFIX + id, type: "symbol", source: SOURCE, "source-layer": sourceLayer,
    minzoom, ...(filter ? { filter } : {}),
    layout: {
      "text-field": NAME, "text-font": ["Noto Sans Regular"],
      "text-size": ["interpolate", ["linear"], ["zoom"], 5, 11, 12, 13, 17, 15],
      "text-max-width": 9, "text-padding": 5,
      ...(line ? { "symbol-placement": "line", "symbol-spacing": 280 } : {}),
    },
    paint: { "text-color": color, "text-halo-color": "#18212b", "text-halo-width": 1.5, "text-halo-blur": 0.4 },
  };
}

function referenceLayers(): LayerSpecification[] {
  return [
    {
      id: REFERENCE_PREFIX + "major-roads", type: "line", source: SOURCE, "source-layer": "transportation", minzoom: 7,
      filter: ["match", ["get", "class"], ["motorway", "trunk", "primary", "secondary"], true, false],
      paint: { "line-color": "#f7d58b", "line-opacity": 0.45, "line-width": ["interpolate", ["linear"], ["zoom"], 7, 0.5, 16, 1.5] },
    },
    {
      id: REFERENCE_PREFIX + "local-roads", type: "line", source: SOURCE, "source-layer": "transportation", minzoom: 14,
      filter: ["match", ["get", "class"], ["tertiary", "minor", "service"], true, false],
      paint: { "line-color": "#e8eef5", "line-opacity": 0.3, "line-width": 0.75 },
    },
    // Lower priority labels first: MapLibre places later symbol layers first.
    label("poi", "poi", 15, ["<=", ["get", "rank"], 10], false, "#e8edda"),
    label("peaks", "mountain_peak", 11, undefined, false, "#e8edda"),
    label("water-line", "waterway", 11, undefined, true, "#a8e3ff"),
    label("water-area-line", "water_name", 4, ["==", ["geometry-type"], "LineString"], true, "#a8e3ff"),
    label("water-area", "water_name", 3, ["==", ["geometry-type"], "Point"], false, "#a8e3ff"),
    label("streets", "transportation_name", 14, ["match", ["get", "class"], ["minor", "service", "track", "path"], true, false], true),
    label("roads", "transportation_name", 10, ["match", ["get", "class"], ["motorway", "trunk", "primary", "secondary", "tertiary"], true, false], true, "#ffe4ac"),
    label("neighborhood", "place", 12, ["match", ["get", "class"], ["suburb", "quarter", "neighbourhood", "hamlet", "isolated_dwelling"], true, false]),
    label("village", "place", 10, ["==", ["get", "class"], "village"]),
    label("town", "place", 8, ["==", ["get", "class"], "town"]),
    label("city", "place", 3, ["==", ["get", "class"], "city"]),
    { ...label("state", "place", 3, ["match", ["get", "class"], ["state", "province"], true, false]), maxzoom: 10 },
    { ...label("country", "place", 1, ["==", ["get", "class"], "country"]), maxzoom: 7 },
  ];
}

export function createSatelliteStyle(labels = true): StyleSpecification {
  return {
    version: 8,
    glyphs: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf",
    sources: {
      esri: {
        type: "raster", tileSize: 256, maxzoom: 18,
        tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
        attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
      },
      [SOURCE]: {
        type: "vector", url: "https://tiles.openfreemap.org/planet",
        attribution: '<a href="https://openfreemap.org/" target="_blank" rel="noopener noreferrer">OpenFreeMap</a> · <a href="https://www.openmaptiles.org/" target="_blank" rel="noopener noreferrer">© OpenMapTiles</a> · <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">© OpenStreetMap</a>',
      },
    },
    layers: [
      { id: "bg", type: "background", paint: { "background-color": "#0a0e14" } },
      { id: "esri", type: "raster", source: "esri" },
      ...referenceLayers().map(layer => ({ ...layer, layout: { ...layer.layout, visibility: labels ? "visible" as const : "none" as const } })),
    ],
  };
}

export function setReferenceVisibility(map: MapLibreMap, visible: boolean) {
  for (const layer of map.getStyle().layers ?? []) {
    if (layer.id.startsWith(REFERENCE_PREFIX)) map.setLayoutProperty(layer.id, "visibility", visible ? "visible" : "none");
  }
}

export function readLabelsPreference(): boolean {
  try { return localStorage.getItem(LABELS_STORAGE_KEY) !== "false"; }
  catch { return true; }
}

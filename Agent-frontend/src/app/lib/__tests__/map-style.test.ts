import { afterEach, expect, it, vi } from "vitest";
import { createSatelliteStyle, LABELS_STORAGE_KEY, readLabelsPreference, REFERENCE_PREFIX, setReferenceVisibility } from "../map-style";
import type { Map as MapLibreMap } from "maplibre-gl";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("defaults on, remembers an explicit off preference and tolerates blocked storage", () => {
  expect(readLabelsPreference()).toBe(true);
  const getItem = vi.fn((key: string) => key === LABELS_STORAGE_KEY ? "false" : null);
  vi.stubGlobal("localStorage", { getItem });
  expect(readLabelsPreference()).toBe(false);
  getItem.mockImplementation(() => { throw new Error("blocked"); });
  expect(readLabelsPreference()).toBe(true);
});

it("toggles every reference layer without hiding imagery, results or drawing", () => {
  const style = createSatelliteStyle();
  const setLayoutProperty = vi.fn();
  const map = { getStyle: () => ({ layers: [...style.layers, {id: "rs-img-image"}, {id: "rs-roi"}] }), setLayoutProperty } as unknown as MapLibreMap;
  setReferenceVisibility(map, false);
  const ids = style.layers.filter(l => l.id.startsWith(REFERENCE_PREFIX)).map(l => l.id);
  expect(setLayoutProperty.mock.calls).toEqual(ids.map(id => [id, "visibility", "none"]));
  setLayoutProperty.mockClear();
  setReferenceVisibility(map, true);
  expect(setLayoutProperty.mock.calls).toEqual(ids.map(id => [id, "visibility", "visible"]));
  expect(createSatelliteStyle(false).layers.filter(l => l.id.startsWith(REFERENCE_PREFIX)).every(l => l.layout?.visibility === "none")).toBe(true);
});

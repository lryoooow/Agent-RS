import { useCallback, useEffect, useState } from "react";
import type { MapAnnotation } from "../types";

// Unowned legacy data is never adopted by the next signed-in account.
export const MAP_ANNOTATIONS_KEY = "map_annotations";
export function mapAnnotationsKey(ownerId: string) {
  return `${MAP_ANNOTATIONS_KEY}:v2:${encodeURIComponent(ownerId)}`;
}
function isMapAnnotation(value: unknown): value is MapAnnotation {
  if (!value || typeof value !== "object") return false;
  const feature = value as Record<string, unknown>;
  if (feature.type !== "Feature" || !feature.geometry || typeof feature.geometry !== "object") return false;
  const geometry = feature.geometry as Record<string, unknown>;
  return ["Polygon", "Point", "LineString"].includes(String(geometry.type)) && Array.isArray(geometry.coordinates);
}
export function readStoredMapAnnotations(ownerId: string | null, storage: Pick<Storage, "getItem"> = localStorage): MapAnnotation[] {
  if (!ownerId) return [];
  try {
    const parsed: unknown = JSON.parse(storage.getItem(mapAnnotationsKey(ownerId)) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter(isMapAnnotation) : [];
  } catch { return []; }
}
export function useMapAnnotations(onChange?: (annotations: MapAnnotation[]) => void, ownerId: string | null = null) {
  const [state, setState] = useState(() => ({ ownerId, annotations: readStoredMapAnnotations(ownerId) }));
  const annotations = state.ownerId === ownerId ? state.annotations : [];
  useEffect(() => {
    setState({ ownerId, annotations: readStoredMapAnnotations(ownerId) });
    const update = (event: StorageEvent) => {
      if (ownerId && (event.key === mapAnnotationsKey(ownerId) || event.key === null)) {
        setState({ ownerId, annotations: readStoredMapAnnotations(ownerId) });
      }
    };
    window.addEventListener("storage", update);
    return () => window.removeEventListener("storage", update);
  }, [ownerId]);
  useEffect(() => { onChange?.(annotations); }, [annotations, onChange]);
  const saveAnnotations = useCallback((next: MapAnnotation[]) => {
    setState({ ownerId, annotations: next });
    if (ownerId) {
      try { localStorage.setItem(mapAnnotationsKey(ownerId), JSON.stringify(next)); } catch { /* session remains usable */ }
    }
  }, [ownerId]);
  return [annotations, saveAnnotations] as const;
}

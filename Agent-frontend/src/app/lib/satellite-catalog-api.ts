import { apiJson } from "./http";

export interface SatelliteCatalogStatus {
  updated: string;
  groups: { name: string; count: number; updated: string }[];
  stale?: boolean;
  refreshing?: boolean;
}

export function parseSatelliteCatalog(raw: unknown): SatelliteCatalogStatus | undefined {
  if (!raw || typeof raw !== "object") return;
  const data = raw as SatelliteCatalogStatus;
  if (!Number.isFinite(Date.parse(data.updated)) || !Array.isArray(data.groups) || !data.groups.length) return;
  const names = new Set<string>();
  for (const group of data.groups) {
    if (!group || typeof group.name !== "string" || names.has(group.name) || !Number.isInteger(group.count) || group.count <= 0 || !Number.isFinite(Date.parse(group.updated))) return;
    names.add(group.name);
  }
  if (!names.has("active") || !names.has("resource") || !names.has("weather")) return;
  return data;
}

export function fetchSatelliteCatalog(signal?: AbortSignal) {
  return apiJson("/groups.json", { signal, timeoutMs: 10_000 }, parseSatelliteCatalog);
}

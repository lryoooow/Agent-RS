import { apiFetch } from "./http";
import type { ImageryMeta } from "../hooks/useImageryUpload";
export async function listAvailableImagery(): Promise<ImageryMeta[]> {
  return (await apiFetch("/imagery")).json();
}
export async function getImagery(id: string): Promise<ImageryMeta> {
  return (await apiFetch(`/imagery/${encodeURIComponent(id)}`)).json();
}

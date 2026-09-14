// 卫星影像检索 API（免账号公共数据源：Sentinel-2 / Landsat）。
// 统一走 lib/http.ts 客户端：同源 cookie、错误归一、按调用点超时。
import { apiFetch } from "./http";

export interface SceneCard {
  key: string;
  satellite: string;
  item_id: string;
  datetime: string;
  cloud_cover: number | null;
  bbox: number[];
  resolution_m: number | null;
  display_name: string;
  preview_url: string;
  download_url: string;
}

export interface SceneSearchResponse {
  scenes: SceneCard[];
  notes: string[];
}

export interface SceneSearchParams {
  bbox?: number[];
  place?: string;
  start_date?: string;
  end_date?: string;
  cloud_max?: number;
  source?: "auto" | "sentinel2" | "landsat";
  limit?: number;
}

export async function searchImagery(params: SceneSearchParams): Promise<SceneSearchResponse> {
  // STAC 双源检索可能要几十秒（远端超时上限 20s×2 源），放宽到 60s。
  const response = await apiFetch("/scenes/search", {
    method: "POST",
    json: params,
    timeoutMs: 60_000,
  });
  return (await response.json()) as SceneSearchResponse;
}

export interface SceneImportResponse {
  imagery_id: string;
  item_id: string;
  satellite: string;
  band_roles: Record<string, number>;
}

export async function importScene(sceneKey: string): Promise<SceneImportResponse> {
  // 远程合成五波段 GeoTIFF 是重活，3 分钟。
  const response = await apiFetch(`/scenes/${sceneKey}/import`, {
    method: "POST",
    timeoutMs: 180_000,
  });
  return (await response.json()) as SceneImportResponse;
}

// 相对 /api 路径 → 同源绝对地址（<img> 与下载链接用；cookie 同源自动携带）。
export function absoluteUrl(path: string): string {
  return path.startsWith("http") ? path : `${window.location.origin}${path}`;
}

// 下载场景 TIF：fetch → blob → 保存。
// 不用 <a href> 直跳：首次下载需服务端远程合成（可达数十秒），anchor 导航
// 零反馈零错误呈现，用户只会觉得"点了没反应"；fetch 版本可给 loading、
// 错误与超时（180s，合成是重活），scene.tif 有磁盘缓存所以二次下载很快。
export async function downloadSceneTif(
  sceneKey: string,
  itemId: string,
  options?: { signal?: AbortSignal },
): Promise<{ filename: string; sizeBytes: number }> {
  const response = await apiFetch(`/scenes/${sceneKey}/download`, {
    timeoutMs: 180_000,
    signal: options?.signal,
    retryOnNetworkError: false,
  });
  const blob = await response.blob();
  const filename = `${itemId}.tif`;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
  return { filename, sizeBytes: blob.size };
}

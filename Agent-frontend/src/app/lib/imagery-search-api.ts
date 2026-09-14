// 卫星影像检索 API（免账号公共数据源：Sentinel-2 / Landsat）。
// 形制对齐 conversations-api.ts：同源 cookie 鉴权 + 统一错误文案提取。
// 注意：入参是聊天端点（如 /api/chat），必须经 getApiBaseEndpoint 剥掉 /chat
// 再拼路径——直接拼会得到 /api/chat/scenes/... → 404。
import { getApiBaseEndpoint } from "../config";


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

function apiBase(chatEndpoint: string): string {
  return getApiBaseEndpoint(chatEndpoint);
}

async function readApiError(response: Response): Promise<string> {
  try {
    const payload = await response.json();
    const detail = payload?.detail;
    if (typeof detail === "string") return detail;
    if (detail?.message) return String(detail.message);
  } catch {
    // 非 JSON 响应走状态码兜底
  }
  return `请求失败（HTTP ${response.status}）`;
}

export async function searchImagery(
  endpoint: string,
  params: SceneSearchParams,
): Promise<SceneSearchResponse> {
  const response = await fetch(`${apiBase(endpoint)}/scenes/search`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!response.ok) throw new Error(await readApiError(response));
  return (await response.json()) as SceneSearchResponse;
}

export interface SceneImportResponse {
  imagery_id: string;
  item_id: string;
  satellite: string;
  band_roles: Record<string, number>;
}

export async function importScene(
  endpoint: string,
  sceneKey: string,
): Promise<SceneImportResponse> {
  const response = await fetch(`${apiBase(endpoint)}/scenes/${sceneKey}/import`, {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok) throw new Error(await readApiError(response));
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
  const response = await fetch(absoluteUrl(`/api/scenes/${sceneKey}/download`), {
    credentials: "include",
    signal: options?.signal ?? AbortSignal.timeout(180_000),
  });
  if (!response.ok) throw new Error(await readApiError(response));
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

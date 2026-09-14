// 统一 HTTP 客户端：全平台唯一的 fetch 出口（P2 制度化）。
//
// 制度（对照后端 P1 错误契约）：
// - 基址：模块级解析一次。默认相对 "/api"（同源反代部署），
//   可用 VITE_API_BASE 覆盖（如独立后端域 + CORS）。
// - 超时：所有请求默认 30s（AbortSignal.timeout 与调用方 signal 组合）；
//   重活（上传/下载/合成）按调用点覆写。
// - 错误：归一为 ApiError{status, code, message}，理解全部四种形态——
//   新契约 {error:{code,message}}、旧 {detail:{code,message}}、
//   旧 {detail:"字符串"}、反向代理 HTML 错误页。
// - 重试：幂等 GET 网络级失败（TypeError）退避 400ms 重试一次；
//   4xx/5xx 一律不重试。
// - 凭据：同源 cookie 始终携带。

/// <reference types="vite/client" />

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

const API_BASE: string = (() => {
  const configured = import.meta.env.VITE_API_BASE as string | undefined;
  if (configured && configured.trim()) return configured.trim().replace(/\/$/, "");
  return "/api";
})();

/** API 基址（模块级常量；测试可 vi.mock 本模块覆写）。 */
export function apiBase(): string {
  return API_BASE;
}

interface ApiFetchOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  json?: unknown;
  formData?: FormData;
  timeoutMs?: number;
  signal?: AbortSignal;
  /** GET 默认 true：网络级失败重试一次。 */
  retryOnNetworkError?: boolean;
}

function composeSignal(timeoutMs: number, signal?: AbortSignal): AbortSignal {
  const timeout = AbortSignal.timeout(timeoutMs);
  if (!signal) return timeout;
  return AbortSignal.any([signal, timeout]);
}

function looksLikeHtml(text: string): boolean {
  return /^\s*<(?:!doctype|html)/i.test(text);
}

async function toApiError(response: Response): Promise<ApiError> {
  let code = `HTTP_${response.status}`;
  let message = `${response.status} ${response.statusText || "请求失败"}`.trim();
  try {
    const text = await response.text();
    if (text && !looksLikeHtml(text)) {
      const payload = JSON.parse(text) as Record<string, unknown>;
      const error = payload.error;
      if (error && typeof error === "object") {
        const { code: c, message: m } = error as Record<string, unknown>;
        if (typeof c === "string" && c) code = c;
        if (typeof m === "string" && m) message = m;
      } else if (typeof payload.detail === "string") {
        message = payload.detail;
      } else if (payload.detail && typeof payload.detail === "object") {
        const { code: c, message: m } = payload.detail as Record<string, unknown>;
        if (typeof c === "string" && c) code = c;
        if (typeof m === "string" && m) message = m;
      }
    } else if (text && looksLikeHtml(text)) {
      // 反向代理错误页（nginx 502 等）：拿不到结构化信息，用状态码语义。
      message = `网关错误（HTTP ${response.status}），请稍后重试。`;
    }
  } catch {
    // 非 JSON 响应保留状态码兜底文案
  }
  return new ApiError(response.status, code, message);
}

function isTimeoutError(exc: unknown): boolean {
  return (
    exc instanceof DOMException &&
    (exc.name === "TimeoutError" || exc.name === "AbortError")
  );
}

export async function apiFetch(
  path: string,
  options: ApiFetchOptions = {},
): Promise<Response> {
  const {
    method = "GET",
    json,
    formData,
    timeoutMs = 30_000,
    signal,
    retryOnNetworkError = method === "GET",
  } = options;

  const url = `${apiBase()}${path.startsWith("/") ? path : `/${path}`}`;
  const init: RequestInit = {
    method,
    credentials: "include",
    signal: composeSignal(timeoutMs, signal),
    headers: json !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: json !== undefined ? JSON.stringify(json) : (formData ?? undefined),
  };

  const attempt = async (): Promise<Response> => {
    const response = await fetch(url, init);
    if (!response.ok) throw await toApiError(response);
    return response;
  };

  try {
    return await attempt();
  } catch (exc) {
    // 网络级失败（TypeError）且允许重试：退避一次。用户主动中止不重试。
    if (retryOnNetworkError && exc instanceof TypeError) {
      await new Promise((resolve) => setTimeout(resolve, 400));
      return await attempt();
    }
    if (isTimeoutError(exc) && (!signal || !signal.aborted)) {
      throw new ApiError(0, "TIMEOUT", "请求超时，请检查网络后重试。");
    }
    throw exc;
  }
}

export async function apiJson<T>(
  path: string,
  options: ApiFetchOptions = {},
  parse?: (raw: unknown) => T | undefined,
): Promise<T> {
  const response = await apiFetch(path, options);
  const raw: unknown = await response.json().catch(() => null);
  if (parse) {
    const parsed = parse(raw);
    if (parsed === undefined) {
      throw new ApiError(0, "BAD_PAYLOAD", "服务端响应格式异常，请稍后重试。");
    }
    return parsed;
  }
  return raw as T;
}

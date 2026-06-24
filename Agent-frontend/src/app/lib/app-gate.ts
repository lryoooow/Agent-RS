import type { ConfigResponse } from "../types";

// 应用门控（纯函数，可单测）：决定首屏渲染 Splash / 登录页 / 主应用。
//
// 历史 bug（App.tsx 旧逻辑 `authRequired && !authed && !auth.loading`）：
//   首次 GET /auth/me 解析期间 auth.loading=true → 条件为假 → 先渲染主应用再跳登录页，可见闪屏。
// 修法：把"配置/会话尚未就绪"显式收敛为 splash 态，绝不在未知态下先渲染主应用。
//
// 规则优先级：
//   1) serverConfig 未拉到 或 会话仍在解析 → "splash"（不预判，不闪主界面）
//   2) 需要登录 且 未认证 → "login"
//   3) 其余（不需登录 / 已认证）→ "app"
export type AppGate = "splash" | "login" | "app";

export function resolveAppGate(input: {
  serverConfig: ConfigResponse | null;
  authLoading: boolean;
  authed: boolean;
}): AppGate {
  const { serverConfig, authLoading, authed } = input;
  if (serverConfig == null || authLoading) return "splash";
  if (serverConfig.auth_required && !authed) return "login";
  return "app";
}

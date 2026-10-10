export function automaticMarkdownImage(value: unknown, origin = window.location.origin): string | null {
  if (typeof value !== "string" || !value || /[\\\x00-\x20]/.test(value) || value.startsWith("//")) return null;
  try {
    const url = new URL(value, origin);
    if (url.origin !== origin || url.username || url.password || url.hash) return null;
    if (!/^\/api\/imagery\/[a-f0-9]{12}\/results\/[^/]+\.(png|jpe?g|webp)$/i.test(url.pathname)) return null;
    return url.href;
  } catch { return null; }
}
export function manualImageLink(value: unknown): string | null {
  if (typeof value !== "string" || /[\\\x00-\x20]/.test(value) || value.startsWith("//")) return null;
  try {
    const url = new URL(value);
    return ["https:","http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}

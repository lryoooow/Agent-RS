/** Browser URL helpers shared by map imagery and downloadable artifacts. */

function browserOrigin(): string {
  return window.location.origin;
}

export function absoluteUrl(value: string): string {
  if (!value) return value;
  try {
    const url = new URL(value, browserOrigin());
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : "";
  } catch {
    return "";
  }
}

export function isSafeSameOriginUrl(value: unknown, origin = browserOrigin()): value is string {
  if (typeof value !== "string" || !value.trim()) return false;
  try {
    const url = new URL(value, origin);
    return (
      (url.protocol === "http:" || url.protocol === "https:") &&
      url.origin === origin &&
      !url.username &&
      !url.password
    );
  } catch {
    return false;
  }
}

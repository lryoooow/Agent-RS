function readable(value: unknown): string | null {
  if (typeof value === "string") return value.trim() || null;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    const parts = value.map(readable).filter((part): part is string => Boolean(part));
    return parts.length > 0 ? parts.join("；") : null;
  }
  if (value && typeof value === "object") {
    const candidate = value as Record<string, unknown>;
    const nested = readable(candidate.message) ?? readable(candidate.msg) ?? readable(candidate.detail);
    if (nested) return nested;
    try {
      return JSON.stringify(candidate);
    } catch {
      return null;
    }
  }
  return null;
}

export function readErrorMessage(payload: unknown): string | null {
  if (
    payload &&
    typeof payload === "object" &&
    "error" in payload &&
    payload.error &&
    typeof payload.error === "object" &&
    "message" in payload.error
  ) {
    return readable(payload.error.message);
  }
  if (
    payload &&
    typeof payload === "object" &&
    "detail" in payload &&
    payload.detail &&
    typeof payload.detail === "object" &&
    "message" in payload.detail
  ) {
    return readable(payload.detail.message);
  }
  if (payload && typeof payload === "object" && "detail" in payload) {
    return readable(payload.detail);
  }
  return readable(payload);
}

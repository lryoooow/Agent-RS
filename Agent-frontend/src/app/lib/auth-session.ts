let epoch = 0;
let expiredEpoch = -1;
const listeners = new Set<() => void>();
export function currentAuthEpoch() { return epoch; }
export function advanceAuthEpoch() { epoch += 1; return epoch; }
export function subscribeAuthExpiry(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; }
export function notifyAuthFailure(code: string, requestEpoch: number) {
  if (!["AUTHENTICATION_REQUIRED", "AUTH_REQUIRED", "SESSION_EXPIRED", "SESSION_INVALID"].includes(code) || requestEpoch !== epoch || expiredEpoch === epoch) return;
  expiredEpoch = epoch;
  for (const listener of listeners) listener();
}

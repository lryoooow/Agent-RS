import { useEffect, useRef } from "react";

export function useAutoScroll<T extends HTMLElement>(dependencies: readonly unknown[]) {
  const ref = useRef<T>(null);

  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: "smooth" });
  }, dependencies);

  return ref;
}

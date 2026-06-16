import { useEffect, useRef } from "react";

export function useAutosizeTextarea(value: string, maxHeight = 200) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, maxHeight) + "px";
  }, [maxHeight, value]);

  return ref;
}

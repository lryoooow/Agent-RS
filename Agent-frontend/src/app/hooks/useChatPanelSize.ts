import { useEffect, useRef, useState, type PointerEvent, type KeyboardEvent } from "react";

const STORAGE_KEY = "agent-rs.chat-panel-size.v1";
type Size = { width: number; height: number };
type Axis = "width" | "height" | "both";

function clamp(size: Size): Size {
  const maxWidth = Math.max(240, window.innerWidth - 32);
  const maxHeight = Math.max(180, window.innerHeight - 124);
  return {
    width: Math.min(maxWidth, Math.max(Math.min(360, maxWidth), size.width)),
    height: Math.min(maxHeight, Math.max(Math.min(340, maxHeight), size.height)),
  };
}

function initialSize(): Size {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null");
    if (saved && Number.isFinite(saved.width) && Number.isFinite(saved.height)) return clamp(saved);
  } catch { /* Storage can be disabled by the browser. */ }
  return clamp({ width: 420, height: window.innerHeight - 124 });
}

export function useChatPanelSize() {
  const [size, setSize] = useState(initialSize);
  const drag = useRef<{ x: number; y: number; size: Size; axis: Axis } | null>(null);
  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(size)); } catch { /* Optional preference. */ }
  }, [size]);
  useEffect(() => {
    const resize = () => setSize((previous) => clamp(previous));
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);

  function handle(axis: Axis) {
    return {
      onPointerDown(event: PointerEvent<HTMLButtonElement>) {
        if (event.button !== 0) return;
        event.preventDefault();
        event.currentTarget.setPointerCapture(event.pointerId);
        drag.current = { x: event.clientX, y: event.clientY, size, axis };
      },
      onPointerMove(event: PointerEvent<HTMLButtonElement>) {
        const start = drag.current;
        if (!start || !event.currentTarget.hasPointerCapture(event.pointerId)) return;
        setSize(clamp({
          width: start.size.width + (start.axis !== "height" ? event.clientX - start.x : 0),
          height: start.size.height + (start.axis !== "width" ? event.clientY - start.y : 0),
        }));
      },
      onPointerUp(event: PointerEvent<HTMLButtonElement>) {
        drag.current = null;
        if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
      },
      onLostPointerCapture() { drag.current = null; },
      onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
        const delta = event.shiftKey ? 40 : 10;
        const dx = axis !== "height" ? ({ ArrowLeft: -delta, ArrowRight: delta }[event.key] ?? 0) : 0;
        const dy = axis !== "width" ? ({ ArrowUp: -delta, ArrowDown: delta }[event.key] ?? 0) : 0;
        if (dx || dy) {
          event.preventDefault();
          setSize((previous) => clamp({ width: previous.width + dx, height: previous.height + dy }));
        }
      },
    };
  }
  return { size, handle, reset: () => setSize(clamp({ width: 420, height: window.innerHeight - 124 })) };
}

import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

const STORAGE_KEY = "agent-rs.layer-panel-size.v1";
const TOP_OFFSET = 108;
const VIEWPORT_GAP = 16;

type Size = { width: number; height: number };
type Axis = "width" | "height" | "both";

function clamp(size: Size): Size {
  const maxWidth = Math.max(240, window.innerWidth - VIEWPORT_GAP * 2);
  const maxHeight = Math.max(180, window.innerHeight - TOP_OFFSET - VIEWPORT_GAP);
  const minWidth = Math.min(280, maxWidth);
  const minHeight = Math.min(240, maxHeight);
  return {
    width: Math.min(maxWidth, Math.max(minWidth, size.width)),
    height: Math.min(maxHeight, Math.max(minHeight, size.height)),
  };
}

function defaultSize(): Size {
  return clamp({ width: 360, height: 560 });
}

function initialSize(): Size {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null");
    if (saved && Number.isFinite(saved.width) && Number.isFinite(saved.height)) return clamp(saved);
  } catch { /* Browser storage is an optional preference. */ }
  return defaultSize();
}

export function useLayerPanelSize() {
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
          // The panel is fixed to the right edge, so moving its left edge left makes it wider.
          width: start.size.width + (start.axis !== "height" ? start.x - event.clientX : 0),
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
        const dw = axis !== "height" ? ({ ArrowLeft: delta, ArrowRight: -delta }[event.key] ?? 0) : 0;
        const dh = axis !== "width" ? ({ ArrowUp: -delta, ArrowDown: delta }[event.key] ?? 0) : 0;
        if (dw || dh) {
          event.preventDefault();
          setSize((previous) => clamp({ width: previous.width + dw, height: previous.height + dh }));
        }
      },
    };
  }

  return { size, handle, reset: () => setSize(defaultSize()) };
}

import { useCallback, useEffect, useRef, useState } from "react";
import { Plus, Minus, Crosshair, SquareDashedMousePointer, X } from "lucide-react";
import type { RSLayer } from "../lib/layers";
import { pixelRoiFromCorners, isDegenerateRoi, type PixelRoi } from "../lib/roi";

// 无地理坐标影像的可交互查看器：滚轮缩放 + 拖拽平移 + 框选（输出影像内相对 bbox 0..1）。
// 替换 MapView 旧的 pointer-events-none 静态 <img> 兜底（geo 影像仍走 maplibre，不在此组件）。
// 多个无坐标图层按透明度叠放（保留原叠放语义：影像在底、结果在上）。
// 纯 CSS transform（translate+scale），无新依赖。

function absoluteUrl(url: string) {
  if (!url) return url;
  return url.startsWith("http") ? url : `${window.location.origin}${url}`;
}

const MIN_SCALE = 0.2;
const MAX_SCALE = 12;

export function ImageViewer({
  layers,
  roi,
  onSelectRegion,
  onClearRegion,
}: {
  layers: RSLayer[];
  roi: PixelRoi | null;
  onSelectRegion: (roi: PixelRoi) => void;
  onClearRegion: () => void;
}) {
  // selectMode 是查看器内部的临时交互态（是否进入框选），只有查看器关心，故本地持有。
  const [selectMode, setSelectMode] = useState(false);
  // 视图变换：scale + 平移（屏幕像素）。
  const [scale, setScale] = useState(1);
  const [tx, setTx] = useState(0);
  const [ty, setTy] = useState(0);
  // 鼠标在「图像内容盒」中的相对位置（0..1），用于底部读数。
  const [relPos, setRelPos] = useState<[number, number] | null>(null);

  const frameRef = useRef<HTMLDivElement>(null); // 外层裁剪框（固定，框选坐标系基准）
  const contentRef = useRef<HTMLDivElement>(null); // 被 transform 的内容盒（含图像）
  const panRef = useRef<{ x: number; y: number; tx: number; ty: number } | null>(null);
  const drawRef = useRef<{ x0: number; y0: number } | null>(null);
  const [drawRect, setDrawRect] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);

  // 影像切换（图层集合变化）时复位视图，避免上一张的缩放/平移残留。
  const layerKey = layers.map((l) => l.id).join("|");
  useEffect(() => {
    setScale(1);
    setTx(0);
    setTy(0);
  }, [layerKey]);

  // 框选坐标 = 鼠标点相对「图像内容盒」的归一化位置。
  // 内容盒经过 translate(tx,ty) + scale(scale)，故反算：rel = (mouse - frameCenter - t) / (size*scale) + 0.5
  const toRel = useCallback((clientX: number, clientY: number): [number, number] | null => {
    const frame = frameRef.current;
    const content = contentRef.current;
    if (!frame || !content) return null;
    const fRect = frame.getBoundingClientRect();
    // content 盒未缩放时的尺寸（offsetWidth/Height 不含 transform）。
    const w = content.offsetWidth * scale;
    const h = content.offsetHeight * scale;
    if (w <= 0 || h <= 0) return null;
    // 内容盒中心在 frame 内的位置 = frame 中心 + 平移。
    const cx = fRect.width / 2 + tx;
    const cy = fRect.height / 2 + ty;
    const left = cx - w / 2;
    const top = cy - h / 2;
    const relX = (clientX - fRect.left - left) / w;
    const relY = (clientY - fRect.top - top) / h;
    return [relX, relY];
  }, [scale, tx, ty]);

  const onWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    setScale((s) => {
      const next = e.deltaY < 0 ? s * 1.12 : s / 1.12;
      return Math.min(MAX_SCALE, Math.max(MIN_SCALE, next));
    });
  }, []);

  const onPointerDown = (e: React.PointerEvent) => {
    (e.target as Element).setPointerCapture?.(e.pointerId);
    if (selectMode) {
      const rel = toRel(e.clientX, e.clientY);
      if (!rel) return;
      drawRef.current = { x0: rel[0], y0: rel[1] };
      setDrawRect({ x0: rel[0], y0: rel[1], x1: rel[0], y1: rel[1] });
    } else {
      panRef.current = { x: e.clientX, y: e.clientY, tx, ty };
    }
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const rel = toRel(e.clientX, e.clientY);
    if (rel) setRelPos(rel);
    if (selectMode && drawRef.current) {
      if (!rel) return;
      setDrawRect({ x0: drawRef.current.x0, y0: drawRef.current.y0, x1: rel[0], y1: rel[1] });
    } else if (panRef.current) {
      setTx(panRef.current.tx + (e.clientX - panRef.current.x));
      setTy(panRef.current.ty + (e.clientY - panRef.current.y));
    }
  };

  const onPointerUp = () => {
    if (selectMode && drawRef.current && drawRect) {
      const next = pixelRoiFromCorners(
        [drawRect.x0, drawRect.y0],
        [drawRect.x1, drawRect.y1],
      );
      if (!isDegenerateRoi(next)) {
        onSelectRegion(next);
        setSelectMode(false); // 框选完成自动退出框选态，回到平移浏览
      }
      setDrawRect(null);
    }
    drawRef.current = null;
    panRef.current = null;
  };

  // 已确认 ROI 的可视矩形：相对内容盒定位（用百分比，随内容盒一起 transform）。
  const roiBox = roi
    ? {
        left: `${roi.rel[0] * 100}%`,
        top: `${roi.rel[1] * 100}%`,
        width: `${(roi.rel[2] - roi.rel[0]) * 100}%`,
        height: `${(roi.rel[3] - roi.rel[1]) * 100}%`,
      }
    : null;

  // 拖拽中的临时矩形：相对 frame 定位需换算回屏幕——简化为相对内容盒百分比一致呈现。
  const liveBox = drawRect
    ? {
        left: `${Math.min(drawRect.x0, drawRect.x1) * 100}%`,
        top: `${Math.min(drawRect.y0, drawRect.y1) * 100}%`,
        width: `${Math.abs(drawRect.x1 - drawRect.x0) * 100}%`,
        height: `${Math.abs(drawRect.y1 - drawRect.y0) * 100}%`,
      }
    : null;

  return (
    <div className="absolute inset-0 z-10 overflow-hidden">
      <div
        ref={frameRef}
        className={`absolute inset-0 ${selectMode ? "cursor-crosshair" : "cursor-grab active:cursor-grabbing"}`}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={() => setRelPos(null)}
      >
        <div className="absolute inset-0 flex items-center justify-center">
          <div
            ref={contentRef}
            className="relative"
            style={{
              transform: `translate(${tx}px, ${ty}px) scale(${scale})`,
              transition: panRef.current || drawRef.current ? "none" : "transform 0.12s ease-out",
            }}
          >
            {[...layers].reverse().map((l, i) => (
              <img
                key={l.id}
                src={absoluteUrl(l.url!)}
                alt={l.name}
                draggable={false}
                className={
                  i === 0
                    ? "max-h-[82vh] max-w-[82vw] select-none rounded-lg object-contain shadow-2xl"
                    : "absolute inset-0 size-full select-none rounded-lg object-contain"
                }
                style={{ opacity: l.opacity }}
              />
            ))}
            {/* ROI 矩形（已确认 + 拖拽中），相对内容盒，随缩放平移贴合 */}
            {roiBox && (
              <div
                className="pointer-events-none absolute rounded-sm border-2 border-primary bg-primary/15"
                style={roiBox}
              />
            )}
            {liveBox && (
              <div
                className="pointer-events-none absolute rounded-sm border-2 border-dashed border-primary bg-primary/10"
                style={liveBox}
              />
            )}
          </div>
        </div>
      </div>

      {/* 像素相对位置读数（替代 geo 的 LAT/LNG） */}
      <div className="pointer-events-none absolute left-1/2 top-[116px] -translate-x-1/2">
        <div className="flex items-center gap-2 rounded-full border border-border bg-card/80 px-3.5 py-1.5 font-mono text-[11px] tracking-tight text-foreground backdrop-blur-md">
          <span className="size-1.5 rounded-full bg-primary" />
          <span className="text-muted-foreground">无地理坐标</span>
          {relPos && relPos[0] >= 0 && relPos[0] <= 1 && relPos[1] >= 0 && relPos[1] <= 1 ? (
            <>
              <span className="text-foreground/30">·</span>
              <span className="text-muted-foreground">X</span>
              <span className="tabular-nums">{Math.round(relPos[0] * 100)}%</span>
              <span className="text-muted-foreground">Y</span>
              <span className="tabular-nums">{Math.round(relPos[1] * 100)}%</span>
            </>
          ) : (
            <>
              <span className="text-foreground/30">·</span>
              <span className="text-muted-foreground">按影像内相对位置定位</span>
            </>
          )}
        </div>
      </div>

      {/* 底部控制簇：缩放 / 复位 / 框选 */}
      <div className="absolute bottom-4 left-1/2 flex -translate-x-1/2 items-center gap-2">
        <div className="flex items-center overflow-hidden rounded-full border border-border bg-card/80 backdrop-blur-md">
          <button
            onClick={() => setScale((s) => Math.max(MIN_SCALE, s / 1.2))}
            className="grid size-8 place-items-center text-foreground transition-colors hover:text-primary"
            title="缩小"
          >
            <Minus className="size-3.5" />
          </button>
          <span className="h-4 w-px bg-border" />
          <button
            onClick={() => setScale((s) => Math.min(MAX_SCALE, s * 1.2))}
            className="grid size-8 place-items-center text-foreground transition-colors hover:text-primary"
            title="放大"
          >
            <Plus className="size-3.5" />
          </button>
        </div>

        <button
          onClick={() => {
            setScale(1);
            setTx(0);
            setTy(0);
          }}
          className="flex items-center gap-1.5 rounded-full border border-border bg-card/80 px-3 py-1.5 font-mono text-[11px] text-foreground backdrop-blur-md transition-colors hover:border-primary/50 hover:text-primary"
        >
          <Crosshair className="size-3.5" />
          复位
        </button>

        <button
          onClick={() => setSelectMode((v) => !v)}
          className={`flex items-center gap-1.5 rounded-full border px-3 py-1.5 font-mono text-[11px] backdrop-blur-md transition-colors ${
            selectMode
              ? "border-primary/50 bg-primary/10 text-primary"
              : "border-border bg-card/80 text-foreground hover:text-primary"
          }`}
          title="框选分析聚焦区"
        >
          <SquareDashedMousePointer className="size-3.5" />
          {selectMode ? "框选中" : "框选"}
        </button>

        {roi && (
          <button
            onClick={onClearRegion}
            className="flex items-center gap-1.5 rounded-full border border-border bg-card/80 px-3 py-1.5 font-mono text-[11px] text-foreground backdrop-blur-md transition-colors hover:border-destructive/50 hover:text-destructive"
          >
            <X className="size-3.5" />
            清除选区
          </button>
        )}
      </div>
    </div>
  );
}

import { useRef, type FormEvent, type KeyboardEvent, type RefObject } from "react";
import { ArrowUp, Loader2, Paperclip } from "lucide-react";
import { useImageryUpload, type ImageryMeta } from "../hooks/useImageryUpload";
import type { GeospatialResult } from "../types";

type ChatComposerProps = {
  endpoint: string;
  input: string;
  loading: boolean;
  textareaRef: RefObject<HTMLTextAreaElement>;
  onInputChange: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  onImageryUploaded?: (msg: string, result?: GeospatialResult) => void;
};

export function ChatComposer({
  endpoint,
  input,
  loading,
  textareaRef,
  onInputChange,
  onSubmit,
  onKeyDown,
  onImageryUploaded,
}: ChatComposerProps) {
  const isComposingRef = useRef(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const imagery = useImageryUpload(endpoint);

  function handleTextareaKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      isComposingRef.current ||
      event.nativeEvent.isComposing ||
      event.keyCode === 229
    ) {
      return;
    }
    onKeyDown(event);
  }

  async function handleFileSelect() {
    const file = fileInputRef.current?.files?.[0];
    if (!file) return;
    const meta = await imagery.upload(file);
    if (meta && onImageryUploaded) {
      onImageryUploaded(
        `已上传影像 ${meta.filename} (${meta.band_count}波段, ${meta.width}x${meta.height}px, ID: ${meta.imagery_id})`,
        buildPreviewResult(meta),
      );
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  return (
    <div className="border-t border-border bg-background">
      <form onSubmit={onSubmit} className="max-w-3xl mx-auto px-6 md:px-10 py-5">
        <div className="flex items-end gap-3 border border-border rounded-2xl bg-card px-4 py-3 focus-within:border-foreground/40 transition-colors">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={loading || imagery.uploading}
            className="shrink-0 inline-flex items-center justify-center size-8 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/50 disabled:opacity-30 transition-colors"
            aria-label="上传影像"
            title="上传 GeoTIFF 影像"
          >
            <Paperclip className="size-4" />
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".tif,.tiff"
            className="hidden"
            onChange={handleFileSelect}
          />
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => onInputChange(e.target.value)}
            onCompositionStart={() => {
              isComposingRef.current = true;
            }}
            onCompositionEnd={() => {
              isComposingRef.current = false;
            }}
            onKeyDown={handleTextareaKeyDown}
            placeholder="说点什么... (Shift + Enter 换行)"
            rows={1}
            disabled={loading}
            className="flex-1 resize-none bg-transparent outline-none text-[15px] leading-relaxed placeholder:text-muted-foreground/70 disabled:opacity-60"
            style={{ minHeight: 24 }}
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="shrink-0 inline-flex items-center justify-center size-9 rounded-full bg-foreground text-background disabled:opacity-30 disabled:cursor-not-allowed hover:bg-foreground/90 transition-colors"
            aria-label="发送"
          >
            {loading ? <Loader2 className="size-4 animate-spin" /> : <ArrowUp className="size-4" />}
          </button>
        </div>
        {imagery.uploading && (
          <p className="mt-1 text-xs text-muted-foreground">正在上传影像...</p>
        )}
        {imagery.error && (
          <p className="mt-1 text-xs text-red-400">{imagery.error}</p>
        )}
        <p
          className="mt-2 text-[10px] tracking-[0.16em] uppercase text-muted-foreground"
          style={{ fontFamily: "'JetBrains Mono', monospace" }}
        >
          POST {endpoint.replace(/^https?:\/\//, "")}
        </p>
      </form>
    </div>
  );
}

function buildPreviewResult(meta: ImageryMeta): GeospatialResult {
  return {
    type: "preview",
    imagery_id: meta.imagery_id,
    result_url: meta.preview_url ?? `/api/imagery/${meta.imagery_id}/results/preview.png`,
    bounds: normalizeBounds(meta.bounds),
  };
}

function normalizeBounds(bounds: number[] | null): [number, number, number, number] | null {
  if (!Array.isArray(bounds) || bounds.length !== 4) return null;
  const [west, south, east, north] = bounds;
  if (![west, south, east, north].every(Number.isFinite)) return null;
  return [west, south, east, north];
}

import { useRef, type FormEvent, type KeyboardEvent, type RefObject } from "react";
import { ArrowUp, Loader2 } from "lucide-react";

type ChatComposerProps = {
  endpoint: string;
  input: string;
  loading: boolean;
  textareaRef: RefObject<HTMLTextAreaElement>;
  onInputChange: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
};

export function ChatComposer({
  endpoint,
  input,
  loading,
  textareaRef,
  onInputChange,
  onSubmit,
  onKeyDown,
}: ChatComposerProps) {
  const isComposingRef = useRef(false);

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

  return (
    <div className="border-t border-border bg-background">
      <form onSubmit={onSubmit} className="max-w-3xl mx-auto px-6 md:px-10 py-5">
        <div className="flex items-end gap-3 border border-border rounded-2xl bg-card px-4 py-3 focus-within:border-foreground/40 transition-colors">
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
            placeholder="说点什么…  (Shift + Enter 换行)"
            rows={1}
            disabled={loading}
            className="flex-1 resize-none bg-transparent outline-none text-[15px] leading-relaxed placeholder:text-muted-foreground/70 disabled:opacity-60"
            style={{ minHeight: 24 }}
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="shrink-0 inline-flex items-center justify-center size-9 rounded-full bg-foreground text-background disabled:opacity-30 disabled:cursor-not-allowed hover:bg-foreground/90 transition-colors"
            aria-label="send"
          >
            {loading ? <Loader2 className="size-4 animate-spin" /> : <ArrowUp className="size-4" />}
          </button>
        </div>
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

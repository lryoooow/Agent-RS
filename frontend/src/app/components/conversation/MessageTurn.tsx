import { AlertTriangle } from "lucide-react";
import type { ChatTurn } from "../../types";
import { AnalysisStatusLine } from "./AnalysisStatusLine";

export function MessageTurn({ turn }: { turn: ChatTurn }) {
  const isUser = turn.role === "user";
  const showAnalysis = !isUser && turn.analysisStatus != null && !turn.content;

  if (turn.error) return <ErrorTurn turn={turn} />;

  return (
    <div className={`flex flex-col gap-2 ${isUser ? "items-end" : "items-start"}`}>
      <div
        className="text-[10px] tracking-[0.2em] uppercase text-muted-foreground"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        {isUser ? "you" : "assistant"}
      </div>
      {showAnalysis && (
        <AnalysisStatusLine status={turn.analysisStatus!} label={turn.analysisLabel} />
      )}
      {(isUser || turn.content) && (
        <div
          className={`max-w-[88%] whitespace-pre-wrap break-words leading-relaxed ${
            isUser ? "bg-foreground text-background rounded-2xl rounded-tr-sm px-4 py-3" : "text-foreground"
          }`}
        >
          {turn.content}
        </div>
      )}
      {!isUser && (turn.model || turn.usage) && <MessageMeta turn={turn} />}
    </div>
  );
}

function ErrorTurn({ turn }: { turn: ChatTurn }) {
  return (
    <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4">
      <div
        className="flex items-center gap-2 text-[10px] tracking-[0.18em] uppercase text-destructive"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        <AlertTriangle className="size-3.5" /> request failed
      </div>
      <p
        className="mt-2 text-sm whitespace-pre-wrap break-words"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        {turn.content}
      </p>
    </div>
  );
}

function MessageMeta({ turn }: { turn: ChatTurn }) {
  return (
    <div
      className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] tracking-[0.14em] uppercase text-muted-foreground pt-1"
      style={{ fontFamily: "'JetBrains Mono', monospace" }}
    >
      {turn.model && <span>model · {turn.model}</span>}
      {turn.provider && <span>provider · {turn.provider}</span>}
      {turn.usage?.total_tokens != null && (
        <span>
          tokens · {turn.usage.input_tokens ?? "?"}↑ {turn.usage.output_tokens ?? "?"}↓{" "}
          {turn.usage.total_tokens}∑
        </span>
      )}
      {turn.finishReason && <span>finish · {turn.finishReason}</span>}
      {turn.retrievedChunks != null && turn.retrievedChunks > 0 && (
        <span>参考了 {turn.retrievedChunks} 段文档</span>
      )}
      {turn.ragTrace && (
        <details className="basis-full pt-1 normal-case tracking-normal">
          <summary className="cursor-pointer">RAG trace</summary>
          <pre className="mt-1 max-w-[88vw] overflow-x-auto text-[10px] leading-relaxed">
            {JSON.stringify(turn.ragTrace, null, 2)}
          </pre>
        </details>
      )}
      {turn.agentTrace && (
        <details className="basis-full pt-1 normal-case tracking-normal">
          <summary className="cursor-pointer">Agent trace</summary>
          <pre className="mt-1 max-w-[88vw] overflow-x-auto text-[10px] leading-relaxed">
            {JSON.stringify(turn.agentTrace, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}

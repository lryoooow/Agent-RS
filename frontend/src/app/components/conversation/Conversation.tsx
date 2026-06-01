import type { RefObject } from "react";
import type { ChatTurn } from "../../types";
import { EmptyState } from "./EmptyState";
import { MessageTurn } from "./MessageTurn";
import { ThinkingIndicator } from "./ThinkingIndicator";

type ConversationProps = {
  turns: ChatTurn[];
  loading: boolean;
  activeStream: boolean;
  scrollRef: RefObject<HTMLDivElement>;
  onPickSuggestion: (value: string) => void;
};

export function Conversation({
  turns,
  loading,
  activeStream,
  scrollRef,
  onPickSuggestion,
}: ConversationProps) {
  const isEmpty = turns.length === 0;

  return (
    <div ref={scrollRef} className="flex-1 overflow-y-auto">
      <div className="max-w-3xl mx-auto px-6 md:px-10 py-10">
        {isEmpty ? (
          <EmptyState onPick={onPickSuggestion} />
        ) : (
          <div className="flex flex-col gap-8">
            {turns.map((turn) => (
              <MessageTurn key={turn.id} turn={turn} />
            ))}
            {loading && !activeStream && <ThinkingIndicator />}
          </div>
        )}
      </div>
    </div>
  );
}

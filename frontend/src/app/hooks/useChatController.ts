import { useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { postChat } from "../lib/chat-api";
import {
  appendAssistantResponse,
  applyRequestError,
  createStreamHandlers,
} from "../lib/chat-events";
import { buildChatRequestBody } from "../lib/chat-request";
import { readStreamResponse } from "../lib/sse";
import { toModelHistory, uid } from "../lib/turns";
import type {
  ChatResponse,
  ChatTurn,
  ProviderConfigBody,
} from "../types";

type ChatControllerSettings = {
  endpoint: string;
  model: string;
  systemPrompt: string;
  streamEnabled: boolean;
  buildProviderConfig: () => ProviderConfigBody;
};

export function useChatController({
  endpoint,
  model,
  systemPrompt,
  streamEnabled,
  buildProviderConfig,
}: ChatControllerSettings) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [activeStream, setActiveStream] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  async function sendMessage(text: string) {
    const trimmed = text.trim();
    if (!trimmed || loading) return;

    const userTurn: ChatTurn = { id: uid(), role: "user", content: trimmed };
    const assistantId = uid();
    const shouldStream = streamEnabled;
    const body = buildChatRequestBody({
      messages: toModelHistory(turns, trimmed),
      model,
      systemPrompt,
      stream: shouldStream,
      providerConfig: buildProviderConfig(),
    });

    if (shouldStream) {
      setTurns((prev) => [...prev, userTurn, { id: assistantId, role: "assistant", content: "" }]);
    } else {
      setTurns((prev) => [...prev, userTurn]);
    }
    setInput("");
    setLoading(true);
    setActiveStream(shouldStream);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await postChat(endpoint, body, controller.signal);

      if (shouldStream) {
        await readStreamResponse(res, createStreamHandlers(setTurns, assistantId));
        return;
      }

      const data = (await res.json()) as ChatResponse;
      appendAssistantResponse(setTurns, data);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      applyRequestError(setTurns, assistantId, shouldStream, err);
    } finally {
      abortRef.current = null;
      setActiveStream(false);
      setLoading(false);
    }
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    sendMessage(input);
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  }

  function resetConversation() {
    abortRef.current?.abort();
    setActiveStream(false);
    setTurns([]);
  }

  return {
    turns,
    input,
    loading,
    activeStream,
    setInput,
    sendMessage,
    handleSubmit,
    handleKeyDown,
    resetConversation,
  };
}

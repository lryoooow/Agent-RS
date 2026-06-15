import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
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
  GeospatialResult,
  ProviderConfig,
} from "../types";

const CONVERSATION_STORAGE_KEY = "agent-rs.conversationId";
const LEGACY_CONVERSATION_STORAGE_KEY = "chatbot.conversationId";

type ChatControllerSettings = {
  endpoint: string;
  systemPrompt: string;
  streamEnabled: boolean;
  useRag: boolean;
  // 模型直连兜底配置：仅当后端未配置 API Key 时由 useSettings 计算为非空，env 优先。
  providerConfig?: ProviderConfig | null;
};

export function useChatController({
  endpoint,
  systemPrompt,
  streamEnabled,
  useRag,
  providerConfig,
}: ChatControllerSettings) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [activeStream, setActiveStream] = useState(false);
  const [conversationId, setConversationIdState] = useState<string | null>(() =>
    window.localStorage.getItem(CONVERSATION_STORAGE_KEY) ??
    window.localStorage.getItem(LEGACY_CONVERSATION_STORAGE_KEY),
  );
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  function setConversationId(nextConversationId: string | null) {
    setConversationIdState(nextConversationId);
    if (nextConversationId) {
      window.localStorage.setItem(CONVERSATION_STORAGE_KEY, nextConversationId);
      window.localStorage.removeItem(LEGACY_CONVERSATION_STORAGE_KEY);
      return;
    }
    window.localStorage.removeItem(CONVERSATION_STORAGE_KEY);
    window.localStorage.removeItem(LEGACY_CONVERSATION_STORAGE_KEY);
  }

  async function sendMessage(text: string) {
    const trimmed = text.trim();
    if (!trimmed || loading) return;

    const userTurn: ChatTurn = { id: uid(), role: "user", content: trimmed };
    const assistantId = uid();
    const shouldStream = streamEnabled;
    const requestMessages = conversationId
      ? [...latestGeospatialContext(turns), { role: "user" as const, content: trimmed }]
      : toModelHistory(turns, trimmed);
    const body = buildChatRequestBody({
      messages: requestMessages,
      systemPrompt,
      stream: shouldStream,
      conversationId,
      useRag,
      providerConfig,
    });

    if (shouldStream) {
      setTurns((prev) => [
        ...prev,
        userTurn,
        {
          id: assistantId,
          role: "assistant",
          content: "",
          analysisStatus: "analyzing",
          analysisLabel: "正在解析问题...",
        },
      ]);
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
        await readStreamResponse(res, createStreamHandlers(setTurns, assistantId, setConversationId));
        return;
      }

      const data = (await res.json()) as ChatResponse;
      if (data.conversation_id) setConversationId(data.conversation_id);
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
    setConversationId(null);
  }

  function addSystemNote(content: string) {
    setTurns((prev) => [...prev, { id: uid(), role: "system", content }]);
  }

  function addGeospatialResult(content: string, geospatialResult: GeospatialResult) {
    setTurns((prev) => [
      ...prev,
      { id: uid(), role: "system", content, geospatialResult },
    ]);
  }

  return {
    turns,
    input,
    loading,
    activeStream,
    conversationId,
    setInput,
    setConversationId,
    sendMessage,
    handleSubmit,
    handleKeyDown,
    resetConversation,
    addSystemNote,
    addGeospatialResult,
  };
}

function latestGeospatialContext(turns: ChatTurn[]) {
  const turn = [...turns].reverse().find((item) => item.geospatialResult);
  if (!turn?.geospatialResult) return [];
  const result = turn.geospatialResult;
  return [
    {
      role: "system" as const,
      content: `当前上传影像：ID=${result.imagery_id}，图层类型=${result.type}。如用户要求计算 NDVI 或其他遥感工具，优先使用该 imagery_id。`,
    },
  ];
}

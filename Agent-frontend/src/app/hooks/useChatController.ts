import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { postChat } from "../lib/chat-api";
import {
  appendAssistantResponse,
  applyRequestError,
  createStreamHandlers,
  parseGeospatialResult,
  parseToolResult,
} from "../lib/chat-events";
import { buildChatRequestBody } from "../lib/chat-request";
import { createReport } from "../lib/reports-api";
import { readStreamResponse } from "../lib/sse";
import { toModelHistory, uid } from "../lib/turns";
import { type Roi } from "../lib/roi";
import type {
  ChatResponse,
  ChatTurn,
  GeospatialResult,
  GeospatialSceneSearchResult,
  ProviderConfig,
  MapContext,
  ThinkingStrength,
} from "../types";

type ChatControllerSettings = {
  endpoint: string;
  systemPrompt: string;
  streamEnabled: boolean;
  useRag: boolean;
  model?: string | null;
  providerConfig?: ProviderConfig | null;
  roi?: Roi | null;
  analysisSource?: "current_map" | "selected_imagery";
  getMapContext?: () => MapContext | null;
  thinkingStrength?: ThinkingStrength | null;
  tavilyApiKey?: string | null;
  onMapControl?: (target: Record<string, unknown>) => void;
};

export function useChatController({
  endpoint,
  systemPrompt,
  streamEnabled,
  useRag,
  model,
  providerConfig,
  roi,
  analysisSource,
  getMapContext,
  thinkingStrength,
  tavilyApiKey,
  onMapControl,
}: ChatControllerSettings) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const turnsRef = useRef(turns);
  turnsRef.current = turns;
  const [activeImageryId, setActiveImageryIdState] = useState<string | null>(null);
  const activeImageryRef = useRef<string | null>(null);
  const requestEpoch = useRef(0);
  const busyRef = useRef(false);
  function selectImagery(id: string | null) {
    activeImageryRef.current = id;
    setActiveImageryIdState(id);
  }
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [activeStream, setActiveStream] = useState(false);
  const [reportPending, setReportPending] = useState(false);
  // 会话 id 不再从 localStorage 恢复：欢迎页/刷新一律视为新对话（初始 null）。
  // 「接着上次聊」只通过历史列表显式 loadConversation 进入，避免旧 id 隐式泄漏到新对话。
  const [conversationId, setConversationIdState] = useState<string | null>(null);
  // 用 ref 持有「发请求那一刻的真值」：resetConversation 后即便 setState 尚未重渲染、
  // sendMessage 拿到的是旧闭包，也能从 ref 读到已清空的 id，杜绝旧会话历史串联（stale closure 根因）。
  const conversationIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // 用 ref 持有最新 ROI，避免 sendMessage 闭包读到过期值（与 conversationId 同样的 stale closure 防护）。
  const roiRef = useRef<Roi | null>(roi ?? null);
  roiRef.current = roi ?? null;
  const analysisSourceRef = useRef(analysisSource);
  analysisSourceRef.current = analysisSource;

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  function setConversationId(nextConversationId: string | null) {
    conversationIdRef.current = nextConversationId;
    setConversationIdState(nextConversationId);
  }

  async function sendMessage(text: string) {
    const trimmed = text.trim();
    if (!trimmed || busyRef.current) return;
    busyRef.current = true;
    const epoch = ++requestEpoch.current;

    // 从 ref 读取「此刻」的会话 id，而非闭包里可能过期的 state：
    // startSession 先 resetConversation()（异步清空 state）再 setTimeout 调本函数，
    // 闭包捕获的 conversationId 仍是旧值，唯有 ref 已同步为 null。
    const activeConversationId = conversationIdRef.current;
    const userTurn: ChatTurn = { id: uid(), role: "user", content: trimmed };
    const assistantId = uid();
    const shouldStream = streamEnabled;
    const baseMessages = activeConversationId
      ? [{ role: "user" as const, content: trimmed }]
      : toModelHistory(turnsRef.current, trimmed);
    // 当前影像与 ROI 通过结构化字段传输，由服务端验证后加入上下文。
    const activeRoi = roiRef.current;
    const requestMessages = baseMessages;

    // 提取地图上下文（如果提供了 getMapContext 函数）
    const metadata: Record<string, unknown> = {};
    const activeImageryId = activeImageryRef.current;
    metadata.active_imagery_id = activeImageryId;
    if (activeRoi && analysisSourceRef.current) metadata.analysis_source = analysisSourceRef.current;
    if (getMapContext) {
      const mapCtx = getMapContext();
      if (mapCtx) {
        metadata.map_context = {
          ...mapCtx,
          annotations: mapCtx.annotations?.slice(0, 100),
        };
      }
    }

    const body = buildChatRequestBody({
      messages: requestMessages,
      systemPrompt,
      stream: shouldStream,
      conversationId: activeConversationId,
      useRag,
      model,
      providerConfig,
      metadata: Object.keys(metadata).length > 0 ? metadata : undefined,
      thinkingStrength,
      tavilyApiKey,
      analysisRoi: activeRoi,
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
          analysisLabel: "正在思考中...",
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
      const res = await postChat(body, controller.signal);

      if (shouldStream) {
        await readStreamResponse(
          res,
          createStreamHandlers(
            (update) => { if (epoch === requestEpoch.current) setTurns(update); },
            assistantId,
            (id) => { if (epoch === requestEpoch.current) setConversationId(id); },
            (target) => { if (epoch === requestEpoch.current) onMapControl?.(target); },
          ),
        );
        return;
      }

      const data = (await res.json()) as ChatResponse;
      if (epoch !== requestEpoch.current) return;
      if (data.conversation_id) setConversationId(data.conversation_id);
      appendAssistantResponse(setTurns, data);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      if (epoch === requestEpoch.current) applyRequestError(setTurns, assistantId, shouldStream, err);
    } finally {
      if (epoch === requestEpoch.current) {
        abortRef.current = null;
        busyRef.current = false;
        setActiveStream(false);
        setLoading(false);
      }
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
    ++requestEpoch.current;
    busyRef.current = false;
    setLoading(false);
    turnsRef.current = [];
    setActiveStream(false);
    setTurns([]);
    setConversationId(null);
  }

  function addSystemNote(content: string) {
    setTurns((prev) => [...prev, { id: uid(), role: "system", content }]);
  }

  function addGeospatialResult(content: string, geospatialResult: GeospatialResult) {
    if (geospatialResult.type === "preview") selectImagery(geospatialResult.imagery_id);
    const next: ChatTurn[] = [...turnsRef.current, { id: uid(), role: geospatialResult.type === "report" ? "assistant" : "system", content, geospatialResult }];
    turnsRef.current = next;
    setTurns(next);
  }

  // 结果卡片"生成 Word 报告"按钮：调后端 /reports（服务端读本对话持久化结果），
  // 成功则追加一张可下载的报告卡片；失败给一条 system 提示。生成中用 reportPending 防重复点击。
  async function generateReport(imageryId?: string) {
    const activeConversationId = conversationIdRef.current;
    if (!activeConversationId) {
      addSystemNote("当前还没有可生成报告的对话上下文。");
      return;
    }
    if (reportPending) return;
    const epoch = requestEpoch.current;
    setReportPending(true);
    try {
      const artifact = await createReport({
        conversationId: activeConversationId,
        imageryId,
      });
      if (epoch !== requestEpoch.current) return;
      addGeospatialResult("分析报告已生成", {
        type: "report",
        imagery_id: artifact.imagery_id,
        filename: artifact.filename,
        download_url: artifact.download_url,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (epoch === requestEpoch.current) addSystemNote(`报告生成失败：${message}`);
    } finally {
      setReportPending(false);
    }
  }

  // 载入历史会话：把后端消息映射成 ChatTurn 回填，并锁定该 conversationId。
  // 关键：从每条消息的 metadata 还原已持久化的 geospatial_result/tool_result，
  // 让分析结果卡片在重开会话时重现（根治"重载后只剩文字、卡片丢失"）。
  function loadConversation(
    nextConversationId: string,
    messages: { role: string; content: string; metadata?: Record<string, unknown> | null }[],
  ) {
    abortRef.current?.abort();
    ++requestEpoch.current;
    busyRef.current = false;
    setActiveStream(false);
    setLoading(false);
    const restored = messages.map((m) => {
        const meta = m.metadata ?? undefined;
        const geospatialResult = meta ? parseGeospatialResult(meta.geospatial_result) : undefined;
        const toolResult = meta ? parseToolResult(meta.tool_result) : undefined;
        return {
          id: uid(),
          role: (m.role === "assistant" || m.role === "system" ? m.role : "user") as ChatTurn["role"],
          content: m.content,
          restored: true,
          geospatialResult,
          toolResult,
        };
      });
    turnsRef.current = restored;
    setTurns(restored);
    const lastSelection = [...messages].reverse().find((m) => "active_imagery_id" in (m.metadata ?? {}) || parseGeospatialResult(m.metadata?.geospatial_result)?.type === "preview");
    const previewSelection = lastSelection ? parseGeospatialResult(lastSelection.metadata?.geospatial_result) : undefined;
    const restoredSelection = lastSelection && "active_imagery_id" in (lastSelection.metadata ?? {})
      ? (typeof lastSelection.metadata?.active_imagery_id === "string" ? lastSelection.metadata.active_imagery_id : null)
      : previewSelection?.type === "preview" ? previewSelection.imagery_id : null;
    selectImagery(lastSelection ? restoredSelection : latestGeospatialContext(restored));
    setConversationId(nextConversationId);
  }

  return {
    turns,
    activeImageryId,
    selectImagery,
    input,
    loading,
    activeStream,
    reportPending,
    conversationId,
    setInput,
    sendMessage,
    handleSubmit,
    handleKeyDown,
    resetConversation,
    addSystemNote,
    addGeospatialResult,
    generateReport,
    loadConversation,
  };
}

function latestGeospatialContext(turns: ChatTurn[]) {
  // 影像检索卡片（scene_search）没有 imagery_id，不能当"当前影像"注入。
  const turn = [...turns].reverse().find(
    (item): item is ChatTurn & {
      geospatialResult: Exclude<GeospatialResult, GeospatialSceneSearchResult>;
    } => !!item.geospatialResult && item.geospatialResult.type !== "scene_search" && item.geospatialResult.type !== "report",
  );
  return turn?.geospatialResult.imagery_id ?? null;
}

import { useMemo, useRef, useState } from "react";
import { AnimatePresence } from "motion/react";
import { MapView } from "./components/MapView";
import { AgentChat } from "./components/AgentChat";
import { RightPanel } from "./components/RightPanel";
import { WelcomeScreen } from "./components/WelcomeScreen";
import { TopBar } from "./components/TopBar";
import { TaskBar } from "./components/TaskBar";
import { ToolsPage } from "./components/ToolsPage";
import { DataPanel } from "./components/DataPanel";
import { TaskQueuePanel } from "./components/TaskQueuePanel";
import { AnalysisReportPanel } from "./components/AnalysisReportPanel";
import { AuthGate } from "./components/AuthGate";
import { SplashScreen } from "./components/SplashScreen";
import { useSettings } from "./hooks/useSettings";
import { useChatController } from "./hooks/useChatController";
import { useImageryUpload } from "./hooks/useImageryUpload";
import { useAuth } from "./hooks/useAuth";
import { layersFromTurns } from "./lib/layers";
import { tasksFromTurns } from "./lib/tasks";
import { reportsFromTurns } from "./lib/reports";
import { resolveAppGate } from "./lib/app-gate";
import type { GeospatialResult } from "./types";
import type { Roi } from "./lib/roi";

export default function App() {
  const settings = useSettings();
  const auth = useAuth(settings.endpoint);
  // 框选的分析聚焦区（ROI）：geo（经纬度 bbox）或 pixel（影像内相对 0..1）。
  // 由 MapView/ImageViewer 上报，注入下一轮对话作为「解读聚焦提示」（工具仍全图计算）。
  const [roi, setRoi] = useState<Roi | null>(null);
  const chat = useChatController({
    endpoint: settings.endpoint,
    systemPrompt: settings.systemPrompt,
    streamEnabled: settings.streamEnabled,
    useRag: settings.useRag,
    model: settings.model,
    providerConfig: settings.providerConfig,
    roi,
  });
  const imagery = useImageryUpload(settings.endpoint);

  const [view, setView] = useState<"welcome" | "chat">("welcome");
  const [toolsOpen, setToolsOpen] = useState(false);
  const [dataOpen, setDataOpen] = useState(false);
  const [tasksOpen, setTasksOpen] = useState(false);
  const [reportsOpen, setReportsOpen] = useState(false);
  // 图层显隐/透明度的本地覆盖（按 layer id）；图层本体由真实 geospatialResults 派生。
  const [layerOverrides, setLayerOverrides] = useState<
    Record<string, { visible?: boolean; opacity?: number; removed?: boolean }>
  >({});
  const fileRef = useRef<HTMLInputElement>(null);

  // 由对话中的真实 geospatial 结果派生图层视图，叠加本地显隐/透明度覆盖。
  const layers = useMemo(
    () => layersFromTurns(chat.turns, layerOverrides),
    [chat.turns, layerOverrides],
  );
  // 任务队列 / 分析报告均为对话 turns 的不同投影：前者来自 agentTrace 执行轨迹，后者来自真实结果。
  const tasks = useMemo(
    () => tasksFromTurns(chat.turns, chat.activeStream ? chat.turns[chat.turns.length - 1]?.id : null),
    [chat.turns, chat.activeStream],
  );
  const reports = useMemo(() => reportsFromTurns(chat.turns), [chat.turns]);
  const hasImagery = layers.some((l) => l.kind === "imagery");

  const triggerUpload = () => fileRef.current?.click();

  const handleFile = async (file: File | undefined) => {
    if (!file) return;
    const meta = await imagery.upload(file);
    if (!meta) {
      chat.addSystemNote(`影像上传失败：${imagery.error ?? "未知错误"}`);
      return;
    }
    const bounds =
      Array.isArray(meta.bounds) && meta.bounds.length === 4
        ? (meta.bounds as [number, number, number, number])
        : null;
    const preview: GeospatialResult = {
      type: "preview",
      imagery_id: meta.imagery_id,
      result_url: meta.preview_url ?? "",
      bounds,
    };
    // 把上传影像作为 preview 结果写入对话：① 地图据此出预览图层
    // ② useChatController 会把最近 imagery_id 注入后续请求 system message，由 LLM 决定调用何种工具。
    chat.addGeospatialResult(`影像已加载 · ${meta.filename}`, preview);
    setLayerOverrides({});
    setRoi(null);
  };

  // ---- session navigation -------------------------------------------------
  const startSession = (firstText?: string) => {
    chat.resetConversation();
    setLayerOverrides({});
    setRoi(null);
    setView("chat");
    if (firstText?.trim()) {
      setTimeout(() => chat.sendMessage(firstText), 0);
    }
  };

  const goBack = () => setView("welcome");

  const openConversation = (
    id: string,
    messages: { role: string; content: string; metadata?: Record<string, unknown> | null }[],
  ) => {
    chat.loadConversation(id, messages);
    setLayerOverrides({});
    setRoi(null);
    setDataOpen(false);
    setView("chat");
  };

  // 删除的恰好是当前激活会话：重置对话状态并清掉派生的图层/ROI（与 startSession 一致），
  // 防止下条消息仍带已删 id 发出导致后端静默新建空会话、上下文断裂。
  const handleActiveConversationDeleted = () => {
    chat.resetConversation();
    setLayerOverrides({});
    setRoi(null);
  };

  const launchModelPrompt = (prompt: string) => {
    if (chat.loading) return;
    setToolsOpen(false);
    if (view !== "chat") {
      setView("chat");
      setTimeout(() => chat.sendMessage(prompt), 0);
    } else {
      chat.sendMessage(prompt);
    }
  };

  // 应用门控（纯函数 resolveAppGate，可单测）：splash / login / app 三态。
  // splash 收敛"配置或会话尚未就绪"，绝不在未知态下先渲染主应用 —— 根治旧逻辑首屏闪烁。
  const gate = resolveAppGate({
    serverConfig: settings.serverConfig,
    authLoading: auth.loading,
    authed: auth.user?.authenticated === true,
  });
  if (gate === "splash") return <SplashScreen />;
  if (gate === "login") return <AuthGate auth={auth} />;

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-background text-foreground">
      <MapView
        layers={layers}
        roi={roi}
        onSelectRegion={setRoi}
        onClearRegion={() => setRoi(null)}
      />

      <TopBar settings={settings} auth={auth} />
      <TaskBar
        onOpenTools={() => setToolsOpen(true)}
        onOpenData={() => setDataOpen(true)}
        onOpenTasks={() => setTasksOpen(true)}
        onOpenReports={() => setReportsOpen(true)}
      />

      <DataPanel
        open={dataOpen}
        onOpenChange={setDataOpen}
        endpoint={settings.endpoint}
        onOpenConversation={openConversation}
        activeConversationId={chat.conversationId}
        onActiveConversationDeleted={handleActiveConversationDeleted}
      />

      <TaskQueuePanel open={tasksOpen} onOpenChange={setTasksOpen} tasks={tasks} />
      <AnalysisReportPanel open={reportsOpen} onOpenChange={setReportsOpen} entries={reports} />

      <input
        ref={fileRef}
        type="file"
        accept=".tif,.tiff"
        className="hidden"
        onChange={(e) => {
          handleFile(e.target.files?.[0]);
          e.target.value = "";
        }}
      />

      <AnimatePresence>
        {view === "chat" && (
          <RightPanel
            layers={layers}
            onToggle={(id) =>
              setLayerOverrides((prev) => ({
                ...prev,
                [id]: { ...prev[id], visible: !(prev[id]?.visible ?? true) },
              }))
            }
            onOpacity={(id, v) =>
              setLayerOverrides((prev) => ({ ...prev, [id]: { ...prev[id], opacity: v } }))
            }
            onRemove={(id) =>
              setLayerOverrides((prev) => ({ ...prev, [id]: { ...prev[id], removed: true } }))
            }
          />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {toolsOpen && <ToolsPage onClose={() => setToolsOpen(false)} onRun={launchModelPrompt} />}
      </AnimatePresence>

      <AnimatePresence mode="wait">
        {view === "welcome" ? (
          <WelcomeScreen key="welcome" onStart={startSession} />
        ) : (
          <AgentChat
            key="chat"
            turns={chat.turns}
            loading={chat.loading}
            activeStream={chat.activeStream}
            hasImagery={hasImagery}
            uploading={imagery.uploading}
            onSend={chat.sendMessage}
            onUpload={triggerUpload}
            onBack={goBack}
            onGenerateReport={chat.generateReport}
            reportPending={chat.reportPending}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

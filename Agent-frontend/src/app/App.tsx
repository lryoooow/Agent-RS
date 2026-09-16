import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence } from "motion/react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { MapView } from "./components/MapView";
import { AgentChat } from "./components/AgentChat";
import { RightPanel } from "./components/RightPanel";
import { WelcomeScreen } from "./components/WelcomeScreen";
import { TopBar } from "./components/TopBar";
import { TaskBar } from "./components/TaskBar";
import { ToolsPage } from "./components/ToolsPage";
import { DataPanel } from "./components/DataPanel";
import {
  SatelliteWorkspace,
  type SatelliteWorkspaceMode,
  type ScenePreviewRequest,
} from "./components/SatelliteWorkspace";
import { TaskQueuePanel } from "./components/TaskQueuePanel";
import { AnalysisReportPanel } from "./components/AnalysisReportPanel";
import { AuthGate } from "./components/AuthGate";
import { SplashScreen } from "./components/SplashScreen";
import { useSettings } from "./hooks/useSettings";
import { useChatController } from "./hooks/useChatController";
import { useImageryUpload, type ImageryMeta } from "./hooks/useImageryUpload";
import { useAuth } from "./hooks/useAuth";
import { layersFromTurns } from "./lib/layers";
import { tasksFromTurns } from "./lib/tasks";
import { reportsFromTurns } from "./lib/reports";
import { resolveAppGate } from "./lib/app-gate";
import { importScene } from "./lib/imagery-search-api";
import type { MapAnnotation, SceneCardInfo } from "./types";
import { roiIntersectsBounds, type Roi } from "./lib/roi";
import { getImagery, listAvailableImagery } from "./lib/imagery-api";
import { RoiAnalysisPanel, type RoiAnalysisSource } from "./components/RoiAnalysisPanel";

export default function App() {
  const settings = useSettings();
  const auth = useAuth(settings.endpoint);
  // 框选的分析聚焦区（ROI）：geo（经纬度 bbox）或 pixel（影像内相对 0..1）。
  // 由 MapView/ImageViewer 上报；地物分类会把它作为可信工具参数执行真正的 ROI 裁切。
  const [roi, setRoi] = useState<Roi | null>(null);
  const [roiSource, setRoiSource] = useState<RoiAnalysisSource>("current_map");
  const [searchRoiVersion, setSearchRoiVersion] = useState(0);
  // MapLibre 地图实例 ref，用于提取地图上下文（中心坐标、缩放级别）
  const mapRef = useRef<MapLibreMap | null>(null);
  // 地图标注数据（多边形、点、线段）
  const [annotations, setAnnotations] = useState<MapAnnotation[]>([]);

  const chat = useChatController({
    endpoint: settings.endpoint,
    systemPrompt: settings.systemPrompt,
    streamEnabled: settings.streamEnabled,
    useRag: settings.useRag,
    model: settings.model,
    providerConfig: settings.providerConfig,
    thinkingStrength: settings.thinkingStrength,
    tavilyApiKey: settings.tavilyApiKey,
    onMapControl: (target) => {
      // 对话控图：agent 调 look_at_location 后，命令式应用到地图（复用 MapView 既有 flyTo/fitBounds）。
      const map = mapRef.current;
      if (!map) return;
      const bbox = target.bbox as [[number, number], [number, number]] | undefined;
      const center = target.center as [number, number] | undefined;
      if (bbox) {
        map.fitBounds(bbox, { padding: 48, duration: 900 });
      } else if (center) {
        map.flyTo({ center, zoom: (target.zoom as number) ?? 11, duration: 900 });
      }
    },
    roi,
    analysisSource: roiSource,
    getMapContext: () => {
      const map = mapRef.current;
      if (!map) return null;
      const center = map.getCenter();
      const zoom = map.getZoom();
      return {
        center: [center.lng, center.lat],
        zoom: Math.round(zoom),
        annotations: annotations.length > 0 ? annotations : undefined,
      };
    },
  });
  const imagery = useImageryUpload(settings.endpoint);

  const [view, setView] = useState<"welcome" | "chat">("welcome");
  const [toolsOpen, setToolsOpen] = useState(false);
  const [dataOpen, setDataOpen] = useState(false);
  const [tasksOpen, setTasksOpen] = useState(false);
  const [reportsOpen, setReportsOpen] = useState(false);
  const [appSection, setAppSection] = useState<"workspace" | "satellite">("workspace");
  const [satelliteMode, setSatelliteMode] = useState<SatelliteWorkspaceMode>("orbit");
  const [scenePreviewRequest, setScenePreviewRequest] = useState<ScenePreviewRequest | null>(null);
  // 图层显隐/透明度的本地覆盖（按 layer id）；图层本体由真实 geospatialResults 派生。
  const [layerOverrides, setLayerOverrides] = useState<
    Record<string, { visible?: boolean; opacity?: number; removed?: boolean }>
  >({});
  const fileRef = useRef<HTMLInputElement>(null);

  const [availableImagery, setAvailableImagery] = useState<ImageryMeta[]>([]);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const activationVersion = useRef(0);
  const ownerRef = useRef(auth.user?.id);
  ownerRef.current = auth.user?.id;
  const selectedImage = availableImagery.find((m) => m.imagery_id === chat.activeImageryId);
  const roiMismatch = roiIntersectsBounds(roi, selectedImage?.bounds) === false;
  const rememberImage = (meta: ImageryMeta) => setAvailableImagery((prev) => [meta, ...prev.filter((m) => m.imagery_id !== meta.imagery_id)]);
  useEffect(() => {
    setAvailableImagery([]);
    setSelectionError(null);
    chat.resetConversation();
    chat.selectImagery(null);
    setLayerOverrides({});
    setRoi(null);
    setRoiSource("current_map");
    ++activationVersion.current;
    if (!auth.user?.authenticated) return;
    let alive = true;
    listAvailableImagery().then((items) => { if (alive) setAvailableImagery(items); })
      .catch((err) => { if (alive) setSelectionError(String(err)); });
    return () => { alive = false; };
  }, [auth.user?.authenticated, auth.user?.id]);
  useEffect(() => {
    if (!chat.activeImageryId || selectedImage) return;
    let alive = true;
    getImagery(chat.activeImageryId).then((meta) => { if (alive) rememberImage(meta); })
      .catch(() => { if (alive) setSelectionError("当前影像不可用，请重新选择或上传。"); });
    return () => { alive = false; };
  }, [chat.activeImageryId, selectedImage]);
  // Agent 导入产生的预览也进入同一个选择状态；报告或旧影像分析结果不会切换选择。
  const seenPreviews = useRef(new Set<string>());
  useEffect(() => {
    for (const turn of chat.turns) {
      const selected = turn.selectedImageryId ?? (turn.geospatialResult?.type === "preview" ? turn.geospatialResult.imagery_id : null);
      const key = `${turn.id}:${selected}`;
      if (!turn.restored && turn.role === "assistant" && selected && !seenPreviews.current.has(key)) {
        seenPreviews.current.add(key);
        chat.selectImagery(selected);
        setRoi((prev) => prev?.kind === "pixel" ? null : prev);
      }
    }
  }, [chat.turns]);

  const activateImage = (meta: ImageryMeta) => {
    rememberImage(meta);
    setSelectionError(null);
    chat.selectImagery(meta.imagery_id);
    setRoiSource("selected_imagery");
    setLayerOverrides((prev) => ({...prev, [`imagery-${meta.imagery_id}`]: {visible: true}}));
    setRoi((prev) => prev?.kind === "pixel" ? null : prev);
  };
  const selectImage = async (id: string) => {
    const version = ++activationVersion.current;
    if (!id) { chat.selectImagery(null); setRoi(null); return; }
    try {
      const meta = await getImagery(id);
      if (version === activationVersion.current) activateImage(meta);
    } catch (err) { setSelectionError(String(err)); }
  };
  const importOnly = async (key: string): Promise<string | null> => {
    const owner = ownerRef.current;
    try {
      const result = await importScene(key);
      const meta = await getImagery(result.imagery_id);
      if (owner !== ownerRef.current) return null;
      rememberImage(meta);
      chat.addSystemNote(`卫星影像已导入 · ${meta.filename} · ${meta.imagery_id}。需要分析时请明确选择“设为分析影像”。`);
      return meta.imagery_id;
    } catch (err) {
      chat.addSystemNote(`场景导入失败：${err instanceof Error ? err.message : String(err)}`);
      return null;
    }
  };

  const openWorkspace = () => setAppSection("workspace");
  const openSatellite = () => {
    setToolsOpen(false);
    setDataOpen(false);
    setTasksOpen(false);
    setReportsOpen(false);
    setAppSection("satellite");
  };

  const previewScene = (scene: SceneCardInfo) => {
    setSatelliteMode("imagery");
    setScenePreviewRequest({ token: Date.now(), scene });
    openSatellite();
  };

  // 当前预览独立于对话历史，新对话仍可使用已选择的上传影像。
  const layers = useMemo(
    () => layersFromTurns([...chat.turns, ...(selectedImage ? [{
      id: `selected-${selectedImage.imagery_id}`, role: "system" as const, content: "",
      geospatialResult: {type: "preview" as const, imagery_id: selectedImage.imagery_id,
        result_url: selectedImage.preview_url ?? "", bounds: selectedImage.bounds as [number,number,number,number] | null},
    }] : [])], layerOverrides),
    [chat.turns, layerOverrides, selectedImage],
  );
  // 任务队列 / 分析报告均为对话 turns 的不同投影：前者来自 agentTrace 执行轨迹，后者来自真实结果。
  const tasks = useMemo(
    () => tasksFromTurns(chat.turns, chat.activeStream ? chat.turns[chat.turns.length - 1]?.id : null),
    [chat.turns, chat.activeStream],
  );
  const reports = useMemo(() => reportsFromTurns(chat.turns), [chat.turns]);
  const hasImagery = !!selectedImage;

  const triggerUpload = () => fileRef.current?.click();

  const handleFile = async (file: File | undefined) => {
    if (!file) return;
    const version = ++activationVersion.current;
    const owner = ownerRef.current;
    let meta: ImageryMeta;
    try { meta = await imagery.upload(file); }
    catch (err) {
      chat.addSystemNote(`影像上传失败：${err instanceof Error ? err.message : String(err)}`);
      return;
    }
    if (owner !== ownerRef.current) return;
    rememberImage(meta);
    if (version === activationVersion.current) activateImage(meta);
    chat.addSystemNote(`影像已上传 · ${meta.filename} · ${meta.imagery_id}`);
  };

  // ---- session navigation -------------------------------------------------
  const startSession = (firstText?: string) => {
    chat.resetConversation();
    setLayerOverrides({});
    // The first message can refer to a box drawn on the welcome map.
    if (!firstText?.trim()) setRoi(null);
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
    seenPreviews.current = new Set();
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
        mapRef={mapRef}
        layers={layers}
        activeImageryId={chat.activeImageryId}
        roi={roi}
        onSelectRegion={(region) => {
          setRoi(region);
          const bounds = selectedImage?.bounds;
          const useSelected = region.kind === "pixel" || (region.kind === "geo" && bounds?.length === 4
            && region.bbox[0] >= bounds[0] && region.bbox[1] >= bounds[1] && region.bbox[2] <= bounds[2] && region.bbox[3] <= bounds[3]
            && layers.some((layer) => layer.kind === "imagery" && layer.imageryId === chat.activeImageryId && layer.visible));
          setRoiSource(useSelected ? "selected_imagery" : "current_map");
        }}
        onClearRegion={() => setRoi(null)}
        onClassifyRegion={() => launchModelPrompt("请对框选区域进行地物分类。")}
        onAnnotationsChange={setAnnotations}
      />

      <TopBar settings={settings} auth={auth} navigation={<TaskBar
        activeSection={appSection}
        onOpenWorkspace={openWorkspace}
        onOpenTools={() => setToolsOpen(true)}
        onOpenData={() => setDataOpen(true)}
        onOpenTasks={() => setTasksOpen(true)}
        onOpenReports={() => setReportsOpen(true)}
        onOpenSearch={openSatellite}
      />} />

      <SatelliteWorkspace
        active={appSection === "satellite"}
        mode={satelliteMode}
        onModeChange={setSatelliteMode}
        onSceneImport={importOnly}
        onActivateImagery={selectImage}
        onOpenWorkspace={openWorkspace}
        roi={roi}
        roiSelectionVersion={searchRoiVersion}
        previewRequest={scenePreviewRequest}
      />

      <DataPanel
        open={dataOpen}
        onOpenChange={setDataOpen}
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
        {appSection === "workspace" && view === "chat" && (
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
        {appSection === "workspace" && (view === "welcome" ? (
          <WelcomeScreen key="welcome" onStart={startSession} />
        ) : (
          <AgentChat
            key="chat"
            turns={chat.turns}
            loading={chat.loading}
            activeStream={chat.activeStream}
            hasImagery={hasImagery}
            imageryOptions={availableImagery}
            activeImageryId={chat.activeImageryId}
            onSelectImagery={selectImage}
            imageryNotice={roi && roiSource === "current_map" ? "本次选区使用地图卫星底图，可直接提取建筑或进行地物分类。" : roiMismatch ? "框选区域与当前影像不相交，请切换分析数据或重新框选。" : selectionError}
            onLocateImagery={() => {
              if (selectedImage?.bounds?.length === 4) mapRef.current?.fitBounds(selectedImage.bounds as [number,number,number,number], {padding: 64});
            }}
            uploading={imagery.uploading}
            onSend={chat.sendMessage}
            onUpload={triggerUpload}
            onBack={goBack}
            onGenerateReport={chat.generateReport}
            reportPending={chat.reportPending}
            thinkingStrength={settings.thinkingStrength}
            onThinkingChange={settings.setThinkingStrength}
            onScenePreview={previewScene}
            onSceneImport={importOnly}
          />
        ))}
      </AnimatePresence>
      {appSection === "workspace" && roi && <RoiAnalysisPanel roi={roi} source={roiSource} activeImageryId={chat.activeImageryId} loading={chat.loading || imagery.uploading}
        onSourceChange={setRoiSource} onClear={() => setRoi(null)}
        onRun={(target) => launchModelPrompt(target === "building" ? "提取框选区域内的建筑物。" : "请对框选区域进行地物分类。")}
        onSearch={() => { setSearchRoiVersion((v) => v + 1); setSatelliteMode("imagery"); openSatellite(); }} />}
    </div>
  );
}

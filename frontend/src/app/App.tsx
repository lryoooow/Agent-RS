import { useEffect, useState } from "react";
import { AnimatePresence } from "motion/react";
import { MapView, layerKeyOf, type LayerUiState } from "./components/MapView";
import { AgentChat } from "./components/AgentChat";
import { RightPanel } from "./components/RightPanel";
import { WelcomeScreen } from "./components/WelcomeScreen";
import { TopBar } from "./components/TopBar";
import { TaskBar } from "./components/TaskBar";
import { ToolsPage } from "./components/ToolsPage";
import { useSettings } from "./hooks/useSettings";
import { useChatController } from "./hooks/useChatController";
import { listConversations, type ConversationItem } from "./lib/conversations-api";
import { AuthDialog } from "./components/panels/AuthDialog";
import { DataModal, MemoryModal } from "./components/panels/DataModals";
import type { GeospatialResult } from "./types";

export default function App() {
  const settings = useSettings();
  const chat = useChatController({
    endpoint: settings.endpoint,
    systemPrompt: settings.systemPrompt,
    streamEnabled: settings.streamEnabled,
    useRag: settings.useRag,
    providerConfig: settings.effectiveProviderConfig,
  });

  const [view, setView] = useState<"welcome" | "chat">("welcome");
  const [toolsOpen, setToolsOpen] = useState(false);
  const [dataOpen, setDataOpen] = useState(false);
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [layerUi, setLayerUi] = useState<LayerUiState>({});
  const [hasImagery, setHasImagery] = useState(false);

  // All geospatial results across the conversation become map/panel layers.
  const geospatialResults: GeospatialResult[] = chat.turns
    .filter((t) => t.geospatialResult)
    .map((t) => t.geospatialResult!);

  // Load conversation history for the welcome screen.
  useEffect(() => {
    let cancelled = false;
    listConversations(settings.endpoint)
      .then((items) => {
        if (!cancelled) setConversations(items);
      })
      .catch(() => {
        if (!cancelled) setConversations([]);
      });
    return () => {
      cancelled = true;
    };
  }, [settings.endpoint, view]);

  // Keep layerUi keys in sync with current results (default visible + 0.85 opacity).
  useEffect(() => {
    setLayerUi((prev) => {
      const next: LayerUiState = {};
      geospatialResults.forEach((result, idx) => {
        const key = layerKeyOf(result, idx);
        next[key] = prev[key] ?? { visible: true, opacity: result.type === "preview" ? 1 : 0.85 };
      });
      return next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chat.turns]);

  const toggleLayer = (key: string) =>
    setLayerUi((prev) => ({
      ...prev,
      [key]: { ...(prev[key] ?? { visible: true, opacity: 0.85 }), visible: !(prev[key]?.visible ?? true) },
    }));

  const setLayerOpacity = (key: string, v: number) =>
    setLayerUi((prev) => ({
      ...prev,
      [key]: { ...(prev[key] ?? { visible: true, opacity: 0.85 }), opacity: v },
    }));

  const focusLayer = (_result: GeospatialResult) => {
    // MapView owns fitBounds via its own focus button; this is a hook point kept
    // for future per-layer camera control from the panel.
  };

  const handleImageryUploaded = (msg: string, result: GeospatialResult) => {
    setHasImagery(true);
    chat.addGeospatialResult(msg, result);
  };

  const startSession = (firstText?: string) => {
    chat.resetConversation();
    setHasImagery(false);
    setLayerUi({});
    setView("chat");
    if (firstText) setTimeout(() => chat.sendMessage(firstText), 0);
  };

  const openSession = (id: string) => {
    chat.resetConversation();
    chat.setConversationId(id);
    setHasImagery(false);
    setLayerUi({});
    setView("chat");
  };

  const goBack = () => setView("welcome");

  const launchModel = (_intent: string, label: string) => {
    setToolsOpen(false);
    const prompt = `运行模型：${label}。请对当前已上传影像执行该分析，并将结果叠加到地图。`;
    if (view !== "chat") {
      startSession(prompt);
    } else {
      chat.sendMessage(prompt);
    }
  };

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-background text-foreground">
      <MapView geospatialResults={geospatialResults} layerUi={layerUi} />

      <TopBar
        settings={{
          endpoint: settings.endpoint,
          systemPrompt: settings.systemPrompt,
          streamEnabled: settings.streamEnabled,
          useRag: settings.useRag,
          modelLabel: settings.serverConfig?.default_model ?? "",
          webSearchEnabled: settings.serverConfig?.web_search_enabled ?? false,
          baseUrl: settings.baseUrl,
          apiKey: settings.apiKey,
          model: settings.model,
          apiKeyConfigured: settings.serverConfig?.api_key_configured ?? false,
          allowClientProviderConfig: settings.serverConfig?.allow_client_provider_config ?? false,
        }}
        onSave={(next) => {
          settings.setEndpoint(next.endpoint);
          settings.setSystemPrompt(next.systemPrompt);
          settings.setStreamEnabled(next.streamEnabled);
          settings.setUseRag(next.useRag);
          settings.setBaseUrl(next.baseUrl);
          settings.setApiKey(next.apiKey);
          settings.setModel(next.model);
        }}
        rightSlot={<AuthDialog endpoint={settings.endpoint} />}
      />
      <TaskBar
        onOpenTools={() => setToolsOpen(true)}
        onOpenData={() => setDataOpen(true)}
        onOpenMemory={() => setMemoryOpen(true)}
      />

      <AnimatePresence>
        {view === "chat" && (
          <RightPanel
            results={geospatialResults}
            layerUi={layerUi}
            onToggle={toggleLayer}
            onOpacity={setLayerOpacity}
            onFocus={focusLayer}
          />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {toolsOpen && <ToolsPage onClose={() => setToolsOpen(false)} onRun={launchModel} />}
      </AnimatePresence>

      <AnimatePresence>
        {dataOpen && <DataModal endpoint={settings.endpoint} onClose={() => setDataOpen(false)} />}
      </AnimatePresence>

      <AnimatePresence>
        {memoryOpen && (
          <MemoryModal endpoint={settings.endpoint} onClose={() => setMemoryOpen(false)} />
        )}
      </AnimatePresence>

      <AnimatePresence mode="wait">
        {view === "welcome" ? (
          <WelcomeScreen
            key="welcome"
            sessions={conversations}
            onStart={startSession}
            onOpenSession={openSession}
          />
        ) : (
          <AgentChat
            key="chat"
            turns={chat.turns}
            loading={chat.loading}
            activeStream={chat.activeStream}
            endpoint={settings.endpoint}
            hasImagery={hasImagery}
            onSend={chat.sendMessage}
            onImageryUploaded={handleImageryUploaded}
            onBack={goBack}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

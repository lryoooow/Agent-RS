import { useState } from "react";
import { ChatComposer } from "./components/ChatComposer";
import { Conversation } from "./components/conversation/Conversation";
import { AppHeader } from "./components/AppHeader";
import { AuthPanel } from "./components/auth/AuthPanel";
import { HistoryPanel } from "./components/history/HistoryPanel";
import { KnowledgePanel } from "./components/knowledge/KnowledgePanel";
import { MapPanel } from "./components/map/MapPanel";
import type { GeospatialResult } from "./types";
import { MemoryPanel } from "./components/memory/MemoryPanel";
import { SettingsPanel } from "./components/settings/SettingsPanel";
import { useAutoScroll } from "./hooks/useAutoScroll";
import { useAutosizeTextarea } from "./hooks/useAutosizeTextarea";
import { useAuth } from "./hooks/useAuth";
import { useChatController } from "./hooks/useChatController";
import { useSettings } from "./hooks/useSettings";

export default function App() {
  const settings = useSettings();
  const auth = useAuth(settings.endpoint);
  const chat = useChatController({
    endpoint: settings.endpoint,
    systemPrompt: settings.systemPrompt,
    streamEnabled: settings.streamEnabled,
    useRag: settings.useRag,
  });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [knowledgeOpen, setKnowledgeOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [authOpen, setAuthOpen] = useState(false);
  const scrollRef = useAutoScroll<HTMLDivElement>([chat.turns, chat.loading]);
  const textareaRef = useAutosizeTextarea(chat.input);
  const isEmpty = chat.turns.length === 0;

  const geospatialResults: GeospatialResult[] = chat.turns
    .filter((t) => t.geospatialResult)
    .map((t) => t.geospatialResult!);

  return (
    <div
      className="size-full flex flex-col bg-background text-foreground"
      style={{ fontFamily: "Inter, system-ui, sans-serif" }}
    >
      <AppHeader
        isEmpty={isEmpty}
        loading={chat.loading}
        settingsOpen={settingsOpen}
        knowledgeOpen={knowledgeOpen}
        historyOpen={historyOpen}
        memoryOpen={memoryOpen}
        authOpen={authOpen}
        userLabel={auth.user?.email ?? "default user"}
        authenticated={Boolean(auth.user?.authenticated)}
        onReset={chat.resetConversation}
        onToggleSettings={() => {
          setSettingsOpen((value) => !value);
          setKnowledgeOpen(false);
          setHistoryOpen(false);
          setMemoryOpen(false);
          setAuthOpen(false);
        }}
        onToggleKnowledge={() => {
          setKnowledgeOpen((value) => !value);
          setSettingsOpen(false);
          setHistoryOpen(false);
          setMemoryOpen(false);
          setAuthOpen(false);
        }}
        onToggleHistory={() => {
          setHistoryOpen((value) => !value);
          setSettingsOpen(false);
          setKnowledgeOpen(false);
          setMemoryOpen(false);
          setAuthOpen(false);
        }}
        onToggleMemory={() => {
          setMemoryOpen((value) => !value);
          setSettingsOpen(false);
          setKnowledgeOpen(false);
          setHistoryOpen(false);
          setAuthOpen(false);
        }}
        onToggleAuth={() => {
          setAuthOpen((value) => !value);
          setSettingsOpen(false);
          setKnowledgeOpen(false);
          setHistoryOpen(false);
          setMemoryOpen(false);
        }}
      />

      {settingsOpen && (
        <SettingsPanel
          endpoint={settings.endpoint}
          systemPrompt={settings.systemPrompt}
          streamEnabled={settings.streamEnabled}
          useRag={settings.useRag}
          serverConfig={settings.serverConfig}
          configError={settings.configError}
          onEndpointChange={settings.setEndpoint}
          onSystemPromptChange={settings.setSystemPrompt}
          onStreamEnabledChange={settings.setStreamEnabled}
          onUseRagChange={settings.setUseRag}
          onClearSettings={settings.clearSettings}
        />
      )}

      {knowledgeOpen && <KnowledgePanel endpoint={settings.endpoint} />}
      {historyOpen && <HistoryPanel endpoint={settings.endpoint} />}
      {memoryOpen && <MemoryPanel endpoint={settings.endpoint} />}
      {authOpen && (
        <AuthPanel
          user={auth.user}
          loading={auth.loading}
          error={auth.error}
          onLogin={auth.signIn}
          onRegister={auth.signUp}
          onLogout={auth.signOut}
        />
      )}

      <div className="flex flex-1 min-h-0">
        <div className="flex flex-col flex-1 min-w-0">
          <Conversation
            turns={chat.turns}
            loading={chat.loading}
            activeStream={chat.activeStream}
            scrollRef={scrollRef}
            onPickSuggestion={chat.sendMessage}
          />

          <ChatComposer
            endpoint={settings.endpoint}
            input={chat.input}
            loading={chat.loading}
            textareaRef={textareaRef}
            onInputChange={chat.setInput}
            onSubmit={chat.handleSubmit}
            onKeyDown={chat.handleKeyDown}
            onImageryUploaded={chat.addSystemNote}
          />
        </div>

        <div className="w-[45%] min-w-[360px] max-w-[600px]">
          <MapPanel
            endpoint={settings.endpoint}
            geospatialResults={geospatialResults}
          />
        </div>
      </div>
    </div>
  );
}

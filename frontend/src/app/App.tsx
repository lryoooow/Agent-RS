import { useState } from "react";
import { ChatComposer } from "./components/ChatComposer";
import { Conversation } from "./components/conversation/Conversation";
import { AppHeader } from "./components/AppHeader";
import { SettingsPanel } from "./components/settings/SettingsPanel";
import { useAutoScroll } from "./hooks/useAutoScroll";
import { useAutosizeTextarea } from "./hooks/useAutosizeTextarea";
import { useChatController } from "./hooks/useChatController";
import { useSettings } from "./hooks/useSettings";

export default function App() {
  const settings = useSettings();
  const chat = useChatController({
    endpoint: settings.endpoint,
    model: settings.model,
    systemPrompt: settings.systemPrompt,
    streamEnabled: settings.streamEnabled,
    buildProviderConfig: settings.buildProviderConfig,
  });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const scrollRef = useAutoScroll<HTMLDivElement>([chat.turns, chat.loading]);
  const textareaRef = useAutosizeTextarea(chat.input);
  const isEmpty = chat.turns.length === 0;

  return (
    <div
      className="size-full flex flex-col bg-background text-foreground"
      style={{ fontFamily: "Inter, system-ui, sans-serif" }}
    >
      <AppHeader
        isEmpty={isEmpty}
        loading={chat.loading}
        settingsOpen={settingsOpen}
        onReset={chat.resetConversation}
        onToggleSettings={() => setSettingsOpen((value) => !value)}
      />

      {settingsOpen && (
        <SettingsPanel
          endpoint={settings.endpoint}
          baseURL={settings.baseURL}
          apiKey={settings.apiKey}
          model={settings.model}
          systemPrompt={settings.systemPrompt}
          streamEnabled={settings.streamEnabled}
          serverConfig={settings.serverConfig}
          configError={settings.configError}
          hasProviderOverride={settings.hasProviderOverride}
          onEndpointChange={settings.setEndpoint}
          onBaseURLChange={settings.setBaseURL}
          onApiKeyChange={settings.setApiKey}
          onModelChange={settings.setModel}
          onSystemPromptChange={settings.setSystemPrompt}
          onStreamEnabledChange={settings.setStreamEnabled}
          onClearSettings={settings.clearSettings}
        />
      )}

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
      />
    </div>
  );
}

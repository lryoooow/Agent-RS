import { Trash2 } from "lucide-react";
import type { ConfigResponse } from "../../types";
import { ConfigStatus } from "./ConfigStatus";
import { SettingsField } from "./SettingsField";

type SettingsPanelProps = {
  endpoint: string;
  systemPrompt: string;
  streamEnabled: boolean;
  useRag: boolean;
  serverConfig: ConfigResponse | null;
  configError: string;
  onEndpointChange: (value: string) => void;
  onSystemPromptChange: (value: string) => void;
  onStreamEnabledChange: (value: boolean) => void;
  onUseRagChange: (value: boolean) => void;
  onClearSettings: () => void;
};

export function SettingsPanel({
  endpoint,
  systemPrompt,
  streamEnabled,
  useRag,
  serverConfig,
  configError,
  onEndpointChange,
  onSystemPromptChange,
  onStreamEnabledChange,
  onUseRagChange,
  onClearSettings,
}: SettingsPanelProps) {
  return (
    <div className="border-b border-border bg-card/60 px-6 md:px-10 py-5">
      <div className="grid gap-4 md:grid-cols-[1.2fr_1.4fr_1fr]">
        <SettingsField label="backend endpoint">
          <input
            value={endpoint}
            onChange={(e) => onEndpointChange(e.target.value)}
            className="w-full bg-transparent border border-border rounded-md px-3 py-2 text-sm outline-none focus:border-foreground/40 transition-colors"
            style={{ fontFamily: "'JetBrains Mono', monospace" }}
          />
        </SettingsField>
        <SettingsField label="extra instructions">
          <textarea
            value={systemPrompt}
            onChange={(e) => onSystemPromptChange(e.target.value)}
            placeholder="Optional per-chat instructions. The backend owns the base system prompt."
            rows={2}
            className="w-full resize-none bg-transparent border border-border rounded-md px-3 py-2 text-sm outline-none focus:border-foreground/40 transition-colors placeholder:text-muted-foreground/60"
          />
        </SettingsField>
        <div className="flex flex-col gap-2 justify-end">
          <label
            className="inline-flex items-center gap-2 text-xs text-muted-foreground"
            style={{ fontFamily: "'JetBrains Mono', monospace" }}
          >
            <input
              type="checkbox"
              checked={streamEnabled}
              onChange={(e) => onStreamEnabledChange(e.target.checked)}
              className="size-3.5 accent-foreground"
            />
            stream response
          </label>
          <label
            className="inline-flex items-center gap-2 text-xs text-muted-foreground"
            style={{ fontFamily: "'JetBrains Mono', monospace" }}
          >
            <input
              type="checkbox"
              checked={useRag}
              onChange={(e) => onUseRagChange(e.target.checked)}
              className="size-3.5 accent-foreground"
            />
            use knowledge base
          </label>
          <ConfigStatus
            config={serverConfig}
            error={configError}
          />
          <button
            type="button"
            onClick={onClearSettings}
            className="inline-flex items-center justify-center gap-1.5 border border-border rounded-md px-3 py-2 text-xs hover:bg-muted transition-colors"
            style={{ fontFamily: "'JetBrains Mono', monospace" }}
          >
            <Trash2 className="size-3.5" />
            clear settings
          </button>
        </div>
      </div>
    </div>
  );
}

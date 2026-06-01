import type { ConfigResponse } from "../../types";
import { StatusPill } from "./StatusPill";

type ConfigStatusProps = {
  config: ConfigResponse | null;
  error: string;
};

export function ConfigStatus({ config, error }: ConfigStatusProps) {
  if (error) {
    return (
      <div
        className="text-[10px] leading-relaxed text-destructive"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        backend config unavailable: {error}
      </div>
    );
  }

  if (!config) {
    return (
      <div
        className="text-[10px] text-muted-foreground"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        checking backend config…
      </div>
    );
  }

  let keyStatus = "key missing";
  if (config.api_key_configured) keyStatus = "env key";
  const extraInstructionsStatus = config.allow_user_extra_instructions
    ? "extra instructions on"
    : "extra instructions off";
  const searchStatus =
    config.web_search_enabled && config.web_search_configured ? "web search on" : "web search off";

  return (
    <div className="flex flex-wrap gap-1.5">
      <StatusPill label={config.provider} />
      <StatusPill label={keyStatus} />
      <StatusPill label={config.default_model ?? "model unset"} />
      <StatusPill label={config.prompt_profile} />
      {config.prompt_dynamic_modules_enabled && <StatusPill label="dynamic prompts" />}
      <StatusPill label={config.system_prompt_language} />
      <StatusPill label={extraInstructionsStatus} />
      <StatusPill label={searchStatus} />
    </div>
  );
}

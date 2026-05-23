import { KeyRound } from "lucide-react";
import type { ConfigResponse } from "../../types";
import { StatusPill } from "./StatusPill";

type ConfigStatusProps = {
  config: ConfigResponse | null;
  error: string;
  hasProviderOverride: boolean;
};

export function ConfigStatus({ config, error, hasProviderOverride }: ConfigStatusProps) {
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
  else if (hasProviderOverride) keyStatus = "client key";
  const extraInstructionsStatus = config.allow_user_extra_instructions
    ? "extra instructions on"
    : "extra instructions off";

  return (
    <div className="flex flex-wrap gap-1.5">
      <StatusPill label={config.provider} />
      <StatusPill label={keyStatus} />
      <StatusPill label={config.default_model ?? "model unset"} />
      <StatusPill label={config.system_prompt_template} />
      <StatusPill label={config.system_prompt_language} />
      <StatusPill label={extraInstructionsStatus} />
      {config.allow_client_provider_config && (
        <StatusPill label="client config on" icon={<KeyRound className="size-3" />} />
      )}
    </div>
  );
}

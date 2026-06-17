import type { Dispatch, SetStateAction } from "react";
import type { StreamHandlers } from "./sse";
import { isHiddenAgentStatus } from "./agent-status";
import { appendToTurn, updateAnalysisStatus, uid, updateTurn } from "./turns";
import type {
  AgentStatus,
  AnalysisStatus,
  ChatResponse,
  ChatTurn,
  GeospatialResult,
  LegendInfo,
  RasterCapabilities,
  ToolExecutionInfo,
  ToolResult,
  Usage,
} from "../types";

type SetTurns = Dispatch<SetStateAction<ChatTurn[]>>;

export function createStreamHandlers(
  setTurns: SetTurns,
  assistantId: string,
  onConversationId?: (conversationId: string) => void,
): StreamHandlers {
  return {
    onMeta: (data) => {
      if (typeof data.conversation_id === "string") {
        onConversationId?.(data.conversation_id);
      }
      setTurns((prev) =>
        updateTurn(prev, assistantId, {
          model: typeof data.model === "string" ? data.model : undefined,
          provider: typeof data.provider === "string" ? data.provider : undefined,
        }),
      );
    },
    onDelta: (content) => {
      setTurns((prev) => appendToTurn(prev, assistantId, content));
    },
    onAnalysisStatus: (data) => {
      const status = normalizeAnalysisStatus(data.status);
      if (!status) return;
      const label = typeof data.label === "string" ? data.label : undefined;
      setTurns((prev) => updateAnalysisStatus(prev, assistantId, status, label));
    },
    onAgentStatus: (data) => {
      const status = normalizeAgentStatus(data.status);
      if (!status) return;
      const label = typeof data.label === "string" ? data.label : undefined;
      // 规划等内部步骤：记录 agentStatus（气泡层已过滤不显示），但不覆盖顶部进度行，
      // 否则"正在理解"会被"正在判断是否需要联网/规划能力调用"等噪声闪掉。
      if (isHiddenAgentStatus(status)) {
        setTurns((prev) =>
          updateTurn(prev, assistantId, { agentStatus: status, agentLabel: label }),
        );
        return;
      }
      setTurns((prev) =>
        updateTurn(prev, assistantId, {
          agentStatus: status,
          agentLabel: label,
          analysisStatus: status === "final_answering" ? "answering" : "preparing",
          analysisLabel: label,
        }),
      );
    },
    onDone: (data) => {
      const geospatialResult = parseGeospatialResult(data.geospatial_result);
      const toolResult = parseToolResult(data.tool_result);
      const finishReason = typeof data.finish_reason === "string" ? data.finish_reason : undefined;
      const failed = finishReason === "error";
      setTurns((prev) =>
        updateTurn(prev, assistantId, {
          analysisStatus: failed ? "answering" : "complete",
          analysisLabel: failed ? "回答生成失败" : "思考完成",
          error: failed,
          usage: data.usage as Usage | undefined,
          finishReason,
          retrievedChunks:
            typeof data.retrieved_chunks === "number" ? data.retrieved_chunks : undefined,
          ragTrace:
            data.rag_trace && typeof data.rag_trace === "object"
              ? (data.rag_trace as Record<string, unknown>)
              : undefined,
          agentTrace:
            data.agent_trace && typeof data.agent_trace === "object"
              ? (data.agent_trace as Record<string, unknown>)
              : undefined,
          geospatialResult,
          toolResult,
        }),
      );
    },
  };
}

export function appendAssistantResponse(setTurns: SetTurns, data: ChatResponse) {
  const geospatialResult = parseGeospatialResult(data.geospatial_result);
  const toolResult = parseToolResult(data.tool_result);
  setTurns((prev) => [
    ...prev,
    {
      id: uid(),
      role: "assistant",
      content: data.content ?? "",
      model: data.model,
      provider: data.provider,
      usage: data.usage,
      finishReason: data.finish_reason,
      retrievedChunks: data.retrieved_chunks,
      ragTrace: data.rag_trace,
      agentTrace: data.agent_trace,
      geospatialResult,
      toolResult,
    },
  ]);
}

function normalizeAnalysisStatus(value: unknown): AnalysisStatus | null {
  if (value === "analyzing" || value === "preparing" || value === "answering" || value === "complete") {
    return value;
  }
  return null;
}

function normalizeAgentStatus(value: unknown): AgentStatus | null {
  if (
    value === "context_assembled" ||
    value === "planning" ||
    value === "planning_fallback" ||
    value === "planner_started" ||
    value === "planner_completed" ||
    value === "planner_invalid" ||
    value === "planner_selected" ||
    value === "planner_no_call" ||
    value === "plan_validation_failed" ||
    value === "capability_guard_rejected" ||
    value === "classifier_skip" ||
    value === "classifier_force" ||
    value === "cache_hit_skip" ||
    value === "cache_hit_search" ||
    value === "tool_requested" ||
    value === "child_agent_running" ||
    value === "tool_execution_started" ||
    value === "tool_execution_completed" ||
    value === "tool_execution_failed" ||
    value === "tool_fallback_used" ||
    value === "tool_context_ready" ||
    value === "geospatial_result_ready" ||
    value === "final_answering" ||
    value === "direct_answer" ||
    value === "tool_unavailable"
  ) {
    return value;
  }
  return null;
}

function parseGeospatialResult(value: unknown): GeospatialResult | undefined {
  if (!value || typeof value !== "object") return undefined;
  const candidate = value as Record<string, unknown>;
  if (
    candidate.type !== "preview" &&
    candidate.type !== "ndvi" &&
    candidate.type !== "spectral_index" &&
    candidate.type !== "composite" &&
    candidate.type !== "detection" &&
    candidate.type !== "segmentation"
  ) {
    return undefined;
  }
  if (typeof candidate.imagery_id !== "string") return undefined;
  if (typeof candidate.result_url !== "string") return undefined;
  const bounds = candidate.bounds;
  if (bounds !== null && !isBounds(bounds)) return undefined;

  const base = {
    imagery_id: candidate.imagery_id,
    result_url: candidate.result_url,
    bounds,
  };
  if (candidate.type === "preview") {
    return { type: "preview", ...base };
  }
  if (candidate.type === "composite") {
    if (typeof candidate.mode !== "string") return undefined;
    if (!Array.isArray(candidate.bands_used) || !candidate.bands_used.every((item) => typeof item === "number")) {
      return undefined;
    }
    return {
      type: "composite",
      ...base,
      mode: candidate.mode,
      bands_used: candidate.bands_used,
      execution: isExecution(candidate.execution) ? candidate.execution : undefined,
    };
  }
  if (candidate.type === "detection") {
    return {
      type: "detection",
      ...base,
      detection_count: typeof candidate.detection_count === "number" ? candidate.detection_count : 0,
      score_threshold: typeof candidate.score_threshold === "number" ? candidate.score_threshold : 0,
      classes: parseDetectionClasses(candidate.classes),
      execution: isExecution(candidate.execution) ? candidate.execution : undefined,
    };
  }
  if (candidate.type === "segmentation") {
    return {
      type: "segmentation",
      ...base,
      total_pixels: typeof candidate.total_pixels === "number" ? candidate.total_pixels : 0,
      classes: parseSegmentationClasses(candidate.classes),
      execution: isExecution(candidate.execution) ? candidate.execution : undefined,
    };
  }
  if (!isStats(candidate.stats)) return undefined;
  if (candidate.type === "spectral_index") {
    if (typeof candidate.index_type !== "string") return undefined;
    const stats = candidate.stats as {
      min: number;
      max: number;
      mean: number;
      std: number;
      nodata_pct?: number;
      index_type?: string;
    };
    return {
      type: "spectral_index",
      ...base,
      index_type: candidate.index_type,
      stats: {
        ...stats,
        index_type: typeof stats.index_type === "string" ? stats.index_type : candidate.index_type,
      },
      execution: isExecution(candidate.execution) ? candidate.execution : undefined,
      legend: parseLegend(candidate.legend),
    };
  }
  return {
    type: "ndvi",
    ...base,
    stats: candidate.stats,
    execution: isExecution(candidate.execution) ? candidate.execution : undefined,
    legend: parseLegend(candidate.legend),
  };
}

function parseToolResult(value: unknown): ToolResult | undefined {
  if (!value || typeof value !== "object") return undefined;
  const candidate = value as Record<string, unknown>;
  if (candidate.type !== "raster_inspect") return undefined;
  if (typeof candidate.imagery_id !== "string") return undefined;
  if (typeof candidate.width !== "number") return undefined;
  if (typeof candidate.height !== "number") return undefined;
  if (typeof candidate.band_count !== "number") return undefined;
  const bounds = candidate.bounds;
  if (bounds != null && !isBounds(bounds)) return undefined;
  const pixelSize = candidate.pixel_size;
  if (pixelSize != null && !isPixelSize(pixelSize)) return undefined;
  return {
    type: "raster_inspect",
    imagery_id: candidate.imagery_id,
    width: candidate.width,
    height: candidate.height,
    band_count: candidate.band_count,
    crs: typeof candidate.crs === "string" ? candidate.crs : null,
    bounds: bounds ?? null,
    dtype: typeof candidate.dtype === "string" ? candidate.dtype : null,
    pixel_size: pixelSize ?? null,
    nodata:
      typeof candidate.nodata === "number" || typeof candidate.nodata === "string"
        ? candidate.nodata
        : null,
    capabilities: parseCapabilities(candidate.capabilities),
    per_band_stats: parseBandStats(candidate.per_band_stats),
    execution: isExecution(candidate.execution) ? candidate.execution : undefined,
  };
}

function isBounds(value: unknown): value is [number, number, number, number] {
  return Array.isArray(value) && value.length === 4 && value.every((item) => typeof item === "number");
}

function isPixelSize(value: unknown): value is [number, number] {
  return Array.isArray(value) && value.length === 2 && value.every((item) => typeof item === "number");
}

function isStats(value: unknown): value is { min: number; max: number; mean: number; std: number } {
  if (!value || typeof value !== "object") return false;
  const stats = value as Record<string, unknown>;
  return ["min", "max", "mean", "std"].every((key) => typeof stats[key] === "number");
}

function isExecution(value: unknown): value is ToolExecutionInfo {
  if (!value || typeof value !== "object") return false;
  const execution = value as Record<string, unknown>;
  return (
    typeof execution.mode === "string" &&
    typeof execution.fallback_used === "boolean" &&
    (execution.error_code === undefined ||
      execution.error_code === null ||
      typeof execution.error_code === "string")
  );
}

function parseDetectionClasses(value: unknown) {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .map((item) => ({
      name: typeof item.name === "string" ? item.name : "",
      label: typeof item.label === "string" ? item.label : "",
      count: typeof item.count === "number" ? item.count : 0,
      color: typeof item.color === "string" ? item.color : "#888888",
    }));
}

function parseSegmentationClasses(value: unknown) {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .map((item) => ({
      name: typeof item.name === "string" ? item.name : "",
      label: typeof item.label === "string" ? item.label : "",
      pixel_count: typeof item.pixel_count === "number" ? item.pixel_count : 0,
      percentage: typeof item.percentage === "number" ? item.percentage : 0,
      color: typeof item.color === "string" ? item.color : "#888888",
    }));
}

function parseLegend(value: unknown): LegendInfo | undefined {
  if (!value || typeof value !== "object") return undefined;
  const legend = value as Record<string, unknown>;
  if (typeof legend.label !== "string") return undefined;
  if (typeof legend.min !== "number" || typeof legend.max !== "number") return undefined;
  if (typeof legend.palette !== "string") return undefined;
  return {
    label: legend.label,
    min: legend.min,
    max: legend.max,
    palette: legend.palette,
  };
}

function parseCapabilities(value: unknown): RasterCapabilities {
  const capabilities = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    has_blue: capabilities.has_blue === true,
    has_green: capabilities.has_green === true,
    has_red: capabilities.has_red === true,
    has_nir: capabilities.has_nir === true,
    has_swir: capabilities.has_swir === true,
  };
}

function parseBandStats(value: unknown) {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .filter((item) => typeof item.band === "number")
    .map((item) => ({
      band: item.band as number,
      min: typeof item.min === "number" ? item.min : null,
      max: typeof item.max === "number" ? item.max : null,
      mean: typeof item.mean === "number" ? item.mean : null,
      std: typeof item.std === "number" ? item.std : null,
    }));
}

export function applyRequestError(setTurns: SetTurns, assistantId: string, shouldStream: boolean, err: unknown) {
  const message = err instanceof Error ? err.message : String(err);
  if (shouldStream) {
    setTurns((prev) =>
      prev.map((turn) =>
        turn.id === assistantId
          ? {
              ...turn,
              content: turn.content ? `${turn.content}\n\n${message}` : message,
              error: true,
            }
          : turn,
      ),
    );
    return;
  }

  setTurns((prev) => [
    ...prev,
    {
      id: uid(),
      role: "assistant",
      content: message,
      error: true,
    },
  ]);
}

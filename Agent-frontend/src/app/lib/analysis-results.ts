import type { AnalysisProvenance, BandCalibrationInfo, CalibrationInfo, GeospatialMaskResult, MaskClass, MaskLegendInfo, MaskStats } from "../types";

const maskClasses: MaskClass[] = ["water", "non_water", "clear", "cloud", "shadow", "nodata", "unknown", "snow", "terrain_shadow", "candidate_bright", "candidate_dark", "candidate_other"];
const textKeys = ["method", "method_version", "method_validation", "calibration_method_version", "warning", "threshold_method", "quality_type", "quality_sensor", "quality_source", "quality_item_id", "cloud_policy", "clear_semantics", "uncertainty_policy"] as const;
const numericKeys = ["threshold_value", "ndwi_threshold", "cloud_vis_threshold", "shadow_nir_threshold"] as const;
const isRecord = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === "object" && !Array.isArray(value);
const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

function parseBandCalibration(value: unknown): Record<string, BandCalibrationInfo> | undefined {
  if (!isRecord(value)) return undefined;
  const out: Record<string, BandCalibrationInfo> = {};
  for (const role of ["red", "green", "blue", "nir", "swir", "swir1", "swir2"]) {
    const band = value[role];
    if (!isRecord(band)) continue;
    const info: BandCalibrationInfo = {};
    if (Number.isSafeInteger(band.band_index) && (band.band_index as number) > 0) info.band_index = band.band_index as number;
    for (const key of ["scale", "offset"] as const) if (finite(band[key])) info[key] = band[key];
    for (const key of ["applied", "input_applied"] as const) if (typeof band[key] === "boolean") info[key] = band[key];
    for (const key of ["source", "quantity", "input_quantity"] as const) if (typeof band[key] === "string") info[key] = band[key];
    out[role] = info;
  }
  return out;
}

export function parseAnalysisProvenance(value: Record<string, unknown>): AnalysisProvenance {
  const out: AnalysisProvenance = {};
  for (const key of textKeys) if (typeof value[key] === "string") out[key] = value[key];
  for (const key of numericKeys) if (finite(value[key])) out[key] = value[key];
  for (const key of ["total_pixels", "valid_pixels", "nodata_pixels"] as const) {
    if (Number.isSafeInteger(value[key]) && (value[key] as number) >= 0) out[key] = value[key] as number;
  }
  if (value.percentage_denominator === "total_pixels" || value.percentage_denominator === "valid_pixels") out.percentage_denominator = value.percentage_denominator;
  if (value.nodata_pct === null || (finite(value.nodata_pct) && value.nodata_pct >= 0 && value.nodata_pct <= 100)) out.nodata_pct = value.nodata_pct;
  if (typeof value.calibrated === "boolean") out.calibrated = value.calibrated;
  if (typeof value.calibration === "string") out.calibration = value.calibration;
  else if (isRecord(value.calibration) && typeof value.calibration.method === "string") {
    const info: CalibrationInfo = { method: value.calibration.method, bands: parseBandCalibration(value.calibration.bands) };
    if (typeof value.calibration.method_version === "string") info.method_version = value.calibration.method_version;
    if (typeof value.calibration.sensor === "string") info.sensor = value.calibration.sensor;
    out.calibration = info;
  }
  out.band_calibration = parseBandCalibration(value.band_calibration);
  if (isRecord(value.resolved_bands)) {
    out.resolved_bands = Object.fromEntries(Object.entries(value.resolved_bands).filter(([role, index]) => ["red", "green", "blue", "nir", "swir", "swir1", "swir2"].includes(role) && Number.isSafeInteger(index) && (index as number) > 0)) as Record<string, number>;
  }
  return out;
}

export function parseMaskStats(value: unknown): MaskStats | undefined {
  if (!isRecord(value)) return undefined;
  const out: MaskStats = parseAnalysisProvenance(value);
  for (const key of ["total_pixels", "valid_pixels", "nodata_pixels"] as const) {
    if (value[key] !== undefined && (!Number.isSafeInteger(value[key]) || (value[key] as number) < 0)) return undefined;
  }
  if (out.total_pixels != null && ((out.valid_pixels ?? 0) > out.total_pixels || (out.nodata_pixels ?? 0) > out.total_pixels)) return undefined;
  if (out.total_pixels != null && out.valid_pixels != null && out.nodata_pixels != null && out.valid_pixels + out.nodata_pixels !== out.total_pixels) return undefined;
  for (const name of maskClasses) for (const suffix of ["pct", "valid_pct", "pixel_count"] as const) {
    const key = `${name}_${suffix}` as const;
    const number = value[key];
    if (number === undefined) continue;
    if (number !== null && (!finite(number) || number < 0 || (suffix !== "pixel_count" && number > 100) || (suffix === "pixel_count" && !Number.isSafeInteger(number)))) return undefined;
    out[key] = number as number | null;
  }
  return out;
}

export function parseMaskLegend(value: unknown): MaskLegendInfo | undefined {
  if (!isRecord(value) || typeof value.label !== "string" || !Array.isArray(value.classes)) return undefined;
  return { label: value.label, classes: value.classes.filter(isRecord).filter(item => Number.isInteger(item.code) && typeof item.name === "string").map(item => ({ code: item.code as number, name: item.name as string })) };
}

export function provenanceRows(stats: AnalysisProvenance): { label: string; value: string }[] {
  const rows: { label: string; value: string }[] = [];
  for (const [key, label] of [["total_pixels", "总像元"], ["valid_pixels", "有效像元"], ["nodata_pixels", "无效像元"]] as const) {
    if (stats[key] != null) rows.push({ label, value: String(stats[key]) });
  }
  if (stats.percentage_denominator) rows.push({ label: "占比分母", value: stats.percentage_denominator === "total_pixels" ? "全网格像元（含无效像元）" : "有效像元" });
  if (stats.calibration) {
    const method = typeof stats.calibration === "string" ? stats.calibration : stats.calibration.method;
    rows.push({ label: "定标来源", value: stats.calibrated === false || method === "uncalibrated_relative" ? "未定标，相对值" : method });
  }
  if (stats.resolved_bands && Object.keys(stats.resolved_bands).length) rows.push({ label: "波段映射", value: Object.entries(stats.resolved_bands).map(([role, index]) => `${role}=B${index}`).join(" / ") });
  return rows;
}

export function maskTitle(result: GeospatialMaskResult): string {
  if (result.type === "water_mask") return "NDWI 阈值水体掩膜";
  if (result.stats.method === "heuristic") return "疑似亮暗区（未验证）";
  if (result.stats.method === "quality_mask") return "云/云影质量标记";
  return "云/云影历史结果（来源未知）";
}

export function maskRows(result: GeospatialMaskResult): { label: string; value: string }[] {
  const stats = result.stats;
  const fields: [MaskClass, string][] = result.type === "water_mask" ? [["water", "水体"], ["non_water", "非水体"], ["nodata", "无效"]]
    : stats.method === "heuristic" ? [["candidate_bright", "疑似亮区"], ["candidate_dark", "疑似暗区"], ["candidate_other", "未命中规则"], ["unknown", "未知"], ["nodata", "无效"]]
    : [["cloud", "云标记"], ["shadow", "云影标记"], ["clear", "未标记云/云影"], ["unknown", "未知"], ["snow", "雪/冰"], ["terrain_shadow", "地形阴影"], ["nodata", "无效"]];
  const rows = fields.map(([field, label]) => ({ label, value: stats[`${field}_pct`] == null ? "未返回" : `${stats[`${field}_pct`]}%` }));
  if (result.type === "water_mask") {
    rows.push({ label: "NDWI 阈值", value: stats.threshold_value != null || stats.ndwi_threshold != null ? String(stats.threshold_value ?? stats.ndwi_threshold) : "来源未知" });
  } else {
    rows.push({ label: "方法", value: stats.method === "heuristic" ? "亮暗启发式，仅定性估计" : stats.method === "quality_mask" ? `${stats.quality_type ?? "QA 类型未知"} · ${stats.quality_source ?? "来源未知"}` : "来源未知（历史结果，未验证）" });
  }
  return [...rows, ...provenanceRows(stats)];
}

export function maskNotice(result: GeospatialMaskResult): string {
  if (result.type === "water_mask") return "NDWI 阈值受传感器、水体浑浊及阴影影响，需结合原始影像核验。";
  if (result.stats.method === "heuristic") return "疑似亮暗区不是云量/云影；未验证，不据此判断是否可分析。";
  if (result.stats.method === "quality_mask") return "统计来自质量产品标记；未知、雪/冰、地形阴影不能当作晴空，未标记不保证可分析。";
  return "缺少方法和质量来源的历史结果，不能当作可信云量。";
}

export function maskLegend(result: GeospatialMaskResult): { label: string; color: string }[] {
  const heuristic = result.stats.method === "heuristic";
  const names = result.type === "water_mask" ? ["非水体（透明）", "水体", "无效（透明）"]
    : [heuristic ? "未命中规则（透明）" : "未标记云/云影（透明）", heuristic ? "疑似亮区" : result.stats.method === "quality_mask" ? "云标记" : "云标记（来源未知）", heuristic ? "疑似暗区" : "云影标记", "无效（透明）", "未知", "雪/冰", "地形阴影"];
  const colors = result.type === "water_mask" ? ["transparent", "#3182bd", "transparent"] : ["transparent", "#ffffff", "#7850a0", "transparent", "#ffa500", "#64c8ff", "#a06428"];
  return names.map((label, code) => ({ label, color: colors[code] }));
}

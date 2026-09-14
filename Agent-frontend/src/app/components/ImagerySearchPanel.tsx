// 卫星影像检索面板（NASA EarthData Search 三栏形态的本地化实现）：
// 左侧筛选 Sheet + 中央主地图（复用 MapView）+ 右侧结果 Sheet。
// 免账号公共数据源（Sentinel-2 / Landsat），预览/下载(TIF)/导入平台全在卡片上完成。
import { useState } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { Satellite, Search, MapPin, Eye, Download, PlusCircle, Loader2, CheckCircle2, AlertTriangle } from "lucide-react";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "./ui/sheet";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Slider } from "./ui/slider";
import { Badge } from "./ui/badge";
import { ScrollArea } from "./ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./ui/select";
import {
  absoluteUrl,
  downloadSceneTif,
  importScene,
  searchImagery,
  type SceneCard,
} from "../lib/imagery-search-api";
import type { Roi } from "../lib/roi";

type SourceKind = "auto" | "sentinel2" | "landsat";

export function ImagerySearchPanel({
  open,
  onOpenChange,
  mapRef,
  roi,
  endpoint,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mapRef: React.MutableRefObject<MapLibreMap | null>;
  roi: Roi | null;
  endpoint: string;
}) {
  // ── 筛选条件 ──
  const [place, setPlace] = useState("");
  const [bbox, setBbox] = useState<number[] | null>(null); // 「当前视野/框选」填充
  const [bboxLabel, setBboxLabel] = useState<string>("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [cloudMax, setCloudMax] = useState(30);
  const [cloudUnlimited, setCloudUnlimited] = useState(false);
  const [source, setSource] = useState<SourceKind>("auto");
  const [limit, setLimit] = useState(10);

  // ── 结果与状态 ──
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scenes, setScenes] = useState<SceneCard[]>([]);
  const [notes, setNotes] = useState<string[]>([]);
  const [searched, setSearched] = useState(false);
  const [importing, setImporting] = useState<string | null>(null);
  const [imported, setImported] = useState<Record<string, string>>({}); // key → imagery_id
  const [downloading, setDownloading] = useState<string | null>(null);
  const [downloaded, setDownloaded] = useState<Record<string, string>>({}); // key → 文件名 (大小)

  const useCurrentView = () => {
    const map = mapRef.current;
    if (!map) return;
    const b = map.getBounds();
    const next = [
      Number(b.getWest().toFixed(4)),
      Number(b.getSouth().toFixed(4)),
      Number(b.getEast().toFixed(4)),
      Number(b.getNorth().toFixed(4)),
    ];
    setBbox(next);
    setBboxLabel(`当前视野 ${next.join(", ")}`);
    setPlace("");
  };

  const useRoi = () => {
    if (roi?.kind !== "geo") return;
    setBbox([...roi.bbox]);
    setBboxLabel(`框选区域 ${roi.bbox.map((v) => Number(v.toFixed(4))).join(", ")}`);
    setPlace("");
  };

  const runSearch = async () => {
    if (!bbox && !place.trim()) {
      setError("请先填写地名，或使用「当前视野 / 框选区域」设定检索范围。");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await searchImagery(endpoint, {
        bbox: bbox ?? undefined,
        place: place.trim() || undefined,
        start_date: startDate || undefined,
        end_date: endDate || undefined,
        cloud_max: cloudUnlimited ? undefined : cloudMax,
        source,
        limit,
      });
      setScenes(response.scenes);
      setNotes(response.notes);
      setSearched(true);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "检索失败，请稍后重试。");
    } finally {
      setLoading(false);
    }
  };

  const previewOnMap = (scene: SceneCard) => {
    const map = mapRef.current;
    if (!map) return;
    const [w, s, e, n] = scene.bbox;
    map.fitBounds(
      [
        [w, s],
        [e, n],
      ],
      { padding: 96, duration: 900 },
    );
  };

  const downloadTif = async (scene: SceneCard) => {
    setDownloading(scene.key);
    setError(null);
    try {
      const result = await downloadSceneTif(scene.key, scene.item_id);
      const sizeMb = (result.sizeBytes / 1024 / 1024).toFixed(1);
      setDownloaded((prev) => ({ ...prev, [scene.key]: `${result.filename}（${sizeMb} MB）` }));
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "下载失败，请稍后重试。";
      setError(`下载 ${scene.item_id} 失败：${message}`);
    } finally {
      setDownloading(null);
    }
  };

  const importToPlatform = async (scene: SceneCard) => {
    setImporting(scene.key);
    setError(null);
    try {
      const result = await importScene(endpoint, scene.key);
      setImported((prev) => ({ ...prev, [scene.key]: result.imagery_id }));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "导入失败，请稍后重试。");
    } finally {
      setImporting(null);
    }
  };

  return (
    <>
      {/* 左侧：检索条件（NASA EarthData 的左栏筛选形态）。
          非模态（中央地图保持可交互）+ 阻止"点外部即关闭"：左右两栏共享开关，
          互点与点地图都会被另一栏判为外部交互而误关；关闭走右上角 X / ESC。 */}
      <Sheet open={open} onOpenChange={onOpenChange} modal={false}>
        <SheetContent
          side="left"
          className="flex w-[340px] flex-col gap-0 bg-sidebar p-0 sm:max-w-[340px]"
          onInteractOutside={(e) => e.preventDefault()}
        >
          <SheetHeader className="border-b border-border px-4 py-3">
            <SheetTitle className="flex items-center gap-2" style={{ fontFamily: "var(--font-display)" }}>
              <Satellite className="size-4 text-primary" />
              卫星影像检索
            </SheetTitle>
            <SheetDescription className="font-mono text-[11px]">
              免账号公开档案 · Sentinel-2（10m）/ Landsat（30m）
            </SheetDescription>
          </SheetHeader>

          <ScrollArea className="min-h-0 flex-1">
            <div className="flex flex-col gap-4 px-4 py-4">
              <div className="flex flex-col gap-1.5">
                <Label className="text-[12px]">区域</Label>
                <div className="flex items-center gap-2">
                  <MapPin className="size-3.5 shrink-0 text-muted-foreground" />
                  <Input
                    value={place}
                    onChange={(e) => {
                      setPlace(e.target.value);
                      setBbox(null);
                      setBboxLabel("");
                    }}
                    placeholder="地名，如 深圳南山"
                    className="h-8 bg-input-background text-[12px]"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <Button variant="outline" size="sm" className="h-7 flex-1 text-[11px]" onClick={useCurrentView}>
                    使用当前视野
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 flex-1 text-[11px]"
                    onClick={useRoi}
                    disabled={roi?.kind !== "geo"}
                  >
                    使用框选区域
                  </Button>
                </div>
                {bboxLabel && (
                  <p className="font-mono text-[10px] text-muted-foreground">{bboxLabel}</p>
                )}
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div className="flex flex-col gap-1.5">
                  <Label className="text-[12px]">开始日期</Label>
                  <Input
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    className="h-8 bg-input-background font-mono text-[11px]"
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-[12px]">结束日期</Label>
                  <Input
                    type="date"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    className="h-8 bg-input-background font-mono text-[11px]"
                  />
                </div>
              </div>

              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <Label className="text-[12px]">云量上限</Label>
                  <span className="font-mono text-[10px] text-muted-foreground">
                    {cloudUnlimited ? "不限" : `≤ ${cloudMax}%`}
                  </span>
                </div>
                <Slider
                  value={[cloudMax]}
                  min={0}
                  max={100}
                  step={5}
                  onValueChange={([v]) => setCloudMax(v)}
                  disabled={cloudUnlimited}
                />
                <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={cloudUnlimited}
                    onChange={(e) => setCloudUnlimited(e.target.checked)}
                    className="size-3 accent-[var(--primary)]"
                  />
                  不限制云量
                </label>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div className="flex flex-col gap-1.5">
                  <Label className="text-[12px]">数据源</Label>
                  <Select value={source} onValueChange={(v) => setSource(v as SourceKind)}>
                    <SelectTrigger className="h-8 bg-input-background text-[12px]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="auto">自动（双源）</SelectItem>
                      <SelectItem value="sentinel2">Sentinel-2</SelectItem>
                      <SelectItem value="landsat">Landsat</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-[12px]">结果数</Label>
                  <Select value={String(limit)} onValueChange={(v) => setLimit(Number(v))}>
                    <SelectTrigger className="h-8 bg-input-background text-[12px]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="5">5 景</SelectItem>
                      <SelectItem value="10">10 景</SelectItem>
                      <SelectItem value="20">20 景</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <Button onClick={runSearch} disabled={loading} className="h-9 text-[12.5px]">
                {loading ? <Loader2 className="size-3.5 animate-spin" /> : <Search className="size-3.5" />}
                检索影像
              </Button>

              {error && (
                <div className="flex items-start gap-1.5 rounded-lg border border-destructive/40 bg-destructive/10 p-2 text-[11px] text-destructive">
                  <AlertTriangle className="mt-0.5 size-3 shrink-0" />
                  {error}
                </div>
              )}
              {notes.length > 0 && (
                <p className="text-[10px] leading-relaxed text-muted-foreground">
                  {notes.join("；")}
                </p>
              )}
            </div>
          </ScrollArea>
        </SheetContent>
      </Sheet>

      {/* 右侧：结果列表（与左侧同时开合，中央留给主地图 → 三栏形态）。 */}
      <Sheet open={open} onOpenChange={onOpenChange} modal={false}>
        <SheetContent
          side="right"
          className="flex w-[400px] flex-col gap-0 bg-sidebar p-0 sm:max-w-[400px]"
          onInteractOutside={(e) => e.preventDefault()}
        >
          <SheetHeader className="border-b border-border px-4 py-3">
            <SheetTitle className="flex items-center gap-2" style={{ fontFamily: "var(--font-display)" }}>
              <Search className="size-4 text-primary" />
              检索结果
            </SheetTitle>
            <SheetDescription className="font-mono text-[11px]">
              {searched ? `${scenes.length} 景影像 · 点击预览定位` : "设定条件后开始检索"}
            </SheetDescription>
          </SheetHeader>

          <ScrollArea className="min-h-0 flex-1">
            <div className="flex flex-col gap-2.5 px-4 py-4">
              {!searched && !loading && (
                <p className="px-1 text-[11.5px] leading-relaxed text-muted-foreground">
                  在左侧设定区域（地名 / 当前视野 / 框选）、时间范围与云量后检索。
                  免账号数据源：Sentinel-2 地表反射率（10m）与 Landsat 8-9（30m）。
                </p>
              )}
              {loading && (
                <div className="flex items-center gap-2 px-1 text-[11.5px] text-muted-foreground">
                  <Loader2 className="size-3.5 animate-spin" /> 正在检索公开影像档案…
                </div>
              )}
              {scenes.map((scene) => {
                const done = imported[scene.key];
                return (
                  <div
                    key={scene.key}
                    className="overflow-hidden rounded-xl border border-border bg-card"
                  >
                    <button
                      className="block w-full cursor-pointer text-left"
                      onClick={() => previewOnMap(scene)}
                      title="在地图上定位该景"
                    >
                      <img
                        src={absoluteUrl(scene.preview_url)}
                        alt={scene.display_name}
                        loading="lazy"
                        className="h-36 w-full bg-muted object-cover"
                      />
                    </button>
                    <div className="flex flex-col gap-1.5 p-2.5">
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-[12px] font-medium">{scene.satellite}</span>
                        <Badge variant="secondary" className="font-mono text-[10px]">
                          {scene.resolution_m ?? "?"}m
                        </Badge>
                      </div>
                      <p className="font-mono text-[10px] text-muted-foreground">
                        {scene.datetime.slice(0, 10)} · 云量{" "}
                        {scene.cloud_cover != null ? `${scene.cloud_cover}%` : "—"} · {scene.item_id}
                      </p>
                      <div className="mt-1 flex items-center gap-1.5">
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-7 flex-1 text-[11px]"
                          onClick={() => previewOnMap(scene)}
                        >
                          <Eye className="size-3" /> 预览
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-7 flex-1 text-[11px]"
                          disabled={downloading === scene.key}
                          onClick={() => downloadTif(scene)}
                        >
                          {downloading === scene.key ? (
                            <>
                              <Loader2 className="size-3 animate-spin" /> 合成中…
                            </>
                          ) : (
                            <>
                              <Download className="size-3" /> 下载 TIF
                            </>
                          )}
                        </Button>
                        <Button
                          variant="secondary"
                          size="sm"
                          className="h-7 flex-1 text-[11px]"
                          disabled={!!done || importing === scene.key}
                          onClick={() => importToPlatform(scene)}
                        >
                          {done ? (
                            <>
                              <CheckCircle2 className="size-3 text-primary" /> 已导入
                            </>
                          ) : importing === scene.key ? (
                            <Loader2 className="size-3 animate-spin" />
                          ) : (
                            <>
                              <PlusCircle className="size-3" /> 导入
                            </>
                          )}
                        </Button>
                      </div>
                      {done && (
                        <p className="font-mono text-[10px] text-primary">
                          已注册为平台影像 {done}，可直接对话分析（如“对这张图算 NDVI”）。
                        </p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </ScrollArea>
        </SheetContent>
      </Sheet>
    </>
  );
}

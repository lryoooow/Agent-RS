import { apiJson } from "./http";
import { isSafeSameOriginUrl } from "./urls";

export type ReportArtifact = {
  imagery_id: string;
  filename: string;
  download_url: string;
};

// 结果卡片"生成 Word 报告"按钮走此端点：服务端以本对话持久化的真实分析结果为准，
// 前端只传 conversation_id（+可选 imagery_id），不传分析数据，避免伪造/陈旧。
export async function createReport(params: {
  conversationId: string;
  imageryId?: string;
}): Promise<ReportArtifact> {
  const body: Record<string, string> = { conversation_id: params.conversationId };
  if (params.imageryId) body.imagery_id = params.imageryId;
  // 报告生成含 Word 渲染，放宽到 2 分钟。
  return apiJson(
    "/reports",
    { method: "POST", json: body, timeoutMs: 120_000 },
    (raw) => {
      if (!raw || typeof raw !== "object") return undefined;
      const value = raw as Record<string, unknown>;
      if (typeof value.imagery_id !== "string" || typeof value.filename !== "string") return undefined;
      if (!isSafeSameOriginUrl(value.download_url)) return undefined;
      return {
        imagery_id: value.imagery_id,
        filename: value.filename,
        download_url: value.download_url,
      };
    },
  );
}

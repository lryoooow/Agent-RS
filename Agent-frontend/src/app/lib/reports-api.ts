import { getApiBaseEndpoint } from "../config";
import { readErrorMessage } from "./errors";

export type ReportArtifact = {
  imagery_id: string;
  filename: string;
  download_url: string;
};

// 结果卡片"生成 Word 报告"按钮走此端点：服务端以本对话持久化的真实分析结果为准，
// 前端只传 conversation_id（+可选 imagery_id），不传分析数据，避免伪造/陈旧。
export async function createReport(
  chatEndpoint: string,
  params: { conversationId: string; imageryId?: string },
): Promise<ReportArtifact> {
  const body: Record<string, string> = { conversation_id: params.conversationId };
  if (params.imageryId) body.imagery_id = params.imageryId;
  const res = await fetch(`${getApiBaseEndpoint(chatEndpoint)}/reports`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    throw new Error(readErrorMessage(payload) ?? `${res.status} ${res.statusText}`);
  }
  return (await res.json()) as ReportArtifact;
}

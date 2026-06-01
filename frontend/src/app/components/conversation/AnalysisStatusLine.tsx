import type { AnalysisStatus } from "../../types";

type AnalysisStatusLineProps = {
  status: AnalysisStatus;
  label?: string;
};

export function AnalysisStatusLine({ status, label }: AnalysisStatusLineProps) {
  return (
    <div
      key={status}
      className="analysis-status-line max-w-[88%] text-sm leading-relaxed text-muted-foreground/80"
    >
      {label ?? getAnalysisLabel(status)}
    </div>
  );
}

function getAnalysisLabel(status: AnalysisStatus) {
  if (status === "analyzing") return "正在解析问题…";
  if (status === "preparing") return "正在整理内容…";
  if (status === "answering") return "正在组织回复…";
  return "思考完成";
}

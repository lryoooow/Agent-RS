import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

type Props = { children: ReactNode };
type State = { failed: boolean; diagnosticId: string | null };

function diagnosticId(): string {
  return `ui-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { failed: false, diagnosticId: null };

  static getDerivedStateFromError(): State {
    return { failed: true, diagnosticId: diagnosticId() };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // 原始异常只写浏览器控制台，界面不展示堆栈、路径或可能包含敏感内容的 message。
    console.error("Agent-RS UI render failure", {
      diagnosticId: this.state.diagnosticId,
      name: error.name,
      componentStack: info.componentStack,
    });
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main className="grid min-h-screen place-items-center bg-background p-6 text-foreground">
        <section role="alert" className="w-full max-w-md rounded-2xl border border-border bg-card p-6 text-center shadow-2xl">
          <AlertTriangle className="mx-auto size-9 text-amber-400" />
          <h1 className="mt-4 text-lg font-semibold">界面暂时无法显示</h1>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            页面组件发生异常。重新加载会恢复到最近保存的会话与地图状态。
          </p>
          {this.state.diagnosticId && (
            <p className="mt-3 font-mono text-[11px] text-muted-foreground">
              诊断编号：{this.state.diagnosticId}
            </p>
          )}
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-5 inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground"
          >
            <RefreshCw className="size-4" />
            重新加载页面
          </button>
        </section>
      </main>
    );
  }
}

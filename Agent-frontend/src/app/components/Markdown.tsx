import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

// 助手消息的 Markdown 渲染：暗色主题、紧凑排版，支持 GFM 表格。
// 仅用于 assistant 正文；用户消息仍走纯文本。
const COMPONENTS: Components = {
  h1: ({ children }) => <h1 className="mb-1.5 mt-2 text-[15px] font-semibold text-foreground first:mt-0">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-1.5 mt-2.5 text-[14px] font-semibold text-foreground first:mt-0">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-1 mt-2 text-[13px] font-semibold text-foreground first:mt-0">{children}</h3>,
  p: ({ children }) => <p className="my-1.5 leading-relaxed first:mt-0 last:mb-0">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noreferrer" className="text-primary underline underline-offset-2 hover:opacity-80">
      {children}
    </a>
  ),
  ul: ({ children }) => <ul className="my-1.5 ml-4 list-disc space-y-0.5 marker:text-primary">{children}</ul>,
  ol: ({ children }) => <ol className="my-1.5 ml-4 list-decimal space-y-0.5 marker:text-muted-foreground">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  hr: () => <hr className="my-2.5 border-border" />,
  blockquote: ({ children }) => (
    <blockquote className="my-1.5 border-l-2 border-primary/50 pl-2.5 text-muted-foreground">{children}</blockquote>
  ),
  code: ({ className, children }) => {
    const inline = !className;
    if (inline) {
      return <code className="rounded bg-background/70 px-1 py-0.5 font-mono text-[12px] text-primary">{children}</code>;
    }
    return (
      <code className="block overflow-x-auto rounded-lg border border-border bg-background/70 p-2.5 font-mono text-[12px] leading-relaxed text-foreground">
        {children}
      </code>
    );
  },
  pre: ({ children }) => <pre className="my-2 overflow-x-auto">{children}</pre>,
  table: ({ children }) => (
    <div className="my-2 overflow-x-auto rounded-lg border border-border">
      <table className="w-full border-collapse text-[12px]">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-background/60">{children}</thead>,
  th: ({ children }) => <th className="border-b border-border px-2.5 py-1.5 text-left font-semibold text-foreground">{children}</th>,
  td: ({ children }) => <td className="border-b border-border/60 px-2.5 py-1.5 align-top">{children}</td>,
};

export function Markdown({ children }: { children: string }) {
  return (
    <div className="text-[13px] text-card-foreground">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
        {children}
      </ReactMarkdown>
    </div>
  );
}

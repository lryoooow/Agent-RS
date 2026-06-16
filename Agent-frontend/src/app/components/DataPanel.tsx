import { Database } from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "./ui/sheet";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "./ui/tabs";
import { KnowledgePanel } from "./KnowledgePanel";
import { MemoryPanel } from "./MemoryPanel";
import { HistoryPanel } from "./HistoryPanel";

// 数据管理抽屉：知识库 / 长期记忆 / 历史会话 三合一。
// 全部复用移植自老前端的 lib api（documents/memories/conversations），cookie 鉴权同源。
export function DataPanel({
  open,
  onOpenChange,
  endpoint,
  onOpenConversation,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  endpoint: string;
  onOpenConversation: (id: string, messages: { role: string; content: string }[]) => void;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-[420px] flex-col gap-0 bg-sidebar p-0 sm:max-w-[420px]">
        <SheetHeader className="border-b border-border px-4 py-3">
          <SheetTitle className="flex items-center gap-2" style={{ fontFamily: "var(--font-display)" }}>
            <Database className="size-4 text-primary" />
            数据管理
          </SheetTitle>
          <SheetDescription className="font-mono text-[11px]">
            知识库文档 · 长期记忆 · 历史会话
          </SheetDescription>
        </SheetHeader>

        <Tabs defaultValue="knowledge" className="flex min-h-0 flex-1 flex-col px-4 py-3">
          <TabsList className="grid w-full grid-cols-3">
            <TabsTrigger value="knowledge">知识库</TabsTrigger>
            <TabsTrigger value="memory">记忆</TabsTrigger>
            <TabsTrigger value="history">历史</TabsTrigger>
          </TabsList>
          <TabsContent value="knowledge" className="min-h-0 flex-1">
            <KnowledgePanel endpoint={endpoint} />
          </TabsContent>
          <TabsContent value="memory" className="min-h-0 flex-1">
            <MemoryPanel endpoint={endpoint} />
          </TabsContent>
          <TabsContent value="history" className="min-h-0 flex-1">
            <HistoryPanel endpoint={endpoint} onOpen={onOpenConversation} />
          </TabsContent>
        </Tabs>
      </SheetContent>
    </Sheet>
  );
}

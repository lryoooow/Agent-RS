import { act, renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useChatController } from "./useChatController";
import { postChat } from "../lib/chat-api";
vi.mock("../lib/chat-api",()=>({postChat:vi.fn()}));
const settings={endpoint:"/api/chat",systemPrompt:"",streamEnabled:false,useRag:true};
beforeEach(()=>vi.clearAllMocks());
const response=()=>new Response(JSON.stringify({reply:"ok",conversation_id:"new-conversation"}),{headers:{"Content-Type":"application/json"}});
it("uses the newly selected imagery even when selection and send share an event",async()=>{
  vi.mocked(postChat).mockResolvedValue(response());
  const {result}=renderHook(()=>useChatController(settings));
  await act(async()=>{result.current.selectImagery("4256dea5c68b");await result.current.sendMessage("这张影像提取建筑");});
  expect(vi.mocked(postChat).mock.calls[0][0].metadata?.active_imagery_id).toBe("4256dea5c68b");
  act(()=>result.current.addGeospatialResult("报告",{type:"report",imagery_id:"fec6252c9325",filename:"report.docx",download_url:"/report.docx"}));
  expect(result.current.activeImageryId).toBe("4256dea5c68b");
  expect(result.current.turns.slice(-1)[0]?.role).toBe("assistant");
  expect(result.current.turns.slice(-1)[0]?.geospatialResult?.type).toBe("report");
});
it("restores the last explicit selection ahead of old analysis results",()=>{
 const {result}=renderHook(()=>useChatController(settings));
 act(()=>result.current.loadConversation("history",[
   {role:"assistant",content:"旧图",metadata:{geospatial_result:{type:"preview",imagery_id:"fec6252c9325",result_url:"/old.png"}}},
   {role:"user",content:"这张图",metadata:{active_imagery_id:"4256dea5c68b"}},
 ]));
 expect(result.current.activeImageryId).toBe("4256dea5c68b");
 act(()=>result.current.loadConversation("history",[
   {role:"user",content:"old",metadata:{active_imagery_id:"4256dea5c68b"}},
   {role:"user",content:"cleared",metadata:{active_imagery_id:null}},
 ]));
 expect(result.current.activeImageryId).toBeNull();
});
it("late completion of an aborted conversation cannot write into the new conversation",async()=>{
 let finishOld!: (r: Response)=>void;
 vi.mocked(postChat).mockReturnValueOnce(new Promise(resolve=>{finishOld=resolve;})).mockResolvedValueOnce(response());
 const {result}=renderHook(()=>useChatController(settings));
 let pending!:Promise<void>;
 act(()=>{pending=result.current.sendMessage("old");});
 act(()=>result.current.resetConversation());
 await act(async()=>{await result.current.sendMessage("new");finishOld(response());await pending;});
 expect(result.current.turns.filter(t=>t.role==="user").map(t=>t.content)).toEqual(["new"]);
 expect(result.current.turns.filter(t=>t.role==="assistant")).toHaveLength(1);
 expect(result.current.loading).toBe(false);
});

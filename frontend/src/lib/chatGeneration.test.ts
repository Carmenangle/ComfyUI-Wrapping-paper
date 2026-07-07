import { describe, it, expect } from "vitest";
import { needsImageInput, hasImageProvided, pickBestText, slimSnapshot } from "./chatGeneration";
import type { Template } from "../api/workflows";
import type { ChatMessage } from "../types/chat";

const tpl = (over: Partial<Template>): Template => ({
  id: "t1", name: "x", source_path: "", exposed: [],
  created_at: 0, updated_at: 0, ...over,
});

describe("needsImageInput", () => {
  it("有 image_node_id → 需要图", () => {
    expect(needsImageInput(tpl({ image_node_id: "5" }))).toBe(true);
  });
  it("exposed 里有 image 控件 → 需要图", () => {
    expect(needsImageInput(tpl({ exposed: [{ node_id: "5", field: "image", label: "", control: "image", semantic: "", default: null }] }))).toBe(true);
  });
  it("都没有 → 不需要", () => {
    expect(needsImageInput(tpl({}))).toBe(false);
  });
});

describe("hasImageProvided", () => {
  const t = tpl({ image_node_id: "5" });
  it("无图像输入口 → 放行", () => {
    expect(hasImageProvided({}, tpl({}))).toBe(true);
  });
  it("litegraph 结构：节点已填 widgets_values → true", () => {
    expect(hasImageProvided({ nodes: [{ id: 5, widgets_values: ["photo.png"] }] }, t)).toBe(true);
  });
  it("litegraph 结构：目标节点为空 → false", () => {
    expect(hasImageProvided({ nodes: [{ id: 5, widgets_values: [""] }] }, t)).toBe(false);
  });
  it("litegraph 结构：目标节点缺失 → false", () => {
    expect(hasImageProvided({ nodes: [{ id: 9, widgets_values: ["x"] }] }, t)).toBe(false);
  });
  it("API 结构：inputs 有非空值 → true", () => {
    expect(hasImageProvided({ "5": { inputs: { image: "photo.png" } } }, t)).toBe(true);
  });
  it("API 结构：inputs 全空 → false", () => {
    expect(hasImageProvided({ "5": { inputs: { image: "" } } }, t)).toBe(false);
  });
  it("两种结构都不匹配（如 null）→ 拿不准放行", () => {
    expect(hasImageProvided(null, t)).toBe(true);
  });
});

describe("pickBestText", () => {
  it("空/undefined → 空串", () => {
    expect(pickBestText(undefined)).toBe("");
    expect(pickBestText([])).toBe("");
  });
  it("过滤纯符号噪声段", () => {
    expect(pickBestText(["!@#$%^&*()", "有效的中文提示词"])).toBe("有效的中文提示词");
  });
  it("多段有效 → 取最长", () => {
    expect(pickBestText(["短", "更长的一段文本"])).toBe("更长的一段文本");
  });
  it("首尾空白被 trim", () => {
    expect(pickBestText(["  hello world  "])).toBe("hello world");
  });
});

describe("slimSnapshot", () => {
  const persist = async (src: string) => (src.startsWith("data:") ? "local://x" : src);
  it("用户 parts 里的 data:URI 图被落盘转小地址", async () => {
    const msgs: ChatMessage[] = [{
      id: "1", role: "user", text: "",
      parts: [{ type: "image", url: "data:image/png;base64,AAAA" }, { type: "text", text: "hi" }],
    }];
    const out = await slimSnapshot(msgs, persist);
    expect(out[0].parts?.[0]).toMatchObject({ type: "image", url: "local://x" });
    expect(out[0].parts?.[1]).toMatchObject({ type: "text", text: "hi" });
  });
  it("已执行的 portsPlan.images 被清空", async () => {
    const msgs: ChatMessage[] = [{
      id: "1", role: "assistant", text: "",
      portsPlan: { status: "applied", images: ["data:image/png;base64,AAAA"], ops: [] } as any,
    }];
    const out = await slimSnapshot(msgs, persist);
    expect(out[0].portsPlan?.images).toEqual([]);
  });
  it("待执行的 portsPlan.images 被落盘保留", async () => {
    const msgs: ChatMessage[] = [{
      id: "1", role: "assistant", text: "",
      portsPlan: { status: "pending", images: ["data:image/png;base64,AAAA"], ops: [] } as any,
    }];
    const out = await slimSnapshot(msgs, persist);
    expect(out[0].portsPlan?.images).toEqual(["local://x"]);
  });
  it("无图消息原样返回", async () => {
    const msgs: ChatMessage[] = [{ id: "1", role: "assistant", text: "纯文本" }];
    const out = await slimSnapshot(msgs, persist);
    expect(out).toEqual(msgs);
  });
});

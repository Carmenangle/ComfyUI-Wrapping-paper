import { describe, expect, it } from "vitest";
import { agentImageMessage, applyPromptApproval, applyRouteChoice, inspirationMessage, upsertMessages, workflowMessages } from "./chatSessionEvents";

describe("chat session event projections", () => {
  it("keeps backend image ids and replaces duplicates", () => {
    const image = agentImageMessage("local://image", "image-1");
    expect(image.id).toBe("image-1");
    expect(upsertMessages([{ ...image, image: "old" }], [image])).toEqual([image]);
  });

  it("keeps workflow message order and text placement", () => {
    const messages = workflowMessages([
      { id: "1", role: "assistant", text: "prompt", image: "a" },
      { id: "2", role: "assistant", text: "", image: "b" },
    ]);
    expect(messages.map((message) => message.text)).toEqual(["prompt", ""]);
  });

  it("normalizes inspiration defaults", () => {
    expect(inspirationMessage({ id: "i", query: "q", prompt: "p", tags: [], sources: [] }))
      .toMatchObject({ id: "i", inspiration: { query: "q", prompt: "p", tags: [], sources: [] } });
  });

  it("updates a historical prompt approval by stable approval id", () => {
    const current = [{
      id: "message-1", role: "assistant" as const, text: "待审核",
      promptApproval: {
        id: "approval-1", messageId: "message-1", kind: "image" as const,
        originalPrompt: "原稿", prompt: "旧稿", status: "pending" as const,
      },
    }];
    const updated = applyPromptApproval(current, {
      id: "approval-1", messageId: "message-1", kind: "image",
      originalPrompt: "原稿", prompt: "用户改稿", status: "pending",
    });

    expect(updated[0].promptApproval?.prompt).toBe("用户改稿");
  });

  it("updates a supervisor route choice by its stable id", () => {
    const current = [{
      id: "message-1", role: "assistant" as const, text: "请选择",
      routeChoice: {
        id: "route-1", messageId: "message-1", userMessageId: "user-1",
        status: "pending" as const,
        options: [{ route: "answer" as const, label: "继续对话" }],
      },
    }];
    const updated = applyRouteChoice(current, {
      ...current[0].routeChoice!,
      status: "selected",
      selectedRoute: "answer",
    });

    expect(updated[0].routeChoice?.selectedRoute).toBe("answer");
  });
});

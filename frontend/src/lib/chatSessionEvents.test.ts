import { describe, expect, it } from "vitest";
import { agentImageMessage, inspirationMessage, upsertMessages, workflowMessages } from "./chatSessionEvents";

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
});

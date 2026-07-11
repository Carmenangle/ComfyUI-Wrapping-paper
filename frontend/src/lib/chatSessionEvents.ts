import type { FinalizedMessage } from "../api/comfyui";
import type { ChatMessage } from "../types/chat";

export function upsertMessages(current: ChatMessage[], incoming: ChatMessage[]): ChatMessage[] {
  const next = [...current];
  for (const message of incoming) {
    const index = next.findIndex((item) => item.id === message.id);
    if (index >= 0) next[index] = message;
    else next.push(message);
  }
  return next;
}

export function workflowMessages(messages: FinalizedMessage[]): ChatMessage[] {
  return messages.map((message) => ({ ...message }));
}

export function agentImageMessage(url: string, id?: string): ChatMessage {
  return { id: id || crypto.randomUUID(), role: "assistant", text: "", image: url };
}

export function inspirationMessage(card: {
  id?: string;
  query: string;
  prompt: string;
  tags: string[];
  sources: { title: string; url: string }[];
}): ChatMessage {
  return {
    id: card.id || crypto.randomUUID(),
    role: "assistant",
    text: "",
    inspiration: {
      query: card.query,
      prompt: card.prompt,
      tags: card.tags || [],
      sources: card.sources || [],
    },
  };
}

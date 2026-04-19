import { Profiler, type ProfilerOnRenderCallback, useState } from "react";
import { act, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ChatMessage from "@/components/chat/ChatMessage";
import type { Message } from "@/lib/types";

function makeMessage(id: string, content: string, isStreaming = false): Message {
  return {
    id,
    role: "assistant",
    content,
    isStreaming,
    blocks: content ? [{ type: "text", text: content }] : [],
  };
}

function Harness({ messages }: { messages: Message[] }) {
  return (
    <>
      {messages.map((message) => (
        <Profiler id={message.id} key={message.id} onRender={recordRender}>
          <ChatMessage message={message} sessionId="session-perf" />
        </Profiler>
      ))}
    </>
  );
}

const renderCounts = new Map<string, number>();
const recordRender: ProfilerOnRenderCallback = (id) => {
  renderCounts.set(id, (renderCounts.get(id) ?? 0) + 1);
};

describe("ChatMessage memoization", () => {
  it("only the streaming ChatMessage re-renders when a token updates its message reference (1k messages)", () => {
    renderCounts.clear();

    const stable: Message[] = [];
    for (let index = 0; index < 999; index += 1) {
      stable.push(makeMessage(`stable-${index}`, `stable content ${index}`));
    }
    const initialStreaming = makeMessage("streaming", "partial", true);
    const initialMessages = [...stable, initialStreaming];

    let setMessages: (next: Message[]) => void = () => {};
    function Controller() {
      const [messages, updater] = useState<Message[]>(initialMessages);
      setMessages = updater;
      return <Harness messages={messages} />;
    }

    render(<Controller />);

    const initialRenders = new Map(renderCounts);
    // Sanity: every ChatMessage mounted exactly once.
    expect(initialRenders.size).toBe(initialMessages.length);
    for (const count of initialRenders.values()) {
      expect(count).toBe(1);
    }

    renderCounts.clear();

    // Simulate a single token arriving: only the streaming message gets a new
    // reference (stable messages keep identity).
    const updatedStreaming: Message = {
      ...initialStreaming,
      content: initialStreaming.content + " extra",
    };
    act(() => {
      setMessages([...stable, updatedStreaming]);
    });

    expect(renderCounts.get("streaming")).toBe(1);
    let otherRenders = 0;
    for (const [id, count] of renderCounts) {
      if (id !== "streaming") {
        otherRenders += count;
      }
    }
    expect(otherRenders).toBe(0);
  });
});

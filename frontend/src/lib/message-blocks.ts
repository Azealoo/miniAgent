import type {
  Message,
  RetrievalResult,
  SessionContentBlock,
  SessionHistoryMessage,
  ToolCall,
} from "./types";

type BlockCompatibleMessage = Pick<
  Message | SessionHistoryMessage,
  "role" | "content" | "tool_calls" | "retrievals" | "blocks"
>;

export interface NormalizedMessageContent {
  blocks: SessionContentBlock[];
  content: string;
  toolCalls: ToolCall[];
  retrievals: RetrievalResult[];
}

function toolBlockKey(tool: string, runId?: string): string {
  return runId ?? tool;
}

function hasBlockType(
  blocks: SessionContentBlock[],
  type: "plan" | "verification"
): boolean {
  return blocks.some((block) => block.type === type);
}

function textBlockTouchesBlockType(
  blocks: SessionContentBlock[],
  index: number,
  type: "plan" | "verification"
): boolean {
  return [index - 1, index + 1].some((candidateIndex) => {
    const candidate = blocks[candidateIndex];
    return candidate?.type === type;
  });
}

interface HelperNarrationOptions {
  hasPlan: boolean;
  hasVerification: boolean;
  planNearby?: boolean;
  verificationNearby?: boolean;
}

export function shouldSuppressHelperNarrationText(
  text: string,
  {
    hasPlan,
    hasVerification,
    planNearby = false,
    verificationNearby = false,
  }: HelperNarrationOptions
): boolean {
  const normalized = text.trim();
  if (!normalized) {
    return false;
  }

  const lower = normalized.toLowerCase();
  const hasPlanJson =
    hasPlan &&
    /"goal"\s*:/.test(normalized) &&
    /"steps"\s*:/.test(normalized);
  const hasVerificationJson =
    hasVerification &&
    /"verdict"\s*:/.test(normalized) &&
    (/"summary"\s*:/.test(normalized) ||
      /"checks"\s*:/.test(normalized) ||
      /"issues"\s*:/.test(normalized) ||
      /"repair_instructions"\s*:/.test(normalized));
  const soundsLikePlannerPreamble =
    hasPlan &&
    (
      lower.startsWith("i'll help you") ||
      lower.startsWith("i will help you") ||
      lower.startsWith("let me ") ||
      lower.startsWith("first, let me") ||
      lower.startsWith("i'm going to") ||
      lower.startsWith("i am going to") ||
      lower.startsWith("based on what i found") ||
      lower.startsWith("based on that") ||
      lower.startsWith("with that in mind") ||
      lower.startsWith("given that") ||
      lower.includes("let me start by creating a structured plan") ||
      lower.includes("creating a structured plan") ||
      lower.includes("planning process") ||
      lower.includes("here is a structured plan") ||
      lower.includes("here's a structured plan") ||
      lower.includes("here is the plan") ||
      lower.includes("here's the plan") ||
      lower.includes("here is the updated plan") ||
      lower.includes("here's the updated plan") ||
      lower.includes("update the plan") ||
      lower.includes("updated plan") ||
      lower.includes("revise the plan") ||
      lower.includes("revised plan") ||
      lower.includes("repair path")
    );
  const soundsLikePlannerStepList =
    hasPlan &&
    planNearby &&
    (
      (/\bstep\s*1\b/i.test(normalized) && /\bstep\s*2\b/i.test(normalized)) ||
      (/(^|\n)\s*1\.\s+/.test(normalized) && /(^|\n)\s*2\.\s+/.test(normalized))
    );
  const soundsLikeVerificationPreamble =
    hasVerification &&
    (
      (verificationNearby &&
        (
          lower.startsWith("now let me verify") ||
          lower.startsWith("let me verify") ||
          lower.startsWith("now let me revise") ||
          lower.startsWith("let me revise") ||
          lower.startsWith("now let me refine") ||
          lower.startsWith("let me refine")
        )) ||
      lower.includes("verification agent") ||
      lower.includes("verification feedback") ||
      lower.includes("verifier verdict")
    );

  return (
    hasPlanJson ||
    hasVerificationJson ||
    soundsLikePlannerPreamble ||
    soundsLikePlannerStepList ||
    soundsLikeVerificationPreamble
  );
}

export function deriveMessageBlocks(
  message: BlockCompatibleMessage
): SessionContentBlock[] {
  if ((message.blocks?.length ?? 0) > 0) {
    return message.blocks ?? [];
  }

  const blocks: SessionContentBlock[] = [];

  if (message.role === "assistant") {
    if ((message.retrievals?.length ?? 0) > 0) {
      blocks.push({
        type: "retrieval",
        results: [...(message.retrievals ?? [])],
      });
    }

    for (const call of message.tool_calls ?? []) {
      blocks.push({
        type: "tool_use",
        tool: call.tool,
        input: call.input,
        run_id: call.run_id,
      });
      blocks.push({
        type: "tool_result",
        tool: call.tool,
        output: call.output,
        run_id: call.run_id,
        result: call.result,
      });
    }
  }

  if ((message.content ?? "").trim()) {
    blocks.push({
      type: "text",
      text: message.content ?? "",
    });
  }

  return blocks;
}

export function normalizeMessageContent(
  message: BlockCompatibleMessage
): NormalizedMessageContent {
  const blocks = deriveMessageBlocks(message);
  const hasPlan = hasBlockType(blocks, "plan");
  const hasVerification = hasBlockType(blocks, "verification");
  const textParts: string[] = [];
  const toolCalls: ToolCall[] = [];
  const retrievals: RetrievalResult[] = [];
  const pendingUses = new Map<string, Array<{ input: string; run_id?: string }>>();

  blocks.forEach((block, index) => {
    switch (block.type) {
      case "text":
        if (
          !shouldSuppressHelperNarrationText(block.text, {
            hasPlan,
            hasVerification,
            planNearby: textBlockTouchesBlockType(blocks, index, "plan"),
            verificationNearby: textBlockTouchesBlockType(
              blocks,
              index,
              "verification"
            ),
          })
        ) {
          textParts.push(block.text);
        }
        break;
      case "tool_use": {
        const key = toolBlockKey(block.tool, block.run_id);
        const queue = pendingUses.get(key) ?? [];
        queue.push({ input: block.input, run_id: block.run_id });
        pendingUses.set(key, queue);
        break;
      }
      case "tool_result": {
        const key = toolBlockKey(block.tool, block.run_id);
        const queue = pendingUses.get(key) ?? [];
        const started = queue.shift();
        if (queue.length > 0) {
          pendingUses.set(key, queue);
        } else {
          pendingUses.delete(key);
        }

        toolCalls.push({
          tool: block.tool,
          input: started?.input ?? "",
          output: block.output,
          run_id: block.run_id ?? started?.run_id,
          result: block.result,
        });
        break;
      }
      case "retrieval":
        retrievals.push(...block.results);
        break;
      case "usage":
      case "plan":
      case "verification":
        break;
    }
  });

  return {
    blocks,
    content: textParts.join("") || (message.content ?? ""),
    toolCalls:
      toolCalls.length > 0 ? toolCalls : [...(message.tool_calls ?? [])],
    retrievals:
      retrievals.length > 0 ? retrievals : [...(message.retrievals ?? [])],
  };
}

export function messageHasProcessTrail(
  message: Pick<
    Message,
    "role" | "content" | "blocks" | "retrievals" | "tool_calls" | "pendingTool"
  >
): boolean {
  return (
    deriveMessageBlocks(message).some(
      (block) => block.type !== "text" && block.type !== "usage"
    ) || message.pendingTool !== undefined
  );
}

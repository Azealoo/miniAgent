export interface ToolCall {
  tool: string;
  input: string;
  output: string;
}

export interface RetrievalResult {
  text: string;
  score: number;
  source: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  tool_calls?: ToolCall[];
  retrievals?: RetrievalResult[];
  isStreaming?: boolean;
  /** Tool currently executing (cleared when tool_end arrives) */
  pendingTool?: { tool: string; input: string; runId: string };
}

export interface Session {
  id: string;
  title: string;
  updated_at: number;
  message_count: number;
}

export interface TokenStats {
  session_id: string;
  system_tokens: number;
  message_tokens: number;
  total_tokens: number;
}

export interface Skill {
  name: string;
  path: string;
}

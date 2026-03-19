export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export interface ToolArtifactRef {
  path?: string | null;
  label?: string | null;
  artifact_type?: string | null;
  identifier?: string | null;
}

export interface ToolResultError {
  code:
    | "blocked"
    | "invalid_input"
    | "retriable_failure"
    | "execution_failure";
  message: string;
  retriable: boolean;
}

export interface ToolResultEnvelope {
  contract_version: string;
  tool_name: string;
  summary: string;
  structured_payload?: JsonValue;
  artifact_refs: ToolArtifactRef[];
  warnings: string[];
  status: "success" | "error";
  outcome:
    | "success"
    | "success_empty"
    | "blocked"
    | "invalid_input"
    | "retriable_failure"
    | "execution_failure";
  error?: ToolResultError | null;
  metadata: { [key: string]: JsonValue };
  source_payload?: JsonValue;
}

export interface ToolCall {
  tool: string;
  input: string;
  output: string;
  run_id?: string;
  result?: ToolResultEnvelope;
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

"""
AgentManager — singleton that owns the LLM, tools, session manager,
and memory indexer. Rebuilds the agent on every request via create_agent
so that live workspace edits are always reflected in the system prompt.
"""
import os
from pathlib import Path
from typing import AsyncGenerator, Optional

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_deepseek import ChatDeepSeek

from .memory_indexer import MemoryIndexer
from .prompt_builder import build_system_prompt
from .session_manager import SessionManager

# Tool name -> single arg name for replayed tool_calls (session stores flat "input" string)
_TOOL_ARG_KEY: dict[str, str] = {
    "terminal": "command",
    "python_repl": "code",
    "fetch_url": "url",
    "read_file": "path",
    "search_knowledge_base": "query",
}


class AgentManager:
    def __init__(self) -> None:
        self.llm: Optional[ChatDeepSeek] = None
        self.tools: list = []
        self.session_manager: Optional[SessionManager] = None
        self.memory_indexer: Optional[MemoryIndexer] = None
        self.base_dir: Optional[Path] = None

    # ------------------------------------------------------------------ #
    # Initialisation                                                       #
    # ------------------------------------------------------------------ #

    def initialize(self, base_dir: Path) -> None:
        self.base_dir = base_dir

        self.llm = ChatDeepSeek(
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            temperature=0.7,
            streaming=True,
        )

        from tools import get_all_tools

        self.tools = get_all_tools(base_dir)
        self.session_manager = SessionManager(base_dir)
        self.memory_indexer = MemoryIndexer(base_dir)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _build_messages(self, history: list[dict]) -> list:
        """Convert session history dicts to LangChain message objects.
        Preserves tool_calls and tool results so the LLM sees full turn structure.
        """
        messages = []
        for msg in history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                tool_calls = msg.get("tool_calls") or []
                if tool_calls:
                    lc_tool_calls = []
                    tool_outputs = []
                    for i, tc in enumerate(tool_calls):
                        cid = f"call_{len(messages)}_{i}"
                        name = tc.get("tool", "")
                        arg_key = _TOOL_ARG_KEY.get(name, "input")
                        lc_tool_calls.append({
                            "id": cid,
                            "name": name,
                            "args": {arg_key: tc.get("input", "")},
                        })
                        tool_outputs.append((cid, tc.get("output", "")))
                    messages.append(AIMessage(content=content, tool_calls=lc_tool_calls))
                    for cid, output in tool_outputs:
                        messages.append(ToolMessage(content=output, tool_call_id=cid))
                else:
                    messages.append(AIMessage(content=content))
        return messages

    def _build_agent(self, rag_mode: bool = False):
        """
        Rebuild the agent from scratch, ensuring the latest workspace edits
        and RAG configuration are reflected in the system prompt.
        """
        assert self.base_dir is not None, "AgentManager not initialised"
        system_prompt = build_system_prompt(self.base_dir, rag_mode)
        return create_agent(self.llm, self.tools, system_prompt=system_prompt)

    # ------------------------------------------------------------------ #
    # Streaming                                                            #
    # ------------------------------------------------------------------ #

    async def astream(
        self, message: str, history: list[dict]
    ) -> AsyncGenerator[dict, None]:
        """
        Core streaming generator. Yields typed event dicts:

          retrieval    — RAG results before the agent runs
          token        — streaming LLM text token
          tool_start   — agent is about to call a tool
          tool_end     — tool finished
          new_response — agent started a new text segment after tool use
          done         — agent finished the full turn
          error        — unhandled exception
        """
        from config import get_rag_mode

        assert self.base_dir is not None, "AgentManager not initialised"

        rag_mode = get_rag_mode()

        # ── RAG injection ──────────────────────────────────────────────
        if rag_mode and self.memory_indexer:
            try:
                results = self.memory_indexer.retrieve(message)
                if results:
                    yield {"type": "retrieval", "query": message, "results": results}
                    context_lines = "\n".join(f"- {r['text']}" for r in results)
                    rag_block = f"[Retrieved Memory]\n{context_lines}"
                    # Injected as a temporary assistant message (not persisted)
                    history = history + [{"role": "assistant", "content": rag_block}]
            except Exception:
                pass  # RAG failure is non-fatal

        # ── Build message list ─────────────────────────────────────────
        lc_messages = (
            self._build_messages(history)
            + [HumanMessage(content=message)]
        )

        # ── Build agent (rebuilt every request) ───────────────────────
        agent = self._build_agent(rag_mode)

        # ── Stream events ──────────────────────────────────────────────
        after_tool = False

        try:
            async for event in agent.astream_events(
                {"messages": lc_messages}, version="v2"
            ):
                kind = event["event"]

                if kind == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    if chunk.content:
                        if after_tool:
                            yield {"type": "new_response"}
                            after_tool = False
                        yield {"type": "token", "content": chunk.content}

                elif kind == "on_tool_start":
                    run_id = event["run_id"]
                    tool_name = event["name"]
                    raw_input = event["data"].get("input", {})

                    # Flatten single-key dict inputs for readability
                    if isinstance(raw_input, dict) and len(raw_input) == 1:
                        tool_input_str = str(next(iter(raw_input.values())))
                    else:
                        tool_input_str = str(raw_input)

                    yield {
                        "type": "tool_start",
                        "tool": tool_name,
                        "input": tool_input_str,
                        "run_id": run_id,
                    }

                elif kind == "on_tool_end":
                    run_id = event["run_id"]
                    raw_output = event["data"].get("output", "")
                    # Output may be a ToolMessage object in some LangGraph versions
                    if hasattr(raw_output, "content"):
                        tool_output_str = raw_output.content
                    else:
                        tool_output_str = str(raw_output)

                    yield {
                        "type": "tool_end",
                        "tool": event["name"],
                        "output": tool_output_str,
                        "run_id": run_id,
                    }
                    after_tool = True

        except Exception as exc:
            yield {"type": "error", "error": str(exc)}
            return

        yield {"type": "done"}


# Module-level singleton
agent_manager = AgentManager()

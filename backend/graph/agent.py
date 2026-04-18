"""
AgentManager — singleton that owns the LLM, tools, session manager,
and memory indexer. Rebuilds the agent on every request via create_agent
so that live workspace edits are always reflected in the system prompt.
"""
from pathlib import Path
from typing import AsyncGenerator, Optional

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from config import get_agent_runtime_limit
from runtime.model_factory import build_chat_model
from .memory_indexer import MemoryIndexer
from .prompt_builder import build_retrieved_memory_block, build_system_prompt
from .session_manager import SessionManager
from .skill_router import select_skill_entries_for_query
from tools.contracts import normalize_tool_output

_HARNESS_GUIDANCE = """
<!-- Runtime Harness Guidance -->
For non-trivial tasks, use the helper-agent tools deliberately:
- Call `plan_agent` before broad multi-step tool use when you need to decide the order of work.
- Use the returned plan to guide tool choice and sequencing.
- After a draft answer for non-trivial, tool-backed, or higher-risk work, call `verification_agent` to challenge the result before responding.
- Skip verification for small conversational turns or obviously complete low-risk answers where a repair pass would add little user value.
- If verification reports `repair_required` or `fail`, fix the material issues before finalizing your answer.
""".strip()


class AgentManager:
    def __init__(self) -> None:
        self.llm = None
        self.planner_llm = None
        self.verifier_llm = None
        self.title_llm = None
        self.tools: list = []
        self.session_manager: Optional[SessionManager] = None
        self.memory_indexer: Optional[MemoryIndexer] = None
        self.base_dir: Optional[Path] = None

    # ------------------------------------------------------------------ #
    # Initialisation                                                       #
    # ------------------------------------------------------------------ #

    def initialize(self, base_dir: Path) -> None:
        self.base_dir = base_dir

        self.llm = build_chat_model("executor", streaming=True)
        self.planner_llm = build_chat_model("planner", streaming=True)
        self.verifier_llm = build_chat_model("verifier", streaming=True)
        self.title_llm = build_chat_model("title", streaming=False)

        from tools import get_runtime_tools

        self.tools = get_runtime_tools(base_dir)
        self.session_manager = SessionManager(base_dir)
        self.memory_indexer = MemoryIndexer(base_dir)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _build_messages(self, history: list[dict]) -> list:
        """Convert session history dicts to LangChain message objects."""
        messages = []
        for msg in history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
            elif role == "system":
                # Used for injected context such as RAG-retrieved memory
                messages.append(SystemMessage(content=content))
        return messages

    def _build_agent(
        self,
        rag_mode: bool = False,
        *,
        skill_entries: list[dict] | None = None,
    ):
        """
        Rebuild the agent from scratch, ensuring the latest workspace edits
        and RAG configuration are reflected in the system prompt.
        """
        assert self.base_dir is not None, "AgentManager not initialised"
        system_prompt = (
            f"{build_system_prompt(self.base_dir, rag_mode, skill_entries=skill_entries)}"
            f"\n\n{_HARNESS_GUIDANCE}"
        )
        return create_agent(self.llm, self.tools, system_prompt=system_prompt)

    def clear_session_runtime(self, session_id: str) -> None:
        for tool in self.tools:
            runtime_tool = getattr(tool, "wrapped_tool", tool)
            clear_session_state = getattr(runtime_tool, "clear_session_state", None)
            if callable(clear_session_state):
                clear_session_state(session_id)

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
          tool_end     — tool finished (legacy output string plus structured result)
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
                results = self.memory_indexer.retrieve(message, top_k=3)
                if results:
                    yield {"type": "retrieval", "query": message, "results": results}
                    rag_block = build_retrieved_memory_block(results)
                    # Injected as a system message so the model treats this as
                    # provided context, not as something it previously said.
                    if rag_block:
                        history = history + [{"role": "system", "content": rag_block}]
            except Exception:
                pass  # RAG failure is non-fatal

        # ── Build message list ─────────────────────────────────────────
        lc_messages = (
            self._build_messages(history)
            + [HumanMessage(content=message)]
        )

        # ── Build agent (rebuilt every request) ───────────────────────
        selected_skill_entries = select_skill_entries_for_query(
            self.base_dir,
            message,
            history=history,
        )
        # Share the routed skill set with the in-flight policy context so
        # `tools_allowed` can be enforced at dispatch time.
        from tools.policy import set_active_skills_on_current_context

        set_active_skills_on_current_context(selected_skill_entries)
        agent = self._build_agent(rag_mode, skill_entries=selected_skill_entries)

        # ── Stream events ──────────────────────────────────────────────
        after_tool = False

        # Biology requests with retrieval and multi-step reasoning often need
        # far more graph turns than LangGraph's small default budget.
        run_config = {
            "recursion_limit": get_agent_runtime_limit(
                "executor_recursion_limit",
                1000,
            )
        }
        try:
            async for event in agent.astream_events(
                {"messages": lc_messages},
                version="v2",
                config=run_config,
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
                    result = normalize_tool_output(event["name"], raw_output)
                    raw_input = event["data"].get("input", {})
                    if isinstance(raw_input, dict) and len(raw_input) == 1:
                        tool_input_str = str(next(iter(raw_input.values())))
                    else:
                        tool_input_str = str(raw_input)

                    result_dict = result.model_dump(mode="json")
                    policy = result.metadata.get("policy")
                    policy_dict = policy if isinstance(policy, dict) else None

                    if result.outcome == "needs_approval":
                        approval_message = (
                            result.error.message
                            if result.error is not None
                            else result.summary
                        )
                        approval_reason = (
                            policy_dict.get("approval_reason")
                            if isinstance(policy_dict, dict)
                            else None
                        ) or "requires_approval"
                        payload = {
                            "type": "tool_awaiting_approval",
                            "tool": event["name"],
                            "input": tool_input_str,
                            "run_id": run_id,
                            "reason": approval_reason,
                            "message": approval_message,
                            "result": result_dict,
                        }
                        if policy_dict is not None:
                            payload["policy"] = policy_dict
                        yield payload
                        after_tool = True
                        continue

                    payload = {
                        "type": "tool_end",
                        "tool": event["name"],
                        "output": result.summary,
                        "result": result_dict,
                        "run_id": run_id,
                    }
                    if policy_dict is not None:
                        payload["policy"] = policy_dict
                    yield payload
                    after_tool = True

        except Exception as exc:
            yield {"type": "error", "error": str(exc)}
            return

        yield {"type": "done"}


# Module-level singleton
agent_manager = AgentManager()

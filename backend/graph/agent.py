"""
AgentManager — singleton that owns the LLM, tools, session manager,
and memory indexer. Rebuilds the agent on every request via create_agent
so that live workspace edits are always reflected in the system prompt.
"""
import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from config import get_agent_runtime_limit, get_max_sections_per_file
from evidence.integrity import (
    build_citation_mismatch_event,
    check_citation_integrity,
)
from runtime.model_factory import build_chat_model, build_fallback_chat_model, get_role_model_config
from runtime.model_fallback import is_overload_or_timeout
from audit.store import append_audit_event
from .memory_indexer import MemoryIndexer
from .prompt_builder import build_retrieved_memory_block, build_system_prompt_blocks
from .session_manager import SessionManager
from .skill_router import select_skill_entries_for_query
from tools.contracts import normalize_tool_output

logger = logging.getLogger(__name__)


def _extract_llm_usage_event(event: dict) -> dict | None:
    """Map a LangChain ``on_chat_model_end`` event to an ``llm_usage`` runtime
    event so the metrics collector can track provider-side prompt-cache usage.

    LangChain normalizes cache accounting across DeepSeek / OpenAI / Anthropic
    into ``AIMessage.usage_metadata`` with an optional ``input_token_details``
    dict carrying ``cache_read`` and ``cache_creation``. If the response has
    no usage metadata (some streamed runs) we skip — the collector only needs
    samples, not a per-call invariant.
    """
    output = event.get("data", {}).get("output")
    usage = getattr(output, "usage_metadata", None)
    if not isinstance(usage, dict):
        return None
    input_tokens = int(usage.get("input_tokens") or 0)
    details = usage.get("input_token_details") or {}
    if not isinstance(details, dict):
        details = {}
    cache_read = int(details.get("cache_read") or 0)
    cache_creation = int(details.get("cache_creation") or 0)
    if input_tokens <= 0 and cache_read <= 0 and cache_creation <= 0:
        return None
    return {
        "type": "llm_usage",
        "input_tokens": input_tokens,
        "cache_read_tokens": cache_read,
        "cache_creation_tokens": cache_creation,
    }

def _role_config_hash(
    llm: Any,
    tool_names: tuple[str, ...],
    system_prompt: str,
) -> str:
    """Digest the inputs to ``create_agent`` that change the built runnable.

    The llm is identified by ``id()``; AgentManager holds the primary executor
    on ``self.llm`` for the session, so identity is stable across turns. A
    swapped-in fallback llm has a different id, which is why fallback builds
    bypass the cache via ``use_cache=False``.
    """
    parts = [
        str(id(llm)),
        "\x1f".join(tool_names),
        system_prompt,
    ]
    return hashlib.sha256("\x1e".join(parts).encode("utf-8")).hexdigest()


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
        # Per-session cache of built agents. Keyed by ``(session_id,
        # role_config_hash)`` so distinct config hashes for the same session
        # cannot clobber each other mid-write. The cache is still capped at
        # one entry per session_id (see ``_build_agent``): when a build uses
        # a new hash, any prior entry for that session is evicted to avoid
        # unbounded growth across long-lived sessions that swap roles.
        # Fallback-LLM builds intentionally bypass this cache so they do not
        # evict the primary entry.
        self._agent_cache: dict[tuple[str, str], Any] = {}
        # Serializes concurrent cache reads/writes when turns from different
        # sessions race inside _build_agent. Under single-threaded asyncio,
        # dict get/set don't yield, so true corruption is unlikely; the lock
        # hardens the invariant and makes future async additions safe.
        self._cache_lock: asyncio.Lock = asyncio.Lock()

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
        self.memory_indexer = MemoryIndexer(
            base_dir, max_sections_per_file=get_max_sections_per_file()
        )

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

    async def _build_agent(
        self,
        rag_mode: bool = False,
        *,
        skill_entries: list[dict] | None = None,
        llm: Any = None,
        session_id: str | None = None,
        use_cache: bool = True,
    ):
        """
        Return (possibly cached) agent, rebuilding when any input that changes
        the runnable — llm identity, tool names, or assembled system prompt —
        has changed since the last build for this session.

        The stable prefix half of the prompt (workspace files, skill snapshot,
        tool-result contract, harness guidance) is frozen on the session on
        first call so sub-agent runs can reuse it for provider prompt-cache
        hits. The volatile suffix (memory index, git context) is appended
        fresh each turn and is intentionally excluded from the frozen prefix.
        """
        assert self.base_dir is not None, "AgentManager not initialised"
        stable_prefix, volatile_suffix = build_system_prompt_blocks(
            self.base_dir,
            rag_mode,
            skill_entries=skill_entries,
        )
        stable_prefix_with_harness = (
            f"{stable_prefix}\n\n{_HARNESS_GUIDANCE}" if stable_prefix else _HARNESS_GUIDANCE
        )
        tool_names = tuple(
            getattr(tool, "name", type(tool).__name__) for tool in self.tools
        )
        if session_id and self.session_manager is not None:
            self.session_manager.freeze_session_prefix(
                session_id,
                stable_prefix=stable_prefix_with_harness,
                tool_names=tool_names,
            )
        if stable_prefix_with_harness and volatile_suffix:
            system_prompt = f"{stable_prefix_with_harness}\n\n{volatile_suffix}"
        else:
            system_prompt = stable_prefix_with_harness or volatile_suffix

        effective_llm = llm or self.llm

        if use_cache and session_id:
            role_config_hash = _role_config_hash(
                effective_llm, tool_names, system_prompt
            )
            key = (session_id, role_config_hash)
            async with self._cache_lock:
                cached = self._agent_cache.get(key)
                if cached is not None:
                    return cached
                agent = create_agent(
                    effective_llm, self.tools, system_prompt=system_prompt
                )
                # Cap at one entry per session_id: drop any stale entry for
                # this session that used a different role_config_hash.
                stale_keys = [
                    k for k in self._agent_cache
                    if k[0] == session_id and k != key
                ]
                for stale in stale_keys:
                    self._agent_cache.pop(stale, None)
                self._agent_cache[key] = agent
                return agent

        return create_agent(effective_llm, self.tools, system_prompt=system_prompt)

    async def _run_llm_probe_retrieval(
        self,
        *,
        query: str,
        session_id: str | None,
        max_payload_chars: int,
    ) -> list[dict]:
        """Ask the executor LLM to pick relevant memory files for ``query``.

        Returns retrieval results in the same shape as ``MemoryIndexer.retrieve``
        so the caller can render them through ``build_retrieved_memory_block``.
        Returns ``[]`` on any failure so the caller falls back to keyword RAG.
        """
        indexer = self.memory_indexer
        if indexer is None or self.llm is None:
            return []
        corpus_digest = indexer.memory_corpus_digest()
        if session_id:
            cached = indexer.get_cached_probe_selection(session_id, corpus_digest)
            if cached:
                return indexer.build_probe_results(cached)
        index_body, valid_sources = indexer.build_probe_index(
            max_chars=max_payload_chars
        )
        if not valid_sources:
            return []
        probe_prompt = (
            "You are selecting which long-term memory files are relevant to answering "
            "a user query. Respond ONLY with a JSON array of source paths (strings) "
            "chosen from the provided list. Pick at most 5, sorted most-relevant first. "
            "Return an empty array if nothing is relevant.\n\n"
            f"User query:\n{query.strip()}\n\n"
            f"Available memory files:\n{index_body}\n\n"
            'Respond with JSON only, e.g. ["memory/project/foo.md"].'
        )
        try:
            response = await self.llm.ainvoke([HumanMessage(content=probe_prompt)])
        except Exception:
            logger.debug("llm_probe invocation failed", exc_info=True)
            return []
        content = getattr(response, "content", "")
        if isinstance(content, list):
            # Some providers return a list of content blocks.
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        if not isinstance(content, str) or not content.strip():
            return []
        picked = indexer.parse_probe_selection(content, valid_sources)
        if not picked:
            return []
        if session_id:
            indexer.cache_probe_selection(session_id, corpus_digest, picked)
        return indexer.build_probe_results(picked)

    def clear_session_runtime(self, session_id: str) -> None:
        # Drop every cache entry for this session regardless of
        # role_config_hash. Called from sync FastAPI handlers, so we can't
        # ``await`` the asyncio.Lock — dict pops are atomic under CPython,
        # and the cap-at-one invariant means at most one entry exists.
        stale_keys = [k for k in list(self._agent_cache) if k[0] == session_id]
        for key in stale_keys:
            self._agent_cache.pop(key, None)
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
        from config import (
            RAG_MODE_LLM_PROBE,
            get_llm_probe_max_chars,
            get_llm_probe_min_files,
            get_rag_mode,
            get_rag_mode_name,
        )

        assert self.base_dir is not None, "AgentManager not initialised"

        # ``get_rag_mode()`` stays the on/off gate (preserves existing patch
        # points) while ``get_rag_mode_name()`` decides which retrieval variant
        # runs when the gate is on.
        rag_mode = get_rag_mode()
        rag_mode_name = get_rag_mode_name() if rag_mode else "off"

        # ── RAG injection ──────────────────────────────────────────────
        if rag_mode and self.memory_indexer:
            from runtime.metrics_collector import METRICS
            from tools.policy import get_tool_policy_context as _get_tool_policy_context

            policy_context = _get_tool_policy_context()
            session_id_for_probe = (
                policy_context.session_id if policy_context is not None else None
            )
            results: list[dict] = []
            retrieval_source = "keyword"
            try:
                if rag_mode_name == RAG_MODE_LLM_PROBE and (
                    self.memory_indexer.memory_file_count()
                    >= get_llm_probe_min_files()
                ):
                    results = await self._run_llm_probe_retrieval(
                        query=message,
                        session_id=session_id_for_probe,
                        max_payload_chars=get_llm_probe_max_chars(),
                    )
                    retrieval_source = "llm_probe" if results else "llm_probe_fallback_keyword"
                if not results:
                    results = self.memory_indexer.retrieve(message, top_k=3)
                if results:
                    yield {
                        "type": "retrieval",
                        "query": message,
                        "results": results,
                        "mode": retrieval_source,
                    }
                    rag_block = build_retrieved_memory_block(results)
                    # Injected as a system message so the model treats this as
                    # provided context, not as something it previously said.
                    if rag_block:
                        history = history + [{"role": "system", "content": rag_block}]
                else:
                    METRICS.observe_retrieval(hit=False)
            except Exception as exc:
                # RAG failure is non-fatal — the turn still runs without
                # retrieved memory, but the reviewer needs to see the failure
                # instead of the old silent swallow (issue #115).
                error_type = type(exc).__name__
                logger.exception(
                    "retrieval_error: memory_indexer.retrieve raised for query=%r (%s)",
                    message,
                    error_type,
                )
                METRICS.observe_retrieval(hit=False)
                METRICS.observe_retrieval_error(error_type=error_type)
                yield {
                    "type": "retrieval_error",
                    "query": message,
                    "error_type": error_type,
                    "message": str(exc),
                }

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
        from tools.policy import get_tool_policy_context, set_active_skills_on_current_context

        set_active_skills_on_current_context(selected_skill_entries)
        policy_context = get_tool_policy_context()
        session_id = policy_context.session_id if policy_context is not None else None
        agent = await self._build_agent(
            rag_mode,
            skill_entries=selected_skill_entries,
            session_id=session_id,
        )

        # ── Stream events ──────────────────────────────────────────────
        after_tool = False
        answer_segments: list[str] = []
        turn_started_at = datetime.now(timezone.utc)
        streamed_any_event = False
        used_fallback = False

        # Biology requests with retrieval and multi-step reasoning often need
        # far more graph turns than LangGraph's small default budget.
        run_config = {
            "recursion_limit": get_agent_runtime_limit(
                "executor_recursion_limit",
                1000,
            )
        }
        # Outer primary->fallback loop: if the primary executor model raises
        # an overload/timeout error before any event has been yielded, swap
        # in the role's configured fallback_model once per turn. The inner
        # stream is unchanged; verification/repair retries remain in
        # ``runtime/query_engine.py`` and are intentionally not merged here.
        while True:
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
                            if isinstance(chunk.content, str):
                                answer_segments.append(chunk.content)
                            streamed_any_event = True
                            yield {"type": "token", "content": chunk.content}

                    elif kind == "on_chat_model_end":
                        usage_event = _extract_llm_usage_event(event)
                        if usage_event is not None:
                            streamed_any_event = True
                            yield usage_event

                    elif kind == "on_tool_start":
                        run_id = event["run_id"]
                        tool_name = event["name"]
                        raw_input = event["data"].get("input", {})

                        # Flatten single-key dict inputs for readability
                        if isinstance(raw_input, dict) and len(raw_input) == 1:
                            tool_input_str = str(next(iter(raw_input.values())))
                        else:
                            tool_input_str = str(raw_input)

                        streamed_any_event = True
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
                            # Hard-stop the turn: the agent must not keep reasoning over a
                            # gated ToolMessage, since that would either loop on the same
                            # gate or paper over the human decision. The reviewer resumes
                            # the turn via POST /api/chat/approval + a follow-up /api/chat.
                            yield {"type": "done", "turn_status": "awaiting_approval"}
                            return

                        payload = {
                            "type": "tool_end",
                            "tool": event["name"],
                            "output": result.summary,
                            "result": result_dict,
                            "run_id": run_id,
                        }
                        if policy_dict is not None:
                            payload["policy"] = policy_dict
                        streamed_any_event = True
                        yield payload
                        after_tool = True
                break

            except asyncio.CancelledError:
                # Cancellation must propagate verbatim so it reaches in-flight
                # async tools as a CancelledError at their next await point.
                # Catching and converting it to an "error" event would silently
                # turn a client disconnect into a normal turn failure and would
                # leave the cancelled tool task uncancelled.
                raise
            except Exception as exc:
                if (
                    not used_fallback
                    and not streamed_any_event
                    and is_overload_or_timeout(exc)
                ):
                    fallback_llm = build_fallback_chat_model(
                        "executor", streaming=True
                    )
                    if fallback_llm is not None:
                        self._record_model_fallback(
                            role="executor",
                            exc=exc,
                        )
                        agent = await self._build_agent(
                            rag_mode,
                            skill_entries=selected_skill_entries,
                            llm=fallback_llm,
                            session_id=session_id,
                            use_cache=False,
                        )
                        used_fallback = True
                        after_tool = False
                        answer_segments = []
                        continue
                yield {"type": "error", "error": str(exc)}
                return

        warning_event = self._maybe_build_citation_warning(
            "".join(answer_segments),
            turn_started_at=turn_started_at,
        )
        if warning_event is not None:
            yield warning_event

        yield {"type": "done"}

    def _record_model_fallback(self, *, role: str, exc: BaseException) -> None:
        """Emit an audit line when a primary model is swapped for its fallback."""
        try:
            primary_cfg = get_role_model_config(role, streaming=True)  # type: ignore[arg-type]
        except Exception:  # pragma: no cover — defensive
            primary_cfg = None
        primary_model = getattr(primary_cfg, "model", "") or ""
        fallback_model = getattr(primary_cfg, "fallback_model", "") or ""
        summary = (
            f"Primary {role} model '{primary_model}' fell back to '{fallback_model}' "
            f"after {type(exc).__name__}."
        )
        try:
            append_audit_event(
                self.base_dir,
                event_type="model_fallback",
                summary=summary,
                outcome="fallback",
                details={
                    "role": role,
                    "primary_model": primary_model,
                    "fallback_model": fallback_model,
                    "exception_class": type(exc).__name__,
                    "exception_message": str(exc)[:500],
                },
            )
        except Exception:  # pragma: no cover — audit must never abort the turn
            logger.warning("Failed to append model_fallback audit event", exc_info=True)

    def _maybe_build_citation_warning(
        self,
        answer_text: str,
        *,
        turn_started_at: datetime,
    ) -> dict | None:
        """Run the citation-integrity check; return a warning event on mismatch."""
        if self.base_dir is None or not answer_text:
            return None
        try:
            result = check_citation_integrity(
                self.base_dir,
                answer_text,
                turn_started_at=turn_started_at,
            )
        except Exception:  # pragma: no cover - defensive
            logger.debug("citation integrity check raised", exc_info=True)
            return None
        if result is None or not result.has_mismatch:
            return None
        logger.warning(
            "citation_mismatch: answer cites PMIDs %s missing from evidence_review %s",
            result.missing_pmids,
            result.review_artifact_relpath,
        )
        return build_citation_mismatch_event(result)


# Module-level singleton
agent_manager = AgentManager()

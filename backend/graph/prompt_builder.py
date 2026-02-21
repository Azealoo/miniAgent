from pathlib import Path

MAX_COMPONENT_CHARS = 20_000

_RAG_MEMORY_GUIDANCE = (
    "<!-- Long-term Memory -->\n"
    "Your long-term memory is managed via RAG (Retrieval-Augmented Generation). "
    "Relevant memories will be dynamically retrieved and injected as context before each response. "
    "You do not need to recall all memories yourself — trust the retrieved context provided to you."
)


def _read_component(path: Path) -> str:
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8").strip()
    if len(content) > MAX_COMPONENT_CHARS:
        content = content[:MAX_COMPONENT_CHARS] + "\n...[truncated]"
    return content


def build_system_prompt(base_dir: Path, rag_mode: bool = False) -> str:
    """
    Assemble the system prompt from 6 ordered components.
    Each component is wrapped in an HTML comment tag for easy debugging.
    Components exceeding MAX_COMPONENT_CHARS are truncated.
    """
    parts: list[str] = []

    # 1. Skills Snapshot
    snap = _read_component(base_dir / "SKILLS_SNAPSHOT.md")
    if snap:
        parts.append(f"<!-- Skills Snapshot -->\n{snap}")

    # 2. Soul
    soul = _read_component(base_dir / "workspace" / "SOUL.md")
    if soul:
        parts.append(f"<!-- Soul -->\n{soul}")

    # 3. Identity
    identity = _read_component(base_dir / "workspace" / "IDENTITY.md")
    if identity:
        parts.append(f"<!-- Identity -->\n{identity}")

    # 4. User Profile
    user = _read_component(base_dir / "workspace" / "USER.md")
    if user:
        parts.append(f"<!-- User Profile -->\n{user}")

    # 5. Agents Guide
    agents = _read_component(base_dir / "workspace" / "AGENTS.md")
    if agents:
        parts.append(f"<!-- Agents Guide -->\n{agents}")

    # 6. Memory — full file or RAG guidance
    if rag_mode:
        parts.append(_RAG_MEMORY_GUIDANCE)
    else:
        memory = _read_component(base_dir / "memory" / "MEMORY.md")
        if memory:
            parts.append(f"<!-- Long-term Memory -->\n{memory}")

    return "\n\n".join(parts)

"""
Observability layer for LGTM's LLM calls.

Provides a thin wrapper around Anthropic SDK calls that:
- Always collects local TraceSpan records (zero-dependency)
- Sends traces to LangSmith when LANGSMITH_API_KEY is set
- Gracefully degrades to local-only when LangSmith is unavailable

All langsmith imports happen inside functions to satisfy Temporal's
workflow sandbox restrictions (no module-level side effects).
"""
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, Any


@dataclass
class TraceSpan:
    """Lightweight local trace record."""
    name: str
    span_type: str  # "llm", "tool", "chain"
    start_time: float = 0.0
    end_time: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    metadata: dict = field(default_factory=dict)
    error: Optional[str] = None

    @property
    def duration_ms(self) -> float:
        return (self.end_time - self.start_time) * 1000

    def to_dict(self) -> dict:
        d = asdict(self)
        d["duration_ms"] = self.duration_ms
        return d


def is_langsmith_enabled() -> bool:
    """Check if LangSmith tracing is configured."""
    return bool(os.environ.get("LANGSMITH_API_KEY"))


def traced_anthropic_call(
    client,
    *,
    span_name: str,
    metadata: Optional[dict] = None,
    **create_kwargs,
):
    """
    Wrapper around client.messages.create that adds tracing.

    When LANGSMITH_API_KEY is set, creates a LangSmith RunTree span.
    Always returns a local TraceSpan for in-process collection.

    Args:
        client: anthropic.Anthropic instance
        span_name: Human-readable name for this trace span
        metadata: Extra key-value pairs to attach to the trace
        **create_kwargs: Forwarded to client.messages.create()

    Returns:
        (response, TraceSpan) tuple
    """
    meta = metadata or {}
    span = TraceSpan(
        name=span_name,
        span_type="llm",
        model=create_kwargs.get("model", "unknown"),
        start_time=time.time(),
        metadata=meta,
    )

    rt = None
    if is_langsmith_enabled():
        try:
            from langsmith.run_trees import RunTree

            rt = RunTree(
                name=span_name,
                run_type="llm",
                inputs={
                    "model": create_kwargs.get("model"),
                    "max_tokens": create_kwargs.get("max_tokens"),
                    "temperature": create_kwargs.get("temperature"),
                    "tools": [t["name"] for t in create_kwargs.get("tools", [])],
                    "messages": _sanitize_messages(create_kwargs.get("messages", [])),
                },
                extra={"metadata": {
                    **meta,
                    "ls_provider": "anthropic",
                    "ls_model_name": create_kwargs.get("model", ""),
                }},
            )
        except Exception:
            # If LangSmith setup fails, continue without it
            rt = None

    try:
        response = client.messages.create(**create_kwargs)

        span.end_time = time.time()
        span.input_tokens = response.usage.input_tokens
        span.output_tokens = response.usage.output_tokens

        if rt is not None:
            try:
                rt.end(
                    outputs={
                        "stop_reason": response.stop_reason,
                        "content_types": [b.type for b in response.content],
                        "tool_calls": [
                            {"name": b.name, "id": b.id}
                            for b in response.content
                            if b.type == "tool_use"
                        ],
                    },
                )
                rt.set(usage_metadata={
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
                })
                rt.post()
            except Exception:
                pass  # Never let tracing failures break the review

        return response, span

    except Exception as e:
        span.end_time = time.time()
        span.error = str(e)
        if rt is not None:
            try:
                rt.end(error=str(e))
                rt.post()
            except Exception:
                pass
        raise


def _sanitize_messages(messages: list) -> list:
    """
    Reduce message payload for trace storage.
    Truncates large tool results and message bodies to avoid bloating traces.
    """
    sanitized = []
    for msg in messages:
        content = msg.get("content")

        # Tool result messages (list of blocks)
        if isinstance(content, list):
            blocks = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    raw = block.get("content", "")
                    blocks.append({
                        "type": "tool_result",
                        "tool_use_id": block.get("tool_use_id"),
                        "content_length": len(raw),
                        "content_preview": (raw[:200] + "...") if len(raw) > 200 else raw,
                    })
                else:
                    blocks.append(block)
            sanitized.append({"role": msg.get("role"), "content": blocks})

        # Large string messages
        elif isinstance(content, str) and len(content) > 500:
            sanitized.append({
                "role": msg.get("role"),
                "content_length": len(content),
                "content_preview": content[:500] + "...",
            })
        else:
            sanitized.append(msg)

    return sanitized

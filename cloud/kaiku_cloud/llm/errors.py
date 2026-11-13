class LlmUnavailable(RuntimeError):
    """The selected LLM backend can't answer right now; callers fall back to the template."""

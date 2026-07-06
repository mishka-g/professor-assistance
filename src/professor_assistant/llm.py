"""Unified LLM interface with a pluggable backend: api | local | mock.

- api   : the professor's paid subscription (OpenAI or Anthropic) - best quality.
- local : Ollama on this Mac - free, private.
- mock  : no model; callers fall back to heuristics. `complete()` is unavailable.
"""

from __future__ import annotations

from .config import get_settings


class BackendUnavailable(RuntimeError):
    pass


def backend() -> str:
    return get_settings().model_backend.lower().strip()


def complete(system: str, user: str, *, temperature: float = 0.2, max_tokens: int = 4000) -> str:
    """Return a completion string. Raises BackendUnavailable for the mock backend."""
    b = backend()
    if b == "api":
        return _complete_api(system, user, temperature, max_tokens)
    if b == "local":
        return _complete_ollama(system, user, temperature, max_tokens)
    raise BackendUnavailable(
        "MODEL_BACKEND=mock has no text model. Set MODEL_BACKEND=local (Ollama) "
        "or MODEL_BACKEND=api (with an API key) for LLM-quality output."
    )


def _complete_api(system: str, user: str, temperature: float, max_tokens: int) -> str:
    settings = get_settings()
    provider = settings.api_provider.lower().strip()

    if provider == "openai":
        if not settings.openai_api_key:
            raise BackendUnavailable("OPENAI_API_KEY is not set.")
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        resp = client.chat.completions.create(
            model=settings.api_model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or ""

    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise BackendUnavailable("ANTHROPIC_API_KEY is not set.")
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model=settings.api_model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in resp.content if block.type == "text")

    raise BackendUnavailable(f"Unknown API_PROVIDER: {provider}")


def _complete_ollama(system: str, user: str, temperature: float, max_tokens: int) -> str:
    import requests

    settings = get_settings()
    url = f"{settings.ollama_host.rstrip('/')}/api/chat"
    payload = {
        "model": settings.local_llm,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    try:
        resp = requests.post(url, json=payload, timeout=600)
        resp.raise_for_status()
    except Exception as exc:
        raise BackendUnavailable(
            f"Could not reach Ollama at {settings.ollama_host} ({exc}). "
            f"Is `ollama serve` running and is '{settings.local_llm}' pulled?"
        ) from exc
    return resp.json().get("message", {}).get("content", "")

"""Pluggable language-model transports.

One registry, one call signature, several vendors. A planner or an explainer takes
a ``call_fn`` of ``(model, system, prompt) -> str`` and never learns which company
answered it (R11). Switching provider is a configuration change.

Transport is stdlib ``urllib``, matching :mod:`kasflex.data.sources`. Vendor SDKs
are large, version-sensitive and would make the offline replay path depend on
packages a reviewer may not have. The request bodies here follow each vendor's
published contract.

Local models are first-class. A grower co-operative that will not send its
operating data to a cloud API can point ``ollama`` at a machine in the office and
every other part of KasFlex behaves identically.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

DEFAULT_TIMEOUT = 120.0
"""Generous: a large local model on CPU is slow, and a timeout here loses a plan."""


class LlmError(RuntimeError):
    """A model could not be reached, or its reply could not be understood."""


@dataclass(frozen=True)
class Provider:
    """One model vendor and what KasFlex needs to know to call it."""

    id: str
    name: str
    models: tuple[str, ...]
    """Suggested models. Any string may be sent; this list only populates the UI."""
    env_var: str = ""
    """Environment variable holding the key. Empty means no key is required."""
    endpoint: str = ""
    help_url: str = ""
    purpose: str = ""
    local: bool = False
    """True for a model that runs on the user's own hardware."""
    base_url_env: str = ""
    """Optional override for self-hosted or proxied deployments."""
    notes: str = ""
    extra_models_allowed: bool = True
    aliases: dict[str, str] = field(default_factory=dict)


PROVIDERS: dict[str, Provider] = {
    "anthropic": Provider(
        id="anthropic",
        name="Anthropic Claude",
        models=("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5-20251001"),
        env_var="ANTHROPIC_API_KEY",
        endpoint="https://api.anthropic.com/v1/messages",
        help_url="https://console.anthropic.com/",
        purpose="Plan generation and grower conversations",
    ),
    "openai": Provider(
        id="openai",
        name="OpenAI",
        models=("gpt-4o", "gpt-4o-mini", "o3-mini"),
        env_var="OPENAI_API_KEY",
        endpoint="https://api.openai.com/v1/chat/completions",
        help_url="https://platform.openai.com/api-keys",
        purpose="Plan generation and grower conversations",
        base_url_env="OPENAI_BASE_URL",
    ),
    "google": Provider(
        id="google",
        name="Google Gemini",
        models=("gemini-2.0-flash", "gemini-1.5-pro"),
        env_var="GEMINI_API_KEY",
        endpoint="https://generativelanguage.googleapis.com/v1beta",
        help_url="https://aistudio.google.com/app/apikey",
        purpose="Plan generation and grower conversations",
    ),
    "ollama": Provider(
        id="ollama",
        name="Ollama (on this computer)",
        models=("llama3.1", "mistral", "qwen2.5"),
        endpoint="http://localhost:11434/api/chat",
        help_url="https://ollama.com/download",
        purpose="Runs on your own hardware. No account, no data leaves the building.",
        local=True,
        base_url_env="OLLAMA_BASE_URL",
        notes="Install Ollama, run `ollama pull llama3.1`, and KasFlex will find it.",
    ),
    "openai-compatible": Provider(
        id="openai-compatible",
        name="Other (OpenAI-compatible)",
        models=(),
        env_var="OPENAI_COMPATIBLE_API_KEY",
        endpoint="",
        help_url="",
        purpose="LM Studio, vLLM, Groq, Together, OpenRouter, or a university endpoint",
        base_url_env="OPENAI_COMPATIBLE_BASE_URL",
        notes="Set the base URL to the server's /v1 root.",
    ),
}

DEFAULT_PROVIDER = "anthropic"


def _post_json(url: str, payload: dict, headers: dict[str, str],
               timeout: float = DEFAULT_TIMEOUT) -> dict:
    """POST JSON and decode the JSON reply, with errors a person can act on."""
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:400]
        except Exception:  # noqa: BLE001 - diagnostics only
            pass
        hint = ""
        if exc.code in (401, 403):
            hint = " The API key looks wrong, expired, or lacks access to this model."
        elif exc.code == 404:
            hint = " The model name is probably not available on this account."
        elif exc.code == 429:
            hint = " Rate limited or out of credit. Wait, or use a different provider."
        raise LlmError(f"{urllib.parse.urlsplit(url).netloc} returned HTTP {exc.code}."
                       f"{hint} Response: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LlmError(
            f"could not reach {urllib.parse.urlsplit(url).netloc}: {exc}. "
            f"Check the network, or the server address if this is a local model."
        ) from exc
    except json.JSONDecodeError as exc:
        raise LlmError(f"{urllib.parse.urlsplit(url).netloc} did not return JSON: {exc}") from exc


def _require_key(provider: Provider, api_key: str | None) -> str:
    key = api_key or os.environ.get(provider.env_var, "")
    if not key:
        raise LlmError(
            f"no API key for {provider.name}. Add one in Configuration > AI model, "
            f"or set {provider.env_var}. Get a key at {provider.help_url}"
        )
    return key


def _base_url(provider: Provider, override: str | None) -> str:
    return (override or os.environ.get(provider.base_url_env, "") or provider.endpoint).rstrip("/")


def _anthropic(model: str, system: str, prompt: str, *, api_key: str | None,
               base_url: str | None, max_tokens: int, timeout: float) -> str:
    provider = PROVIDERS["anthropic"]
    data = _post_json(
        _base_url(provider, base_url),
        {"model": model, "max_tokens": max_tokens, "system": system,
         "messages": [{"role": "user", "content": prompt}]},
        {"x-api-key": _require_key(provider, api_key), "anthropic-version": "2023-06-01"},
        timeout,
    )
    blocks = data.get("content") or []
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    if not text:
        raise LlmError(f"Anthropic returned no text. Stop reason: {data.get('stop_reason')!r}")
    return text


def _openai_style(provider: Provider, model: str, system: str, prompt: str, *,
                  api_key: str | None, base_url: str | None, max_tokens: int,
                  timeout: float) -> str:
    root = _base_url(provider, base_url)
    if not root:
        raise LlmError(f"{provider.name} needs a base URL. Set it in Configuration > AI model.")
    url = root if root.endswith("/chat/completions") else f"{root}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
        "max_completion_tokens": max_tokens,
    }
    headers = {"Authorization": f"Bearer {_require_key(provider, api_key)}"}
    try:
        data = _post_json(url, payload, headers, timeout)
    except LlmError as exc:
        # Servers predating the rename reject max_completion_tokens outright.
        if "max_completion_tokens" not in str(exc):
            raise
        payload.pop("max_completion_tokens")
        payload["max_tokens"] = max_tokens
        data = _post_json(url, payload, headers, timeout)
    choices = data.get("choices") or []
    if not choices:
        raise LlmError(f"{provider.name} returned no choices: {str(data)[:200]}")
    return choices[0].get("message", {}).get("content", "") or ""


def _google(model: str, system: str, prompt: str, *, api_key: str | None,
            base_url: str | None, max_tokens: int, timeout: float) -> str:
    provider = PROVIDERS["google"]
    key = _require_key(provider, api_key)
    root = _base_url(provider, base_url)
    url = f"{root}/models/{urllib.parse.quote(model)}:generateContent?key={urllib.parse.quote(key)}"
    data = _post_json(
        url,
        {"system_instruction": {"parts": [{"text": system}]},
         "contents": [{"role": "user", "parts": [{"text": prompt}]}],
         "generationConfig": {"maxOutputTokens": max_tokens}},
        {},
        timeout,
    )
    candidates = data.get("candidates") or []
    if not candidates:
        raise LlmError(f"Gemini returned no candidates: {str(data.get('promptFeedback'))[:200]}")
    parts = candidates[0].get("content", {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts)


def _ollama(model: str, system: str, prompt: str, *, api_key: str | None,
            base_url: str | None, max_tokens: int, timeout: float,
            fold_system: bool = False) -> str:
    """Call a local model.

    ``fold_system`` merges the system text into the user turn instead of sending
    it as its own message. Several local models -- Mistral derivatives especially
    -- have no system slot in their chat template, so the text is either dropped
    or pasted somewhere the model treats as content to continue rather than
    instruction to follow. GEITje echoed the whole prompt back until it was folded,
    and then produced a correctly-worded rule. Models that do support a system role
    generally do slightly better without folding, so this stays a choice.
    """
    provider = PROVIDERS["ollama"]
    root = _base_url(provider, base_url)
    url = root if root.endswith("/api/chat") else f"{root}/api/chat"
    messages = (
        [{"role": "user", "content": f"{system}\n\n---\n\n{prompt}"}] if fold_system
        else [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    )
    try:
        data = _post_json(
            url,
            {"model": model, "stream": False,
             "options": {"num_predict": max_tokens},
             "messages": messages},
            {},
            timeout,
        )
    except LlmError as exc:
        # Only suggest starting Ollama when it genuinely did not answer. A server
        # that replied with an error is running, and telling someone to start it
        # sends them looking in the wrong place -- which is exactly what happened
        # the first time this was pointed at a generate-only model.
        detail = str(exc)
        if "does not support chat" in detail:
            hint = (f" The model {model!r} has no chat template, so it cannot hold a "
                    f"conversation. Pull an instruct build, for example "
                    f"`ollama pull qwen2.5:3b-instruct`.")
        elif "could not reach" in detail:
            hint = f" Is Ollama running? Start it, then `ollama pull {model}`."
        elif "HTTP 404" in detail:
            hint = f" Ollama does not have that model yet: `ollama pull {model}`."
        else:
            hint = ""
        raise LlmError(f"{detail}{hint}") from exc
    return data.get("message", {}).get("content", "") or ""


def build_call_fn(
    provider: str = DEFAULT_PROVIDER,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    max_tokens: int = 8000,
    timeout: float = DEFAULT_TIMEOUT,
    fold_system: bool = False,
) -> Callable[[str, str, str], str]:
    """Return a ``(model, system, prompt) -> str`` transport for one provider.

    Raises:
        LlmError: if the provider id is unknown. Key and reachability problems
            surface on the first call, not here, so a UI can offer the choice
            before anything is configured.
    """
    if provider not in PROVIDERS:
        raise LlmError(f"unknown provider {provider!r}; available: {sorted(PROVIDERS)}")

    dispatch = {
        "anthropic": _anthropic,
        "google": _google,
        "ollama": _ollama,
    }

    def call(model: str, system: str, prompt: str) -> str:
        kwargs = {"api_key": api_key, "base_url": base_url,
                  "max_tokens": max_tokens, "timeout": timeout}
        if provider == "ollama":
            return _ollama(model, system, prompt, fold_system=fold_system, **kwargs)
        if provider in dispatch:
            return dispatch[provider](model, system, prompt, **kwargs)
        return _openai_style(PROVIDERS[provider], model, system, prompt, **kwargs)

    return call


def provider_status() -> list[dict]:
    """Every provider and whether it is usable right now. Never returns a key."""
    out = []
    for p in PROVIDERS.values():
        configured = True if not p.env_var else bool(os.environ.get(p.env_var))
        out.append({
            "id": p.id, "name": p.name, "models": list(p.models),
            "requires_key": bool(p.env_var), "env_var": p.env_var,
            "configured": configured, "endpoint": p.endpoint,
            "help_url": p.help_url, "purpose": p.purpose, "local": p.local,
            "notes": p.notes, "base_url_env": p.base_url_env,
            "base_url": os.environ.get(p.base_url_env, "") if p.base_url_env else "",
        })
    return out


def check_provider(provider: str, model: str, *, api_key: str | None = None,
                   base_url: str | None = None) -> dict:
    """Send the cheapest possible prompt to prove the settings work.

    A grower needs to know the model is reachable before they trust a plan from it,
    and a failure here names the cause in words rather than surfacing a stack trace.
    """
    try:
        reply = build_call_fn(provider, api_key=api_key, base_url=base_url,
                              max_tokens=32, timeout=45.0)(
            model, "Reply with the single word: ready", "Are you there?")
    except LlmError as exc:
        return {"ok": False, "provider": provider, "model": model, "message": str(exc)}
    return {"ok": True, "provider": provider, "model": model,
            "message": f"{PROVIDERS[provider].name} answered as {model}.",
            "sample": reply.strip()[:120]}

"""Provider transports: request shape, error wording, and no key leakage.

Every test is offline. ``urlopen`` is replaced, so these assert what KasFlex *sends*
and how it reads what comes back -- which is the part that breaks when a vendor
changes its contract, and the part no live test would catch cheaply.
"""

from __future__ import annotations

import json
import urllib.error
from io import BytesIO

import pytest

from kasflex import llm_providers as lp


class FakeResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


@pytest.fixture
def captured(monkeypatch):
    """Capture the outgoing request and return a canned reply per provider."""
    calls: list[dict] = []

    def fake_urlopen(request, timeout=None):
        body = request.data.decode() if request.data else ""
        calls.append({
            "url": request.full_url,
            "headers": {k.lower(): v for k, v in request.headers.items()},
            "payload": json.loads(body) if body else {},
            "timeout": timeout,
        })
        host = request.full_url
        if "anthropic" in host:
            reply = {"content": [{"type": "text", "text": "ANTHROPIC-OK"}]}
        elif "generativelanguage" in host:
            reply = {"candidates": [{"content": {"parts": [{"text": "GEMINI-OK"}]}}]}
        elif "11434" in host or "/api/chat" in host:
            reply = {"message": {"content": "OLLAMA-OK"}}
        else:
            reply = {"choices": [{"message": {"content": "OPENAI-OK"}}]}
        return FakeResponse(json.dumps(reply).encode())

    monkeypatch.setattr(lp.urllib.request, "urlopen", fake_urlopen)
    return calls


# -- registry ---------------------------------------------------------------


def test_every_provider_is_well_formed():
    assert lp.DEFAULT_PROVIDER in lp.PROVIDERS
    for pid, provider in lp.PROVIDERS.items():
        assert provider.id == pid
        assert provider.name
        assert provider.purpose
        if provider.env_var:
            # A generic endpoint has no single sign-up page, so it earns its keep
            # with setup notes instead. Either way the user is told what to do.
            assert provider.help_url or provider.notes, f"{pid} must say how to configure it"


def test_unknown_provider_names_the_alternatives():
    with pytest.raises(lp.LlmError, match="unknown provider"):
        lp.build_call_fn("not-a-vendor")


def test_status_never_returns_a_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-value")
    blob = json.dumps(lp.provider_status())
    assert "sk-ant-secret-value" not in blob
    anthropic = next(p for p in lp.provider_status() if p["id"] == "anthropic")
    assert anthropic["configured"] is True


def test_local_provider_needs_no_key(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    ollama = next(p for p in lp.provider_status() if p["id"] == "ollama")
    assert ollama["requires_key"] is False
    assert ollama["configured"] is True
    assert ollama["local"] is True


# -- request construction ---------------------------------------------------


def test_anthropic_request_shape(captured, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    out = lp.build_call_fn("anthropic")("claude-opus-5", "SYS", "PROMPT")
    assert out == "ANTHROPIC-OK"
    call = captured[0]
    assert call["headers"]["x-api-key"] == "sk-test"
    assert call["headers"]["anthropic-version"] == "2023-06-01"
    assert call["payload"]["system"] == "SYS"
    assert call["payload"]["messages"] == [{"role": "user", "content": "PROMPT"}]


def test_openai_request_shape(captured, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    out = lp.build_call_fn("openai")("gpt-4o", "SYS", "PROMPT")
    assert out == "OPENAI-OK"
    call = captured[0]
    assert call["headers"]["authorization"] == "Bearer sk-openai"
    assert call["url"].endswith("/chat/completions")
    roles = [m["role"] for m in call["payload"]["messages"]]
    assert roles == ["system", "user"]


def test_google_puts_system_in_its_own_field(captured, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    out = lp.build_call_fn("google")("gemini-2.0-flash", "SYS", "PROMPT")
    assert out == "GEMINI-OK"
    call = captured[0]
    assert call["payload"]["system_instruction"]["parts"][0]["text"] == "SYS"
    assert "gemini-2.0-flash:generateContent" in call["url"]


def test_ollama_runs_without_any_key(captured, monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    out = lp.build_call_fn("ollama")("llama3.1", "SYS", "PROMPT")
    assert out == "OLLAMA-OK"
    call = captured[0]
    assert "authorization" not in call["headers"]
    assert call["payload"]["stream"] is False


def test_openai_compatible_uses_the_configured_base_url(captured, monkeypatch):
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "local-key")
    out = lp.build_call_fn("openai-compatible", base_url="http://192.168.1.9:1234/v1")(
        "local-model", "SYS", "PROMPT")
    assert out == "OPENAI-OK"
    assert captured[0]["url"] == "http://192.168.1.9:1234/v1/chat/completions"


def test_openai_compatible_without_a_base_url_says_so(monkeypatch):
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "k")
    monkeypatch.delenv("OPENAI_COMPATIBLE_BASE_URL", raising=False)
    with pytest.raises(lp.LlmError, match="base URL"):
        lp.build_call_fn("openai-compatible")("m", "s", "p")


# -- failure wording --------------------------------------------------------


def test_missing_key_tells_the_user_where_to_add_one(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(lp.LlmError) as exc:
        lp.build_call_fn("anthropic")("claude-opus-5", "s", "p")
    assert "Configuration" in str(exc.value)
    assert "ANTHROPIC_API_KEY" in str(exc.value)


@pytest.mark.parametrize(
    ("code", "phrase"),
    [(401, "key looks wrong"), (404, "not available"), (429, "Rate limited")],
)
def test_http_errors_are_explained_not_dumped(monkeypatch, code, phrase):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")

    def boom(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, code, "err", {}, BytesIO(b"detail"))

    monkeypatch.setattr(lp.urllib.request, "urlopen", boom)
    with pytest.raises(lp.LlmError, match=phrase):
        lp.build_call_fn("anthropic")("claude-opus-5", "s", "p")


def test_unreachable_local_model_suggests_starting_ollama(monkeypatch):
    def boom(request, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(lp.urllib.request, "urlopen", boom)
    with pytest.raises(lp.LlmError, match="Is Ollama running"):
        lp.build_call_fn("ollama")("llama3.1", "s", "p")


def test_empty_anthropic_reply_is_an_error_not_an_empty_plan(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")

    def empty(request, timeout=None):
        return FakeResponse(json.dumps({"content": [], "stop_reason": "max_tokens"}).encode())

    monkeypatch.setattr(lp.urllib.request, "urlopen", empty)
    with pytest.raises(lp.LlmError, match="max_tokens"):
        lp.build_call_fn("anthropic")("claude-opus-5", "s", "p")


# -- connection check -------------------------------------------------------


def test_check_provider_reports_success(captured, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    result = lp.check_provider("anthropic", "claude-opus-5")
    assert result["ok"] is True
    assert "ANTHROPIC-OK" in result["sample"]


def test_check_provider_reports_failure_without_raising(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    result = lp.check_provider("google", "gemini-2.0-flash")
    assert result["ok"] is False
    assert "GEMINI_API_KEY" in result["message"]

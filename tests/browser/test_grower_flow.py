"""The grower page, driven in a real browser.

The HTTP tests check every endpoint, but a workshop fails on the page: a button
that never enables, a script error after a refactor, a dialog that blocks the
screen. These tests open the grower workspace in headless Chromium and go
through a session the way a participant does, and run axe-core on the main
screens.

They need the ``browser`` extra and a Chromium for Playwright:

    pip install -e ".[dev,browser]"
    python -m playwright install chromium

axe-core is read from ``KASFLEX_AXE_JS`` or ``node_modules/axe-core/axe.min.js``
(``npm install --no-save axe-core@4``). Without it only the accessibility tests
are skipped. Set ``KASFLEX_CHROMIUM`` to use a Chromium binary that is already
installed.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.request
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from kasflex.ui.server import serve  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "scenario_westland_winter.yaml"
TIMEOUT_MS = 60_000


def _axe_source() -> str | None:
    candidates = [os.environ.get("KASFLEX_AXE_JS", ""),
                  str(ROOT / "node_modules" / "axe-core" / "axe.min.js")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).read_text(encoding="utf-8")
    return None


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as playwright:
        executable = os.environ.get("KASFLEX_CHROMIUM") or None
        try:
            instance = playwright.chromium.launch(executable_path=executable)
        except Exception as error:  # noqa: BLE001 - no browser installed
            pytest.skip(f"Chromium for Playwright is not available: {error}")
        yield instance
        instance.close()


@pytest.fixture
def server(tmp_path, monkeypatch):
    for variable in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
                     "OPENAI_COMPATIBLE_API_KEY", "ENTSOE_API_KEY", "KASFLEX_ADMIN_PASSWORD"):
        monkeypatch.setenv(variable, "")
    monkeypatch.chdir(tmp_path)
    instance = serve(config_path=str(CONFIG), port=0)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    instance.root = f"http://127.0.0.1:{instance.server_address[1]}"  # type: ignore[attr-defined]
    try:
        yield instance
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=2)


@pytest.fixture
def page(browser, server):
    # The CSP rightly blocks injected scripts; axe-core is injected by the test only.
    context = browser.new_context(bypass_csp=True, locale="en-GB")
    page = context.new_page()
    page.set_default_timeout(TIMEOUT_MS)
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: message.type == "error" and errors.append(message.text))
    page.errors = errors  # type: ignore[attr-defined]
    yield page
    context.close()


def _admin_post(server, path: str, payload: dict) -> dict:
    login = urllib.request.Request(
        server.root + "/api/admin/login", json.dumps({"password": "admin99"}).encode(),
        {"Content-Type": "application/json"})
    with urllib.request.urlopen(login, timeout=10) as response:
        session = json.load(response)
    request = urllib.request.Request(
        server.root + path, json.dumps(payload).encode(),
        {"Content-Type": "application/json", session["header"]: session["token"]})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def _open_workspace(page, server) -> None:
    page.goto(server.root + "/")
    consent = page.locator("#consent-dialog[open]")
    try:
        consent.wait_for(timeout=5_000)
        page.click("#consent-anonymous")
    except sync_api.TimeoutError:
        pass


def _dimensions(page) -> list[str]:
    return page.locator(".dimension-card").evaluate_all(
        "cards => cards.map(card => card.dataset.dimension)")


def _plan_with_suggestion(page) -> None:
    page.click("#accept-recommendation:not([disabled])")
    page.wait_for_selector("#decision-view:not([hidden]) .dimension-card")


def _agree(page, dimension: str) -> None:
    card = f'.dimension-card[data-dimension="{dimension}"]'
    page.locator(f"{card} .choice").first.click()
    page.wait_for_selector(f"{card}.resolved")


def _axe_violations(page, source: str) -> list[dict]:
    page.add_script_tag(content=source)
    result = page.evaluate("async () => (await axe.run(document)).violations")
    return [{"id": v["id"], "impact": v["impact"], "nodes": len(v["nodes"])} for v in result]


def test_a_full_session_ends_in_an_approved_plan_and_a_debrief(page, server):
    _open_workspace(page, server)
    _plan_with_suggestion(page)

    approve = page.locator("#approve-plan")
    dimensions = _dimensions(page)
    assert {"money", "crop", "work"} <= set(dimensions)
    assert approve.is_disabled(), "approval must wait until every part has an answer"

    for dimension in dimensions:
        _agree(page, dimension)
    assert approve.is_enabled()

    approve.click()
    page.wait_for_selector("#debrief:not([hidden])")
    assert page.inner_text("#debrief-text").strip()
    assert page.errors == []  # type: ignore[attr-defined]


def test_a_disagreement_with_a_reason_gets_a_checked_alternative(page, server):
    _open_workspace(page, server)
    _plan_with_suggestion(page)

    card = '.dimension-card[data-dimension="work"]'
    page.locator(f"{card} .choice").nth(2).click()  # disagree
    page.fill(f"{card} textarea", "CHP maintenance 8-14")
    page.click(f"{card} .reason-box button")

    page.wait_for_selector(f"{card} .counter")
    assert "CHP maintenance 8-14" in page.inner_text(f"{card} .counter .said")
    assert page.locator(f"{card} .counter .checker").count() == 1
    assert page.errors == []  # type: ignore[attr-defined]


def test_the_no_advisor_version_shows_no_suggestion_or_chat(page, server):
    _admin_post(server, "/api/workshop", {"version": "manual"})
    _open_workspace(page, server)
    page.wait_for_selector("#build-plan:not([disabled])")
    assert page.locator("#recommend-panel").is_hidden()
    assert page.locator("#chat-toggle").is_hidden()
    assert page.errors == []  # type: ignore[attr-defined]


@pytest.mark.parametrize("screen", ["prepare", "decision", "admin-login"])
def test_main_screens_have_no_accessibility_violations(page, server, screen):
    source = _axe_source()
    if source is None:
        pytest.skip("axe-core is not installed (npm install --no-save axe-core@4)")
    if screen == "admin-login":
        page.goto(server.root + "/admin")
        page.wait_for_load_state("networkidle")
    else:
        _open_workspace(page, server)
        page.wait_for_selector("#accept-recommendation:not([disabled])")
        if screen == "decision":
            _plan_with_suggestion(page)
    assert _axe_violations(page, source) == []


def test_the_admin_page_warns_while_the_default_password_is_in_use(page, server):
    page.goto(server.root + "/admin")
    page.fill("#admin-password", "admin99")
    page.press("#admin-password", "Enter")
    page.wait_for_selector("#workspace:not([hidden])")
    assert "KASFLEX_ADMIN_PASSWORD" in page.inner_text("#default-password")
    assert page.errors == []  # type: ignore[attr-defined]

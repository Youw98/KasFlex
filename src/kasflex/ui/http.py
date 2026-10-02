"""The HTTP request handler: Host, Origin and password checks, then routing to
:class:`kasflex.ui.server.UiServer`. Started by :func:`kasflex.ui.server.serve`.
"""

from __future__ import annotations

import json
import mimetypes
import time
import traceback
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from kasflex.admin_auth import HEADER as ADMIN_HEADER
from kasflex.fair import conflict_table, to_csv
from kasflex.ui.common import (
    SHOWCASE_DATE,
    SHOWCASE_SEED,
    SITE_FIELDS_SET,
    STATIC_DIR,
    VISITOR_HEADER,
    ApiError,
    _reject_constant,
)
from kasflex.ui.reviews import ReviewConflict
from kasflex.ui.server import UiServer, _favicon, _is_loopback
from kasflex.ui.workshop_api import (
    use_visitor,
)


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "kasflex"
    sys_version = ""  # do not advertise the Python version
    ui: UiServer
    allowed_hosts: frozenset[str] = frozenset({"127.0.0.1", "localhost", "[::1]"})
    #: Set when started with allow_network: any Host is accepted (devices on the
    #: network use the machine's address); Origin and the password still apply.
    network: bool = False
    max_body_bytes = 2_000_000

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A002
        """Quieter than the default, which prints a line per asset request."""
        if args and "api" in str(args[0]):
            super().log_message(fmt, *args)

    # -- plumbing ----------------------------------------------------------

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; "
                         "script-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "img-src 'self' data:; connect-src 'self'; "
                         "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: Any, status: int = 200) -> None:
        self._send(status, json.dumps(payload, default=str).encode(), "application/json")

    def _request_host(self) -> str:
        value = (self.headers.get("Host") or "").strip().lower()
        if value.startswith("["):
            end = value.find("]")
            return value[:end + 1] if end >= 0 else value
        return value.rsplit(":", 1)[0]

    #: Requests that change how the site is set up: only with the admin password.
    _ADMIN_POSTS = frozenset({
        "/api/connections", "/api/site-settings", "/api/workshop", "/api/scenarios",
        "/api/scenarios/delete", "/api/documents/save", "/api/documents/delete",
        "/api/memory/forget", "/api/models/test", "/api/experiment", "/api/compare",
        "/api/profiles/delete", "/api/participant-codes",
    })
    #: Research data and other participants' words: readable with the password only.
    _ADMIN_GETS = (
        "/api/preferences", "/api/conflicts", "/api/conversation", "/api/reliance",
        "/api/elicitations", "/api/deliberations", "/api/export/fair", "/api/reviews",
    )

    def _require_admin(self) -> None:
        if not self.ui.gate.check(self.headers.get(ADMIN_HEADER)):
            raise ApiError("Settings are locked: enter the admin password.", 401)

    #: Endpoints that fetch or prepare another day; a locked workshop has no use for them.
    _OTHER_DAY_POSTS = frozenset({"/api/demo-prepare", "/api/data-download"})

    def _enforce_workshop_lock(self, body: dict[str, Any]) -> None:
        """Hold participants to the locked workshop day and study version.

        The grower page hides the day picker when the scenario is locked, but a
        request can still name another day or another condition. With the lock on,
        the server overwrites those fields, so every participant plans the same
        situation and is counted in the version the researcher chose. The settings
        password lifts this, so the researcher can still try other days.
        """
        workshop = self.ui.workshop.get()
        if not workshop.lock_scenario or self.ui.gate.check(self.headers.get(ADMIN_HEADER)):
            return
        if self.path in self._OTHER_DAY_POSTS:
            raise ApiError("The workshop day is locked. Unlock it in ⚙ settings first.", 403)
        overrides = body.get("overrides")
        if not isinstance(overrides, dict):
            return
        for key in ("date", "seed", "scenario_id", "data_source"):
            overrides.pop(key, None)
        if workshop.scenario_id:
            overrides.update(data_source="scenario", scenario_id=workshop.scenario_id)
        else:
            overrides.update(data_source="synthetic", date=SHOWCASE_DATE, seed=SHOWCASE_SEED)
        overrides["condition"] = workshop.version

    def _enforce_issued_ids(self, body: dict[str, Any]) -> None:
        """With issued codes required, refuse a participant id nobody handed out.

        Otherwise a participant can type another person's id and plan, chat or
        consent under it. A code that matches is stored in its printed form, so
        "p-7kq4mx" and "P-7KQ4MX" are the same person.
        """
        if not self.ui.workshop.get().issued_ids_only:
            return
        if self.ui.gate.check(self.headers.get(ADMIN_HEADER)):
            return
        overrides = body.get("overrides")
        holders = [body] + ([overrides] if isinstance(overrides, dict) else [])
        for holder in holders:
            given = str(holder.get("participant_id") or "").strip()
            if not given:
                continue
            if not self.ui.codes.has(given):
                raise ApiError("Use the participant code you were given.", 403)
            holder["participant_id"] = given.upper()

    def _guard_request(self, *, write: bool = False) -> None:
        """Reject DNS-rebinding and cross-site browser requests to the local app."""
        # Without network mode, only this computer may connect, whatever the Host
        # header claims (another computer can claim to be "127.0.0.1").
        if not self.network and not _is_loopback(str(self.client_address[0])):
            raise ApiError("KasFlex only accepts connections from this computer.", 403)
        if not self.network and self._request_host() not in self.allowed_hosts:
            raise ApiError("This local workspace does not recognise the request host.", 403)
        if not write:
            return

        if self.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
            raise ApiError("Requests from another website are not allowed.", 403)
        origin = self.headers.get("Origin")
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != (
                self.headers.get("Host") or ""
            ).lower():
                raise ApiError("Requests from another website are not allowed.", 403)
        if self.headers.get_content_type() != "application/json":
            raise ApiError("Use a JSON request for this API.", 415)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError as exc:
            raise ApiError("Content-Length must be a number.", 400) from exc
        if length < 0 or length > self.max_body_bytes:
            raise ApiError("Request body is too large.", 413)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            # NaN and Infinity are not JSON, but Python accepts them; refuse them here
            # rather than fail later when the answer cannot be encoded.
            data = json.loads(self.rfile.read(length), parse_constant=_reject_constant)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ApiError(f"request body is not valid JSON: {exc}") from exc
        except RecursionError as exc:
            raise ApiError("request body is nested too deeply") from exc
        if not isinstance(data, dict):
            raise ApiError("request body must be a JSON object")
        return data

    #: The grower page is the front door; the researcher interface is a step aside
    #: from it. A grower who has been told "just open KasFlex" must not land in a
    #: screen built for someone comparing planners.
    _PAGES = {"": "demo.html", "/": "demo.html",
              "/grower": "demo.html",
              "/advanced": "index.html", "/research": "index.html",
              "/setup": "setup.html", "/admin": "admin.html"}

    def _static(self, path: str) -> None:
        name = self._PAGES.get(path.rstrip("/") or "/") or path.lstrip("/")
        target = (STATIC_DIR / name).resolve()
        if not target.is_file() or STATIC_DIR.resolve() not in target.parents:
            self._send(404, b"not found", "text/plain")
            return
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._send(200, target.read_bytes(), kind)

    # -- routes ------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        try:
            self._guard_request()
            if any(self.path == p or self.path.startswith(p + "/") or self.path.startswith(p + "?")
                   for p in self._ADMIN_GETS):
                self._require_admin()
            if self.path == "/api/connections":
                self._json(self.ui.connections.status())
            elif self.path == "/api/reviews":
                self._json({"runs": self.ui.reviews.history()})
            elif self.path.startswith("/api/reviews/"):
                self._json(self.ui.reviews.get(self.path.removeprefix("/api/reviews/")))
            elif self.path == "/api/validation-status":
                self._json(self.ui.measured_validation_status())
            elif self.path.startswith("/api/settings"):
                self._json(self.ui.get_settings())
            elif self.path == "/api/site-settings":
                self._require_admin()
                self._json(self.ui.site_settings())
            elif self.path.startswith("/api/i18n"):
                query = dict(parse_qsl(urlsplit(self.path).query))
                self._json(self.ui.translations(query.get("lang", "")))
            elif self.path == "/api/models":
                self._json(self.ui.model_status())
            elif self.path == "/api/preferences":
                self._json(self.ui.list_preferences())
            elif self.path.startswith("/api/conflicts"):
                query = dict(parse_qsl(urlsplit(self.path).query))
                self._json(self.ui.list_conflicts(query.get("run_id", "")))
            elif self.path.startswith("/api/conversation/"):
                self._json(self.ui.conversation(
                    self.path.removeprefix("/api/conversation/").split("?")[0]))
            elif self.path.startswith("/api/consent"):
                query = dict(parse_qsl(urlsplit(self.path).query))
                overrides = {k: v for k, v in query.items()
                             if k in ("participant_id", "condition")}
                self._json(self.ui.consent_status(overrides))
            elif self.path.startswith("/api/reliance"):
                query = dict(parse_qsl(urlsplit(self.path).query))
                self._json(self.ui.reliance_metrics(query.get("condition", "")))
            elif self.path.startswith("/api/elicitations"):
                query = dict(parse_qsl(urlsplit(self.path).query))
                self._json(self.ui.list_elicitations(query.get("run_id", "")))
            elif self.path.startswith("/api/deliberations"):
                query = dict(parse_qsl(urlsplit(self.path).query))
                self._json(self.ui.list_deliberations(query.get("session_id", "")))
            elif self.path.startswith("/api/workshop"):
                query = dict(parse_qsl(urlsplit(self.path).query))
                self._json(self.ui.workshop_status(query.get("lang", "en")))
            elif self.path == "/api/profiles":
                self._json(self.ui.list_profiles())
            elif self.path.startswith("/api/profiles/export/"):
                profile_id = self.path.removeprefix("/api/profiles/export/").split("?")[0]
                body = self.ui.export_profile(profile_id).encode("utf-8")
                self._send(200, body, "application/json; charset=utf-8")
            elif self.path.startswith("/api/export/fair"):
                query = dict(parse_qsl(urlsplit(self.path).query))
                bundle = self.ui.fair_bundle(query.get("anonymous", "1") != "0")
                if query.get("format") == "csv":
                    body = to_csv(conflict_table({
                        "conflicts": bundle.get("kasflex:conflicts", [])})).encode("utf-8")
                    self._send(200, body, "text/csv; charset=utf-8")
                else:
                    self._json(bundle)
            elif self.path.startswith("/favicon.ico"):
                # Answer rather than 404: a browser asks for this unprompted, and a
                # console full of red on first load makes a working page look broken.
                self._send(200, _favicon(), "image/svg+xml")
            else:
                self._static(self.path.split("?")[0])
        except ReviewConflict as exc:
            self._json({"error": str(exc)}, 409)
        except ApiError as exc:
            self._json({"error": str(exc)}, exc.status)
        except Exception as exc:  # noqa: BLE001
            # The detail goes to the terminal, not to the page: a stack trace tells a
            # visitor more about the installation than they need to know.
            traceback.print_exc()
            self._json({"error": f"Something went wrong ({type(exc).__name__}). "
                                 "The details are in the terminal running KasFlex."}, 500)

    def do_POST(self) -> None:  # noqa: N802
        visitor = (self.headers.get(VISITOR_HEADER)
                   if self.ui.workshop.get().separate_visitors else None)
        with use_visitor(visitor):
            self._post()

    def _post(self) -> None:
        try:
            self._guard_request(write=True)
            if self.path == "/api/connections":
                if int(self.headers.get("Content-Length") or 0) > 8192:
                    raise ApiError("API key request is too large.", 413)
            body = self._body()
            overrides = body.get("overrides", {})
            if self.path in self._ADMIN_POSTS or (
                    self.path == "/api/memory" and body.get("everyone") is True):
                self._require_admin()
            # Site settings travel as overrides too: the AI service, model and server
            # address, the grid contract and the installation. Only the settings
            # password may change them, or a request could point the AI at another
            # server and the stored API key would be sent there with it.
            if isinstance(overrides, dict) and set(overrides) & SITE_FIELDS_SET:
                self._require_admin()
            self._enforce_workshop_lock(body)
            self._enforce_issued_ids(body)
            if self.path == "/api/consent/withdraw" and not self.ui.gate.check(
                    self.headers.get(ADMIN_HEADER)):
                # A participant withdraws their own consent with the key they were
                # given when they consented; nobody else can erase their data.
                if not self.ui.consent_keys.check(
                        str(body.get("participant_id") or overrides.get("participant_id") or ""),
                        str(body.get("withdraw_key") or "")):
                    raise ApiError("Withdrawing needs this participant's withdrawal key "
                                   "or the settings password.", 401)
            if self.path == "/api/admin/login":
                # Wrong passwords pause this tab's logins, not everyone's.
                who = str(self.headers.get(VISITOR_HEADER) or "")[:40]
                if self.ui.gate.locked_out(who):
                    raise ApiError("Too many wrong passwords. Try again in a few minutes.", 429)
                token = self.ui.gate.login(str(body.get("password") or ""), who)
                if token is None:
                    time.sleep(0.4)  # a little friction for guessing
                    raise ApiError("Wrong password.", 401)
                self._json({"token": token, "header": ADMIN_HEADER})
                return
            if self.path == "/api/admin/logout":
                self.ui.gate.logout(self.headers.get(ADMIN_HEADER))
                self._json({"locked": True})
                return
            if self.path == "/api/participant-codes":
                with self.ui._lock:
                    if body.get("clear") is True:
                        # Without codes, "only these codes" would shut everyone out.
                        codes = self.ui.codes.clear()
                        self.ui.workshop.set(issued_ids_only=False)
                    elif body.get("make"):
                        try:
                            codes = self.ui.codes.make(int(body["make"]))
                        except (TypeError, ValueError) as exc:
                            raise ApiError("Say how many codes to make.") from exc
                    else:
                        codes = self.ui.codes.all()
                self._json({"codes": codes})
                return
            if self.path == "/api/site-settings":
                with self.ui._lock:
                    self._json(self.ui.save_site_settings(body))
                return
            if self.path == "/api/connections":
                try:
                    with self.ui._lock:
                        result = self.ui.connections.save(body.get("provider", ""),
                                                          body.get("api_key", ""),
                                                          remove=body.get("remove") is True)
                except ValueError as exc:
                    raise ApiError(str(exc)) from exc
                except OSError as exc:
                    raise ApiError("Could not save the local .env file. "
                                   "Check folder permissions.") from exc
                self._json(result)
            elif self.path.startswith("/api/run"):
                self._json(self.ui.run(overrides, body.get("policy")))
            elif self.path == "/api/day-context":
                # Demo mode prepares data here too, which may rewrite the cache
                # manifest; unlocked, two requests race its read-modify-write.
                with self.ui._lock:
                    self._json(self.ui.day_context(overrides))
            elif self.path == "/api/demo-prepare":
                with self.ui._lock:
                    self._json(self.ui.prepare_demo(
                        overrides, refresh=body.get("refresh") is True))
            elif self.path == "/api/data-status":
                self._json(self.ui.data_status(overrides))
            elif self.path == "/api/data-download":
                with self.ui._lock:
                    self._json(self.ui.data_status(overrides, download=True))
            elif self.path.startswith("/api/verify"):
                if not all(k in body for k in ("run_id", "revision", "plan_hash")):
                    raise ApiError("Generate or reopen a saved plan before verifying edits.", 409)
                self._json(self.ui.verify(overrides, body.get("plan", []), reference=body))
            elif self.path.startswith("/api/decision"):
                self._json(self.ui.decide(body))
            elif self.path.startswith("/api/compare"):
                self._json(self.ui.compare(
                    overrides,
                    body.get("planners") or ["rule-based", "learned", "naive"],
                ))
            elif self.path == "/api/checker-comparison":
                self._json(self.ui.compare_checker(overrides, body.get("policy") or {}))
            elif self.path == "/api/experiment":
                with self.ui._lock:
                    self._json(self.ui.run_experiment_batch(body))
            elif self.path == "/api/deliberate":
                with self.ui._lock:
                    self._json(self.ui.deliberate(body))
            elif self.path == "/api/deliberate/final":
                with self.ui._lock:
                    self._json(self.ui.finalise_deliberation(body))
            elif self.path == "/api/explain":
                self._json(self.ui.explain(body))
            elif self.path == "/api/suggested-questions":
                self._json(self.ui.suggested_questions(overrides))
            elif self.path == "/api/preferences":
                with self.ui._lock:
                    self._json(self.ui.add_preference(body))
            elif self.path == "/api/preferences/change":
                with self.ui._lock:
                    self._json(self.ui.change_preference(body))
            elif self.path == "/api/preferences/from-objection":
                with self.ui._lock:
                    self._json(self.ui.preference_from_objection(body))
            elif self.path == "/api/conflicts":
                with self.ui._lock:
                    self._json(self.ui.record_conflicts(body))
            elif self.path == "/api/conflicts/resolve":
                with self.ui._lock:
                    self._json(self.ui.resolve_conflict(body))
            elif self.path == "/api/compromise":
                self._json(self.ui.find_compromise(body))
            elif self.path == "/api/models/test":
                self._json(self.ui.test_model(body))
            elif self.path == "/api/geocode":
                self._json(self.ui.geocode(body))
            elif self.path == "/api/consent":
                participant = str(body.get("participant_id")
                                  or overrides.get("participant_id") or "")
                if (participant and self.ui.consent.current(participant) is not None
                        and not self.ui.gate.check(self.headers.get(ADMIN_HEADER))
                        and not self.ui.consent_keys.check(participant,
                                                           str(body.get("withdraw_key") or ""))):
                    # Someone else's consent is theirs to change, not a guessed pseudonym's.
                    raise ApiError("This participant has already consented. Changing it needs "
                                   "their key or the settings password.", 409)
                with self.ui._lock:
                    self._json(self.ui.grant_consent(body))
            elif self.path == "/api/consent/withdraw":
                with self.ui._lock:
                    self._json(self.ui.withdraw_consent(body))
            elif self.path == "/api/elicit":
                with self.ui._lock:
                    self._json(self.ui.elicit(body))
            elif self.path == "/api/elicit/step":
                with self.ui._lock:
                    self._json(self.ui.elicitation_step(body))
            elif self.path == "/api/outcomes":
                with self.ui._lock:
                    self._json(self.ui.record_outcome(body))
            elif self.path == "/api/workshop":
                with self.ui._lock:
                    self._json(self.ui.set_workshop(body))
            elif self.path == "/api/scenarios":
                with self.ui._lock:
                    self._json(self.ui.save_scenario(body))
            elif self.path == "/api/scenarios/delete":
                with self.ui._lock:
                    self._json(self.ui.delete_scenario(body))
            elif self.path == "/api/recommend":
                self._json(self.ui.recommendation(body))
            elif self.path == "/api/explain-factors":
                self._json(self.ui.factor_explanation(body))
            elif self.path == "/api/chat":
                with self.ui._lock:
                    self._json(self.ui.chat(body))
            elif self.path == "/api/week-outlook":
                self._json(self.ui.week_outlook(body))
            elif self.path == "/api/memory":
                self._json(self.ui.list_remembered(overrides,
                                                   everyone=body.get("everyone") is True))
            elif self.path == "/api/documents":
                self._json(self.ui.list_documents(str(body.get("language") or "en")))
            elif self.path == "/api/documents/save":
                with self.ui._lock:
                    self._json(self.ui.save_document(body))
            elif self.path == "/api/documents/delete":
                with self.ui._lock:
                    self._json(self.ui.delete_document(body))
            elif self.path == "/api/memory/forget":
                with self.ui._lock:
                    self._json(self.ui.forget_remembered(body))
            elif self.path == "/api/profiles":
                with self.ui._lock:
                    self._json(self.ui.save_profile(body))
            elif self.path == "/api/profiles/delete":
                with self.ui._lock:
                    self._json(self.ui.delete_profile(body))
            elif self.path == "/api/profiles/import":
                with self.ui._lock:
                    self._json(self.ui.import_profile(body))
            else:
                self._json({"error": f"no such endpoint: {self.path}"}, 404)
        except ReviewConflict as exc:
            self._json({"error": str(exc)}, 409)
        except ApiError as exc:
            self._json({"error": str(exc)}, exc.status)
        except Exception as exc:  # noqa: BLE001
            # The detail goes to the terminal, not to the page: a stack trace tells a
            # visitor more about the installation than they need to know.
            traceback.print_exc()
            self._json({"error": f"Something went wrong ({type(exc).__name__}). "
                                 "The details are in the terminal running KasFlex."}, 500)

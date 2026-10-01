# KasFlex audit, 1 October 2026

Method: the *webapp-architect* audit method (evidence-based states, severity
anchors, independent re-check, sibling sweep, coverage ledger). Scope: the local
web interface (`src/kasflex/ui/`), its API, the settings lock, consent and research
stores, LLM calls, and the grower, admin, setup and research pages. Risk tier: ASVS
L2 (accounts in the form of participant pseudonyms, personal research data). Static
review plus local requests against a dummy instance; no remote systems touched.

Tools: `recon.py`, `scan_secrets.py`, `scan_licenses.py`, `check_headers.py`
(against the local server), axe-core 4.10 (WCAG 2.2 AA) in Chromium on nine screens,
and `validate_findings.py` on `findings.json` (VALID).

## Summary

| | |
|---|---|
| Confirmed | 1 high, 3 medium, 1 low — all fixed, each with a regression test |
| Hardening | 6 (3 done, 3 left with a reason) |
| Needs validation | 1 (GL-Gym licence: waiting on WUR) |
| Rejected | 4 |

## Confirmed and fixed

**01 · High · security — a request could send the stored AI key to any server.**
`llm_base_url` (and the other settings-menu fields) were accepted as overrides in
any request, so the settings password could be bypassed from devtools and the
provider key in `.env` sent to a server of someone's choosing. Now every override of
a settings field, and `/api/models/test`, needs the password.

**02 · Medium · privacy — other participants' words were readable by URL.**
`/api/preferences`, `/api/export/fair`, `/api/deliberations`, `/api/reliance`,
`/api/elicitations`, `/api/conflicts`, `/api/conversation/*` and `/api/reviews`
answered without the password, including verbatim disagreement reasons. They now need
it; the setup page downloads exports with the token.

**03 · Medium · privacy — anyone could withdraw (and so erase) another participant.**
Consenting now returns a withdrawal key (only its hash is kept). Withdrawing or
changing an existing consent needs that key or the password.

**04 · Medium · accessibility — unlabelled controls in the goals form** (WCAG 4.1.2).

**05 · Low · accessibility — landmarks, pressed state, tooltip-only meaning, motion.**
axe now reports 0 violations on all nine screens (was 11).

## Hardening

| | Status |
|---|---|
| 06 Password guessing unlimited | Done: 5 wrong in 5 min → 429 for the window |
| 07 Stack traces in 500s, Python version in `Server` | Done |
| 08 Default password `admin99` | Kept at the owner's request; banner and README say to set `KASFLEX_ADMIN_PASSWORD` |
| 09 `condition` and `checker.enabled` settable from devtools | Left: the grower page sends both by design; decide if the study needs them tamper-proof |
| 10 CSP allows inline styles | Left: scripts are already `'self'` only |
| 11 No `.env.example` | Done |

## Needs validation

**12 · GL-Gym is AGPL-3.0-or-later.** Released binaries do not bundle it. The open
questions to WUR are in `docs/WUR_LICENCE_CHECK.md`; hosting the worker as a service
would bring AGPL section 13 into play.

## Rejected (checked, not exploitable)

HTTPS/HSTS on a loopback-only server; `innerHTML` in `app.js` (numbers and fixed
markup only); static path traversal (resolved and confined to the static folder);
committed secrets (only the git-ignored `.env` and a third-party test fixture).

## Coverage ledger

| Unit | Status | Notes |
|---|---|---|
| Authentication (settings password, tokens) | Checked | Server-side compare_digest, 8 h tokens, lockout added |
| Authorisation per route | Checked | Every GET and POST route mapped to grower or researcher; 21 now need the password |
| Injection (SQL, HTML, shell) | Checked | Parameterised sqlite; DOM built with textContent; subprocess only for the GreenLight worker with fixed arguments |
| SSRF / outbound | Checked | Finding 01; other outbound hosts are fixed (ENTSO-E, Open-Meteo) |
| Secrets and config | Checked | `scan_secrets.py`; `.env` git-ignored; keys never returned by the API |
| Headers, CSP, CSRF, DNS rebinding | Checked | Host allow-list, Origin and Sec-Fetch-Site checks, JSON-only writes, strict CSP |
| LLM features | Checked | Model output rendered as text; documents are admin-added; prompt injection from a grower's own reason affects only their own counter-text |
| Privacy / consent | Checked | Findings 02, 03 |
| Accessibility | Checked | axe on 9 screens + manual: labels, pressed state, live regions, motion |
| Dependencies | Partly | Licences scanned; no `pip-audit` run (not installed here) |
| Performance | Not checked | Planner runs ~0.3 s; not in scope |
| Hosting / deployment | Not applicable | Loopback only by design |

## What is already good

A strict CSP with scripts from `'self'` only; Host, Origin and Sec-Fetch-Site checks
against DNS rebinding and cross-site writes; parameterised SQL everywhere; keys
stored in `.env` and never returned; the checker independent of the planner; consent
gating that refuses research writes without consent; text rendered with
`textContent`; a test suite that already pinned several of these properties.

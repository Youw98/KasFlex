# KasFlex review, 2 October 2026

A full review of the app after the workshop release: security, privacy and law,
correctness, accessibility, reliability and supply chain. It follows the
webapp-architect audit method: each finding is confirmed with evidence, marked as
hardening, left open as needs-validation, or rejected after checking. Machine-readable
version: [findings.json](findings.json). Earlier audit:
[2026-10-01](../2026-10-01/REPORT.md).

**Scope:** `kasflex ui` (all five pages and every `/api` endpoint), the CLI, the MCP
server, local storage of research data and keys, GitHub workflows and dependencies.
KasFlex is a local research tool. It never switches equipment itself.

## Summary

| | Count |
|---|---|
| Confirmed and fixed | 5 (3 medium, 2 low) |
| Hardening, done | 7 |
| Needs a decision outside the code | 2 (the code side is done) |
| Rejected after checking | 8 |

No high or critical findings. The approval gate, the settings password and the
protection against other websites all hold up. Most findings are about **who else
can reach the app**: another computer on the network, or the next person on the
same laptop.

## Confirmed and fixed

| # | Severity | What | Fix | Test |
|---|---|---|---|---|
| 01 | medium | `--host 0.0.0.0` opened KasFlex to the whole network. The Host check let a spoofed `Host: 127.0.0.1` in, but blocked real tablets. The password was the published `admin99`. | A network address now needs `--allow-network` **and** your own `KASFLEX_ADMIN_PASSWORD`. Without network mode, only this computer may connect. | `test_review_r1_*` |
| 02 | medium | Shared laptop: the participant id and withdrawal key stayed in the browser for the next person. Anonymous visitors shared remembered reasons. | The id and key are now kept for this tab only, and old copies are deleted. New admin option: **keep each anonymous tab's reasons apart**. | `test_review_r4_*` |
| 03 | medium | The chat and suggestion did not say they come from an AI or where questions go. This is required by AI Act art. 50 from 2 Aug 2026; GDPR art. 13 requires naming who receives the data. | The chat states **"AI assistant. Answers can be wrong"** and names where questions go (the provider, or "this computer"). The suggestion tag reads **"KasFlex suggests · AI"**. Both texts are in English and Dutch. | `test_review_r5_*` |
| 04 | low | The scenario lock and study version were enforced only in the page. With curl, a participant could plan another day or another condition. | With the lock on, the server overrides the day and condition and refuses data downloads. The password lifts this for the researcher. | `test_review_r2_*` |
| 05 | low | `NaN`, `Infinity` or deeply nested JSON made the server answer 500. | Such requests now get a 400 with a clear message. | `test_review_r3_*` |

Each test was run against the old code: all fail there. The CLI test did not fail
but hung, because the old code really did start listening on the network.

### Live check of network mode after the fix

Run from another address (192.0.2.2), with `--allow-network` and a password of our
own:

| Request | Result |
|---|---|
| Page | 200 |
| Write, foreign Origin | 403 |
| Write, same Origin | 200 |
| Log in with `admin99` | 401 |

## Hardening

| # | What | Status |
|---|---|---|
| 06 | GitHub Actions had a write token in every job and used movable tags. | **Done:** read-only by default, so only the release job can write. Actions are pinned to commit SHAs, with Dependabot to update them. |
| 07 | There was no way to report a vulnerability. | **Done:** [SECURITY.md](../../../SECURITY.md) (also good practice under the EU Cyber Resilience Act). |
| 08 | Research stores were readable by other accounts on a shared Linux or Mac computer. | **Done:** `results/` is now private to the user (0700). `.env` was already 0600. |
| 09 | The `data` extra allowed urllib3 and idna versions with known advisories. | **Done:** now requires urllib3 ≥ 2.8.0 and idna ≥ 3.15. |
| 13 | Five wrong passwords locked the login for everyone for 5 minutes. | **Done (follow-up):** the pause applies only to the tab that guessed, so the researcher can still log in. All tabs together are capped at 30 wrong passwords per 5 minutes. |
| 10 | Participants typed their own id, so they could type someone else's. | **Done (follow-up):** the admin page makes random codes to print (`P-7KQ4MX`). With **Only accept these codes** on, the server refuses any other id. |
| 22 | AI answers were not marked in a machine-readable way (AI Act art. 50(2)). | **Done (follow-up):** chat and explanation replies carry `ai_generated: true`, and chat bubbles get a matching attribute. |

## Needs a decision outside the code

The code side of both is done; what remains is paperwork only the institution can do.

- **11 · Cloud AI and GDPR.** The consent dialog now names where chat text goes
  before anyone agrees, and asks people not to type personal details. Left to do: a
  data-processing agreement with the AI provider (none needed with Ollama), and an
  approved information sheet. A ready template in English and Dutch, with a
  pre-study checklist: [PARTICIPANT_INFORMATION.md](../../privacy/PARTICIPANT_INFORMATION.md).
- **12 · AI Act research exemption (art. 2(6)).** Whether workshops with growers
  count as "solely scientific research" is a legal judgement. It does not change the
  app: KasFlex already meets art. 50(1) and (2). Verified on 2 Oct 2026: art. 50
  applies from 2 Aug 2026. The Digital Omnibus postponed only the Annex III
  high-risk rules (to 2 Dec 2027), not art. 50.

## Rejected (checked, not exploitable)

| What was tried | Why it fails |
|---|---|
| Approving without the checker | The server refuses with 409, including stale revisions. |
| Path traversal on static files | Encoded and double-encoded `../` both give 404. |
| Other websites calling the app (CSRF, DNS rebinding) | Foreign Host or Origin gives 403; a wrong content type gives 415. |
| Script injection | Text is set with `textContent`, SVG strings use numbers and fixed values only, and the CSP is strict. |
| SQL injection | Queries are parameterised. |
| MCP server over the network | It runs over stdio only. |
| API key exposure | `.env` is 0600 and git-ignored. The secret scan found no committed credentials. |
| Word upload XXE | Entities are refused. |

## Coverage ledger

| Area | Checked | How |
|---|---|---|
| Access control | ✓ | Every POST and GET route against `_ADMIN_POSTS` / `_ADMIN_GETS`, live probes. |
| Network exposure | ✓ | Bind address, Host / Origin / Fetch-Metadata checks, live probe from LAN address. |
| Input handling | ✓ | Malformed, non-finite and deep JSON, wrong content type, oversized bodies. |
| Consent and withdrawal | ✓ | Key checks, re-grant, erase. |
| Browser storage | ✓ | localStorage and sessionStorage in all pages. |
| AI transparency (AI Act art. 50) | ✓ | Chat, suggestion, legacy explanations. |
| GDPR transparency | ✓ | Where data goes. The DPA question is open (11). |
| Accessibility | ✓ | axe-core on 9 page states (prepare, settings locked and open, decision, counter-proposal, chat, factors, admin, admin login), plus the consent dialog and the participant codes panel: **0 violations**. |
| Supply chain | ✓ | pip-audit, workflow permissions and pinning, secret scan. |
| Reliability | ✓ | Full test suite: 741 passed, 1 skipped. ruff is clean. |
| Performance | ✓ | Local single-user tool; plan and context requests answer within a second or two on the showcase day. No issues. |

## What is already good

- **Human approval comes first.** Every plan needs a person's approval and a passing
  check, and the server enforces both.
- **Strong defences against other websites.** A strict CSP, Host / Origin /
  Fetch-Metadata checks, JSON-only writes, and no stack traces sent to the page.
- **The settings password is checked on the server.** Research data, keys and
  documents are behind it.
- **Consent gates research data.** Withdrawal erases the data, and the stores are
  append-only.
- **Fails loudly.** Missing real data never quietly becomes synthetic data.

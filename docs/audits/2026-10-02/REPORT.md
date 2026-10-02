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
| Hardening, done | 4, plus 1 accepted |
| Needs validation (outside the code) | 3 |
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
| 13 | Five wrong passwords lock the login for everyone for 5 minutes. | **Accepted.** A short delay is better than unlimited guessing. Restarting KasFlex clears it. |

## Needs validation

These cannot be settled in code.

- **10 · Participant ids are typed by participants.** Hand out ids (cards) if
  runs must be attributed reliably. The withdrawal key still protects consent.
- **11 · Cloud AI and GDPR.** With Claude, OpenAI or Gemini, questions and the plan
  go to that provider. The institution needs a data-processing agreement with the
  provider and should name it in the participant information. Ollama keeps
  everything on the computer.
- **12 · AI Act research exemption (art. 2(6)).** A legal check should confirm
  whether the workshops count as "solely scientific research". The disclosure stays
  either way.

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
| Accessibility | ✓ | axe-core on 9 page states (prepare, settings locked and open, decision, counter-proposal, chat, factors, admin, admin login): **0 violations**. |
| Supply chain | ✓ | pip-audit, workflow permissions and pinning, secret scan. |
| Reliability | ✓ | Full test suite: 736 passed, 1 skipped. ruff is clean. |
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

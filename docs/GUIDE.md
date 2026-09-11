# KasFlex, explained

This document has two halves. The first is for anyone — a grower, a supervisor, a
colleague who wants to know what this thing does. The second is for whoever has to
work on it, extend it, or defend its numbers.

> **Simulation only.** No greenhouse equipment is connected. Nothing here controls
> a real CHP, battery or boiler.

---

# Part one: in principle

## What problem is this?

Dutch greenhouses own exactly what a congested electricity grid needs: batteries,
CHP units, heat buffers, lights that can be turned down. Used well, that
flexibility is worth real money and real grid capacity.

Deciding *when* to use it is genuinely hard. Electricity prices change every hour,
the weather changes what the crop needs, and the equipment has rules of its own —
a CHP that starts must run for a while. An AI is good at this kind of puzzle.

The problem is trust. Nobody sensible lets software near a grid connection just
because it claims to have found a cheaper plan. And growers, specifically, have
been handed a lot of software that made their lives worse.

## What KasFlex does

Four steps, always in this order:

1. **A planner proposes a day.** Twenty-four hours of intent: where heat comes
   from, how bright the lights are, when the battery charges.
2. **A safety checker verifies it.** Deterministic rules, not AI. Grid limits, crop
   temperature limits, equipment limits. A plan that breaks one is rejected and the
   planner is told exactly which hour and by how much.
3. **The grower reviews it.** In plain language, with the reasoning available.
4. **The grower decides.** And if they disagree, KasFlex asks why — and remembers.

That fourth step is the part most systems skip, and it is the part this project
exists to study.

## The four things this version adds

### It explains itself

Open **Ask why** and ask a question in your own words: *why is the CHP on at three
in the morning?* The answer is grounded in your actual plan — the real price that
hour, the real heat demand — not a generic description of how CHPs work.

If it cannot tell you why, it says so. A guess dressed up as a reason is worse than
an admission.

### It remembers what you tell it

When you disagree with a plan, KasFlex asks what you would do instead and why. Say
*"I don't trust the CHP overnight, it jammed last February"* and it turns that into
a standing instruction — which it shows you first, and only keeps if you agree.

From then on, every plan takes it into account. If it ever has to go against one of
your instructions, it tells you which one and what forced it.

You can see everything it remembers under **What I've told it**, and remove
anything that no longer applies. Removing something does not erase history: plans
made earlier keep their record of what was in force at the time.

### It looks for a middle way

When your judgement and the planner's disagree, that is usually not a case of one
side being wrong. KasFlex will look for a third position — *run the CHP only after
six in the morning* — and price it, so you can see what the compromise costs and
what it protects.

Sometimes there is no middle way. It will say so rather than invent one.

### It speaks Dutch

The whole interface, and the explanations, in Dutch or English — switchable at any
time from the top of the screen. Dutch explanations are written in Dutch, not
translated from English afterwards, and they use the words growers use: WKK, ketel,
warmtebuffer, groeilampen.

## Which AI?

Your choice, and you are not locked in:

| Service | Account needed? | Where your data goes |
|---|---|---|
| Anthropic Claude | Yes | Anthropic |
| OpenAI | Yes | OpenAI |
| Google Gemini | Yes | Google |
| **Ollama** | **No** | **Nowhere — runs on your own computer** |
| Any OpenAI-compatible server | Depends | Wherever you point it |

If sending operating data to a cloud service is not acceptable — a reasonable
position for a commercial grower — install [Ollama](https://ollama.com), and
everything stays in the building. Nothing else about KasFlex changes.

**KasFlex works with no AI at all.** The planner, the safety checker and the plan
itself do not need one. Without a model you lose the conversation and the automatic
wording of preferences; you can still write preferences yourself, and an objection
you type is still recorded word for word.

## Getting started

First run walks you through five short screens: language, your greenhouse, your
equipment, optionally an AI, and done. It saves the answers, so you are never asked
again.

You can also **save your setup to a file** and load it on another computer — useful
for a second site, a new laptop, or a demonstration machine. The file never
contains your API keys.

## What this is not

- It does not control anything. It is a simulation.
- The greenhouse model is not validated. Costs and crop outcomes are simulation
  output, not predictions of your bill.
- Approval is recorded after the simulation runs. It does not gate execution,
  because there is no execution.
- Compromise suggestions come from a language model. They are suggestions, not
  proofs that no better option exists.

---

# Part two: advanced

## Architecture

```
                    ┌─────────────────────────────┐
 prices, weather ──▶│ planner  (rule-based / LLM  │
 grower prefs    ──▶│           / learned / MPC)  │
                    └──────────────┬──────────────┘
                                   │  Plan (24h intent)
                                   ▼
                    ┌─────────────────────────────┐
                    │ safety checker — determinist│──▶ reject + reason ──┐
                    └──────────────┬──────────────┘                      │
                                   │  accepted                    revise ┘
                                   ▼
                    ┌─────────────────────────────┐
                    │ simulation → metrics        │
                    └──────────────┬──────────────┘
                                   ▼
                    ┌─────────────────────────────┐
                    │ grower review               │
                    │  ├ explain    (conversation)│
                    │  ├ object     → preference  │
                    │  └ edit       → conflict    │
                    └──────────────┬──────────────┘
                                   ▼
                         append-only memory ──▶ next plan's prompt
```

The modules added for this work:

| Module | Responsibility |
|---|---|
| `kasflex.llm_providers` | One `(model, system, prompt) -> str` contract over five vendors |
| `kasflex.conversation` | Explanation, preference extraction, compromise, conflict detection |
| `kasflex.memory` | Append-only preferences, conflicts, conversation |
| `kasflex.i18n` | Catalogue, model language instructions, locale formatting |
| `kasflex.profiles` | Saved setups, local and portable |
| `kasflex.fair` | JSON-LD export, codebook, conflict CSV |

## Model providers

`build_call_fn(provider, api_key=…, base_url=…)` returns the transport. Everything
downstream — planner, explainer, preference extraction, compromise — takes that
callable and never learns which vendor answered.

Transport is stdlib `urllib`, not vendor SDKs. Three reasons: the offline replay
path must not depend on packages a reviewer may not have; SDK major versions break;
and the request bodies are small enough that the contract is clearer written out.

Adding a provider means adding one `Provider` to `PROVIDERS` and, if its wire
format is not OpenAI-shaped, one function. `_openai_style` is the fallback, so
anything OpenAI-compatible needs no code at all.

```python
from kasflex.llm_providers import build_call_fn, check_provider

check_provider("ollama", "llama3.1")          # cheapest possible round trip
call = build_call_fn("ollama")                 # (model, system, prompt) -> str
```

### Replay and reproducibility

`LlmPlanner` consults a `TraceStore` keyed by a hash of the model name and the full
prompt. A hit is served without any network access, so a reviewer can reproduce a
published figure with no account and no key. A near-miss raises rather than
silently serving a different day's plan.

`build_planner` now supplies a transport as well, for runs that have not been
recorded yet. The trace store is still consulted first.

## Grower memory

One SQLite file, three append-only tables, `UPDATE` blocked by trigger.

**Preferences** are stated once and never edited. Retiring one appends a
`retired` event; confirming an inferred one appends `confirmed`. Current state is
derived by folding the event log, so *"which preferences were in force on the day
this plan was made"* stays answerable.

```python
memory.add_preference(
    "Do not run the CHP between 22:00 and 06:00",
    "it jammed last February and I could not get an engineer out",
    strength="strong",
    scope={"assets": ["chp"], "hours": [22, 23, 0, 1, 2, 3, 4, 5]},
)
memory.prompt_block()   # rendered into the planner's system prompt
```

Strength binds differently:

| Strength | Meaning |
|---|---|
| `preference` | May be overruled with a stated reason |
| `strong` | Requires an explanation in that hour's reasoning |
| `absolute` | Never crossed; the planner reports infeasibility instead |

**Conflicts** are the study's primary observation. `detect_conflicts` is pure
arithmetic over two plans — no model call — so disagreement is recorded even with
no AI configured. Each conflict carries the planner's value, the grower's value,
the cost difference, whether the checker refused it, and how it resolved:
`grower_kept`, `ai_kept`, `compromise`, or still `open`.

`statistics()["compromise_rate"]` is compromises over *decided* conflicts; open
ones are excluded rather than counted as failures.

**Conversation** turns are stored verbatim with role and model. Grower turns are
the qualitative datum; assistant turns record what they were responding to.

## Containment

Model output is data, never instruction:

- Free text is inserted with `textContent`. Never `innerHTML`.
- Structured replies are parsed, validated field by field, and clamped — hours
  outside 0–23 dropped, unknown strengths downgraded to `preference`, confidence
  clamped to [0, 1].
- A reply that will not parse raises a message telling the grower how to rephrase.
  It never half-applies.
- An inferred preference is stored `confirmed=False` and does not enter
  `prompt_block()` until a person agrees to the wording.

## Language

`CATALOG` is one table of `key -> {lang: text}`, so a reviewer sees both columns
side by side. The test suite fails if any key is missing in either language, and
fails if placeholders differ between them.

`language_instruction(lang)` is appended to every system prompt. Dutch explanations
are generated in Dutch: translating a finished English answer loses the reasoning
and produces the stilted register that makes people distrust a machine.

Formatting follows locale — `€ 1.234` and `13.00 uur` against `€1,234` and `13:00`.

## Profiles

Saved setups are JSON. Loading one is treated as untrusted input: an allowlist
(`SAFE_KEYS`, `SAFE_KEY_PREFIXES`) keeps recognised scenario fields and drops
everything else, so a profile can never carry an API key or a filesystem path
between machines. Size-capped, version-checked, and a corrupt file is skipped
rather than breaking the list.

## FAIR export

`GET /api/export/fair` returns a JSON-LD bundle; `?format=csv` returns the conflict
table flat. `?anonymous=0` keeps operator identity, which is off by default.

The bundle carries a declared `@context`, a licence, per-series data provenance
with checksums, a **codebook** describing every field that carries a finding, and
an explicit **limitations** list. See [FAIR.md](FAIR.md) for the project's wider
FAIR position.

The irreplaceable part of the dataset is `preference.reason` and
`conflict.grower_reason` — the grower's own words. Everything else exists so a
future reader can interpret them correctly.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/i18n?lang=` | Catalogue for one language |
| `GET` | `/api/models` | Providers and which are configured |
| `POST` | `/api/models/test` | One cheap round trip to prove settings work |
| `POST` | `/api/explain` | Answer a question about a plan |
| `GET` | `/api/preferences` | Everything remembered, with statistics |
| `POST` | `/api/preferences` | State one directly |
| `POST` | `/api/preferences/from-objection` | Propose a rule from an objection |
| `POST` | `/api/preferences/change` | `confirm` or `retire` |
| `POST` | `/api/conflicts` | Record edits against the planner's choices |
| `POST` | `/api/conflicts/resolve` | Close one with an outcome |
| `POST` | `/api/compromise` | Look for a third position |
| `GET`/`POST` | `/api/profiles` | Saved setups |
| `GET` | `/api/export/fair` | Research bundle, JSON-LD or CSV |

Localhost only, single user, no authentication. Do not expose it to a network; if
that is ever needed it requires a real framework and a real auth story, not a
changed bind address.

## Configuration

```yaml
language: nl                 # en | nl
llm_provider: ollama         # anthropic | openai | google | ollama | openai-compatible
llm_model: llama3.1
llm_base_url: ""             # only for self-hosted
memory_path: results/grower_memory.sqlite3
```

Keys live in `.env` beside the application, written through an allowlist, chmod
600, and never returned by any endpoint.

## Testing

```bash
python -m pytest -q
```

No test reaches the network. Provider transports are tested by replacing
`urlopen` and asserting the *outgoing* request shape, which is what breaks when a
vendor changes its contract. Conversation is tested with a scripted `call_fn`,
including the hostile cases: prose where JSON was asked for, rules wider than the
objection, hours out of range.

## Known limitations

- Compromise quality is unmeasured. Whether growers accept these suggestions is an
  open question and one of the things the study should answer.
- Preference extraction can mis-scope an objection. The confirmation step exists
  because of this, and the grower's verbatim reason is retained so a researcher can
  audit the wording against what was actually said.
- `detect_conflicts` compares fields independently; it does not understand that
  changing `chp_mode` and `heat_source` together may be one decision.
- The grower interface assumes one site. Multi-site growers would need a site
  switcher and per-site memory.

"""Packaging a study so somebody else can actually use it.

FAIR is four promises, and each costs something concrete here:

**Findable** -- the bundle carries a stable identifier and metadata rich enough to
index. A file called ``results.json`` in a shared drive is not findable.

**Accessible** -- plain JSON over the same local API the interface uses. No vendor
format, no database to install, no credential needed to read what you exported.

**Interoperable** -- JSON-LD with a declared context, so field names mean the same
thing to a tool that has never seen KasFlex. Dates are ISO 8601, money is EUR,
energy is kWh, and the codebook says so rather than leaving it to be guessed.

**Reusable** -- a licence, provenance for every external series, and a codebook
describing every field including the ones that are absent and why. The grower's
own words are the irreplaceable part of this dataset; everything around them
exists so a future reader can interpret them correctly.

Anonymisation is on by default. The research value is in *what* growers object to,
not *which* grower objected.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = "1.0.0"

CONTEXT = {
    "@vocab": "https://schema.org/",
    "kasflex": "https://github.com/ImadB99/kasflex/schema#",
    "prov": "http://www.w3.org/ns/prov#",
    "dcterms": "http://purl.org/dc/terms/",
}

DEFAULT_LICENCE = {
    "name": "Creative Commons Attribution 4.0 International",
    "identifier": "CC-BY-4.0",
    "url": "https://creativecommons.org/licenses/by/4.0/",
}

CODEBOOK: dict[str, dict[str, str]] = {
    "preference.rule": {
        "type": "string",
        "description": "A standing instruction, phrased so a planner can act on it.",
        "note": "Written by the assistant from the grower's objection, then confirmed "
                "by the grower before it binds any plan.",
    },
    "preference.reason": {
        "type": "string",
        "description": "The grower's own words, verbatim.",
        "note": "Never paraphrased. This is the primary qualitative datum.",
    },
    "preference.strength": {
        "type": "enum",
        "description": "preference | strong | absolute",
        "note": "absolute is treated as a hard constraint; preference may be overruled "
                "by the planner with a stated reason.",
    },
    "preference.source": {
        "type": "enum",
        "description": "grower | inferred",
        "note": "inferred means an assistant proposed the wording; confirmed records "
                "whether the grower then agreed to it.",
    },
    "preference.applied_count": {
        "type": "integer",
        "description": "Plans in which this preference was honoured.",
    },
    "preference.overridden_count": {
        "type": "integer",
        "description": "Plans in which the planner went against it anyway.",
        "note": "A high ratio against applied_count marks a preference the system "
                "cannot satisfy, which is a finding rather than a fault.",
    },
    "conflict.ai_value": {
        "type": "string",
        "description": "What the planner chose for this hour and field.",
    },
    "conflict.grower_value": {
        "type": "string",
        "description": "What the grower changed it to.",
    },
    "conflict.cost_delta_eur": {
        "type": "number",
        "unit": "EUR",
        "description": "Cost of the grower's choice minus cost of the planner's. "
                       "Positive means the grower's preference costs money.",
    },
    "conflict.safety_blocked": {
        "type": "boolean",
        "description": "True when the deterministic checker refused the grower's choice.",
    },
    "conflict.resolution": {
        "type": "enum",
        "description": "open | grower_kept | ai_kept | compromise",
        "note": "compromise means a third position was adopted; resolved_value records it.",
    },
    "conversation.role": {
        "type": "enum",
        "description": "grower | assistant | system",
    },
    "conversation.text": {
        "type": "string",
        "description": "Verbatim turn. Grower turns are the research datum; assistant "
                       "turns record what they were responding to.",
    },
    "run.metrics.net_cost_eur": {
        "type": "number",
        "unit": "EUR",
        "description": "Simulated net operating cost for the day.",
        "note": "From an unvalidated surrogate greenhouse model unless the run says "
                "otherwise. Not a measured bill.",
    },
    "run.data_source": {
        "type": "enum",
        "description": "synthetic | cache",
        "note": "synthetic runs use generated prices and weather and must not be "
                "reported as findings about real operation.",
    },
    "elicitation.grower_choice": {
        "type": "string",
        "description": "What the grower said they would do for this decision.",
        "note": "Captured BEFORE the planner's suggestion was shown. This ordering "
                "is enforced by the schema and is what keeps the answer unanchored.",
    },
    "elicitation.confidence": {
        "type": "integer",
        "description": "Self-reported confidence, 1 (guessing) to 5 (certain).",
        "note": "Stated at elicitation time, before seeing the suggestion.",
    },
    "elicitation.ai_choice": {
        "type": "string",
        "description": "The planner's choice, recorded at the moment it was revealed.",
    },
    "elicitation.final_choice": {
        "type": "string",
        "description": "What the grower settled on once both were on the table.",
    },
    "elicitation.better_choice": {
        "type": "string",
        "description": "Which choice the realised outcome favoured. Empty if unscored.",
        "note": "An unscored decision has no verdict and is excluded from all rates.",
    },
    "elicitation.verdict": {
        "type": "enum",
        "description": "appropriate_ai | over_reliance | under_reliance | appropriate_self",
        "note": "Empty when the decision is unscored, or when grower and planner "
                "agreed and so no reliance decision arose.",
    },
    "outcome.within_predicted_band": {
        "type": "boolean",
        "description": "Whether realised cost fell inside the range shown to the grower.",
        "note": "Calibration evidence: a well-calibrated 80% band should contain "
                "roughly 80% of outcomes.",
    },
    "uncertainty.forecast_error.basis": {
        "type": "enum",
        "description": "measured | assumed",
        "note": "assumed means the band rests on a configured placeholder rather "
                "than this site's measured forecast error. Bands whose basis is "
                "assumed, with no novelty history, are not shown to growers at all.",
    },
    "uncertainty.novelty.band": {
        "type": "enum",
        "description": "typical | unusual | unlike anything seen | unknown",
        "note": "Epistemic. unknown means there was too little history to judge, "
                "which is distinct from typical.",
    },
    "metrics.rair": {
        "type": "number",
        "description": "Relative AI reliance: of the occasions where following the "
                       "planner would have helped, the share on which the grower did.",
        "note": "None when no such occasion arose. Not zero.",
    },
    "metrics.rsr": {
        "type": "number",
        "description": "Relative self-reliance: of the occasions where holding firm "
                       "would have helped, the share on which the grower did.",
        "note": "None when no such occasion arose. Not zero.",
    },
}

LIMITATIONS = [
    "Greenhouse response comes from an unvalidated surrogate model. Costs and crop "
    "outcomes are simulation output, not measurements.",
    "Runs marked data_source=synthetic use generated prices and weather.",
    "Approval is recorded after simulation; it does not gate execution in this "
    "prototype, and no equipment is controlled.",
    "Preference wording is assistant-generated from a grower objection. The "
    "grower's verbatim reason is the authoritative record of intent.",
    "Compromise proposals come from a language model and are not optimality claims.",
    "Cost bands describe weather-forecast uncertainty propagated through an "
    "unvalidated greenhouse model. The model's own error is not included, so the "
    "true interval is wider than the one reported.",
    "Reliance verdicts depend on scoring a decision against a realised outcome. "
    "Unscored decisions are excluded from every rate rather than counted as "
    "failures, so rates computed early in a study rest on few observations.",
]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()[:16]


@dataclass
class DatasetMetadata:
    """What a catalogue needs in order to list this bundle."""

    title: str = "KasFlex grower-AI interaction dataset"
    description: str = (
        "Plans produced by an AI energy planner for a Dutch greenhouse, the "
        "deterministic safety verdicts on them, and the grower's responses: "
        "questions asked, objections raised, preferences stated, and where human "
        "and machine judgement diverged."
    )
    creators: list[str] = field(default_factory=list)
    publisher: str = "4TU.NIRICT"
    licence: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_LICENCE))
    keywords: list[str] = field(default_factory=lambda: [
        "greenhouse horticulture", "energy flexibility", "human-AI interaction",
        "decision support", "human oversight", "demand response",
    ])
    identifier: str = ""
    version: str = "1.0.0"
    language: str = "en"
    contact: str = ""

    def to_jsonld(self) -> dict[str, Any]:
        return {
            "@type": "Dataset",
            "dcterms:identifier": self.identifier or _stable_id(self.title, self.version),
            "name": self.title,
            "description": self.description,
            "creator": [{"@type": "Person", "name": name} for name in self.creators],
            "publisher": {"@type": "Organization", "name": self.publisher},
            "license": self.licence.get("url", ""),
            "dcterms:license": self.licence,
            "keywords": self.keywords,
            "version": self.version,
            "inLanguage": self.language,
            "dateCreated": _now(),
            **({"contactPoint": {"@type": "ContactPoint", "email": self.contact}}
               if self.contact else {}),
        }


def anonymise_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip operator identity from decision records, keeping everything else.

    Who approved a plan is the one field with no research value and real privacy
    cost, so it goes. The decision, its timing and its comment all stay.
    """
    cleaned = []
    for entry in runs:
        copy = json.loads(json.dumps(entry, default=str))
        decision = copy.get("decision")
        if isinstance(decision, dict):
            for key in ("operator", "operator_id", "user", "username", "email"):
                decision.pop(key, None)
        cleaned.append(copy)
    return cleaned


def build_bundle(
    *,
    metadata: DatasetMetadata | None = None,
    memory_export: dict[str, Any] | None = None,
    runs: list[dict[str, Any]] | None = None,
    data_provenance: dict[str, Any] | None = None,
    software: dict[str, Any] | None = None,
    anonymous: bool = True,
) -> dict[str, Any]:
    """Assemble the whole export.

    Args:
        memory_export: Output of :meth:`kasflex.memory.GrowerMemory.export`.
        runs: Review history, newest first.
        data_provenance: Cache manifest entries -- source, licence, checksum per series.
        software: Version and configuration of what produced this.
        anonymous: Remove operator identity from decisions.
    """
    metadata = metadata or DatasetMetadata()
    memory_export = memory_export or {}
    runs = runs or []
    if anonymous:
        runs = anonymise_runs(runs)

    statistics = dict(memory_export.get("statistics") or {})
    statistics["runs_total"] = len(runs)

    return {
        "@context": CONTEXT,
        "@type": "Dataset",
        "kasflex:schemaVersion": SCHEMA_VERSION,
        "kasflex:generatedAt": _now(),
        "dataset": metadata.to_jsonld(),
        "kasflex:statistics": statistics,
        "kasflex:preferences": memory_export.get("preferences", []),
        "kasflex:preferenceEvents": memory_export.get("preference_events", []),
        "kasflex:conflicts": memory_export.get("conflicts", []),
        "kasflex:conversation": memory_export.get("conversation", []),
        "kasflex:elicitations": memory_export.get("elicitations", []),
        "kasflex:outcomes": memory_export.get("outcomes", []),
        "kasflex:relianceMetrics": memory_export.get("metrics", {}),
        "kasflex:runs": runs,
        "prov:wasDerivedFrom": data_provenance or {},
        "kasflex:software": software or {},
        "kasflex:codebook": CODEBOOK,
        "kasflex:limitations": LIMITATIONS,
        "kasflex:anonymised": anonymous,
    }


def to_json(bundle: dict[str, Any]) -> str:
    return json.dumps(bundle, indent=2, sort_keys=True, default=str, ensure_ascii=False)


def conflict_table(memory_export: dict[str, Any]) -> list[dict[str, Any]]:
    """Conflicts flattened to one row each, for a spreadsheet or R.

    Researchers who will not parse JSON-LD still need the primary observation, and
    a CSV is the format that reaches them.
    """
    rows = []
    for conflict in memory_export.get("conflicts", []):
        rows.append({
            "conflict_id": conflict.get("conflict_id", ""),
            "created_at": conflict.get("created_at", ""),
            "run_id": conflict.get("run_id", ""),
            "revision": conflict.get("revision", ""),
            "hour": conflict.get("hour", ""),
            "field": conflict.get("field_name", ""),
            "ai_value": conflict.get("ai_value", ""),
            "grower_value": conflict.get("grower_value", ""),
            "grower_reason": conflict.get("grower_reason", ""),
            "cost_delta_eur": conflict.get("cost_delta_eur", 0),
            "safety_blocked": conflict.get("safety_blocked", False),
            "resolution": conflict.get("resolution", "open"),
            "resolved_value": conflict.get("resolved_value", ""),
        })
    return rows


def to_csv(rows: list[dict[str, Any]]) -> str:
    """Flat rows as CSV text, with a stable column order."""
    import csv
    import io

    if not rows:
        return ""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()

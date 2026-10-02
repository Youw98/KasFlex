"""Research endpoints: consent, elicitation, outcomes, reliance, profiles, the FAIR
export and the settings the research workspace shows.

A mixin for :class:`kasflex.ui.server.UiServer`, like :mod:`kasflex.ui.workshop_api`.
"""

from __future__ import annotations

import dataclasses
import os
from typing import Any

from kasflex import i18n
from kasflex.consent import SCOPES as CONSENT_SCOPES
from kasflex.fair import DatasetMetadata, build_bundle
from kasflex.llm_providers import (
    PROVIDERS,
    check_provider,
    provider_status,
)
from kasflex.resources import resolve_output
from kasflex.ui.common import (
    ADJUSTABLE,
    ApiError,
    _apply_overrides,
    _get_path,
)


class ResearchMixin:
    # -- consent -------------------------------------------------------------

    def _may_record(self, overrides: dict[str, Any], scope: str) -> bool:
        """Whether this scope may be written to for the current participant.

        With no ``consent_version`` configured no study is running, so nothing is
        gated -- the ordinary case of one person using the tool on their own
        machine. Once a version is set, absence of consent means no.
        """
        config = _apply_overrides(self.base, overrides or {})
        if not config.consent_version:
            return True
        return self.consent.allows(config.participant_id, scope)

    def consent_status(self, overrides: dict[str, Any]) -> dict[str, Any]:
        config = _apply_overrides(self.base, overrides or {})
        current = self.consent.current(config.participant_id)
        return {
            "study_active": bool(config.consent_version),
            "version": config.consent_version,
            "participant_id": config.participant_id,
            "condition": config.condition,
            "needs_consent": bool(config.consent_version)
                             and self.consent.needs_consent(config.participant_id,
                                                            config.consent_version),
            "current": current.to_dict() if current else None,
            "scopes": dict(CONSENT_SCOPES),
            "summary": self.consent.summary(),
        }

    def grant_consent(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = _apply_overrides(self.base, payload.get("overrides", {}))
        participant = str(payload.get("participant_id") or config.participant_id)
        version = str(payload.get("version") or config.consent_version)
        try:
            consent = self.consent.grant(participant, payload.get("scopes") or {},
                                         version=version,
                                         note=str(payload.get("note", "")))
        except ValueError as exc:
            raise ApiError(str(exc)) from exc
        # Shown once, to the browser that consented first: it keeps it to withdraw
        # or change consent later. A participant who already has a key keeps it.
        key = "" if self.consent_keys.has(participant) else self.consent_keys.issue(participant)
        return {**consent.to_dict(), "withdraw_key": key}

    def withdraw_consent(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Withdraw, and erase the participant's data unless asked not to."""
        config = _apply_overrides(self.base, payload.get("overrides", {}))
        participant = str(payload.get("participant_id") or config.participant_id)
        try:
            consent = self.consent.withdraw(participant, str(payload.get("reason", "")))
            deleted = ({} if payload.get("erase") is False
                       else self.consent.erase(participant,
                                               [resolve_output(self.base.memory_path)]))
        except KeyError as exc:
            raise ApiError("No consent record for that participant.", 404) from exc
        return {**consent.to_dict(), "deleted": deleted}

    # -- reliance measurement -----------------------------------------------

    def elicit(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Record what the grower would do, before any suggestion is shown."""
        if not self._may_record(payload.get("overrides", {}), "research"):
            raise ApiError("This has not been consented to.", 403)
        try:
            item = self.reliance.elicit(
                run_id=str(payload.get("run_id") or "unsaved"),
                question=str(payload.get("question", "day_overall")),
                grower_choice=str(payload.get("grower_choice", "")),
                confidence=payload.get("confidence", 0),
                hour=(int(payload["hour"]) if payload.get("hour") is not None else None),
                condition=str(payload.get("condition", "")),
                note=str(payload.get("note", "")))
        except ValueError as exc:
            raise ApiError(str(exc)) from exc
        return item.to_dict()

    def elicitation_step(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Advance one elicitation: ``reveal``, ``resolve`` or ``score``."""
        elicitation_id = str(payload.get("elicitation_id", ""))
        action = str(payload.get("action", ""))
        try:
            if action == "reveal":
                item = self.reliance.reveal(elicitation_id,
                                            str(payload.get("ai_choice", "")),
                                            str(payload.get("ai_confidence", "")))
            elif action == "resolve":
                item = self.reliance.resolve(elicitation_id,
                                             str(payload.get("final_choice", "")),
                                             str(payload.get("note", "")))
            elif action == "score":
                item = self.reliance.score(elicitation_id,
                                           str(payload.get("better_choice", "")),
                                           str(payload.get("note", "")))
            else:
                raise ApiError("Unknown step for an elicitation.")
        except KeyError as exc:
            raise ApiError("That decision is no longer on record.", 404) from exc
        except ValueError as exc:
            raise ApiError(str(exc)) from exc
        return item.to_dict()

    def list_elicitations(self, run_id: str = "") -> dict[str, Any]:
        return {"elicitations": [e.to_dict() for e in self.reliance.elicitations(run_id)]}

    def record_outcome(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Record what a day actually cost, against what was predicted."""
        if not self._may_record(payload.get("overrides", {}), "outcomes"):
            raise ApiError("This has not been consented to.", 403)
        try:
            outcome = self.reliance.record_outcome(
                run_id=str(payload.get("run_id") or "unsaved"),
                predicted_cost_eur=float(payload.get("predicted_cost_eur", 0) or 0),
                actual_cost_eur=float(payload.get("actual_cost_eur", 0) or 0),
                ai_plan_cost_eur=(None if payload.get("ai_plan_cost_eur") is None
                                  else float(payload["ai_plan_cost_eur"])),
                final_plan_cost_eur=(None if payload.get("final_plan_cost_eur") is None
                                     else float(payload["final_plan_cost_eur"])),
                within_predicted_band=payload.get("within_predicted_band"),
                note=str(payload.get("note", "")))
        except (TypeError, ValueError) as exc:
            raise ApiError("An outcome needs numeric costs.") from exc
        return outcome.to_dict()

    def reliance_metrics(self, condition: str = "") -> dict[str, Any]:
        return self.reliance.metrics(condition)

    # -- saved setups -------------------------------------------------------

    def list_profiles(self) -> dict[str, Any]:
        return {"profiles": [dataclasses.asdict(p) for p in self.profiles.list()]}

    def save_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            profile = self.profiles.create(
                str(payload.get("name", "")), payload.get("settings") or {},
                equipment=payload.get("equipment") or {},
                language=str(payload.get("language", "en")),
                notes=str(payload.get("notes", "")))
        except ValueError as exc:
            raise ApiError(str(exc)) from exc
        return dataclasses.asdict(profile)

    def delete_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.profiles.delete(str(payload.get("profile_id", "")))
        return self.list_profiles()

    def import_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            profile = self.profiles.import_text(str(payload.get("text", "")))
        except ValueError as exc:
            raise ApiError(str(exc)) from exc
        return dataclasses.asdict(profile)

    def export_profile(self, profile_id: str) -> str:
        try:
            return self.profiles.export_text(profile_id)
        except KeyError as exc:
            raise ApiError("That setup no longer exists.", 404) from exc

    # -- models -------------------------------------------------------------

    def model_status(self) -> dict[str, Any]:
        provider, model, base_url, language, fold = self._model_settings({})
        return {"providers": provider_status(), "selected": {
            "provider": provider, "model": model, "base_url": base_url,
            "fold_system": fold},
            "language": language}

    def test_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider = str(payload.get("provider") or self.base.llm_provider)
        model = str(payload.get("model") or self.base.llm_model)
        if provider not in PROVIDERS:
            raise ApiError("Choose one of the listed AI services.")
        return check_provider(provider, model,
                              base_url=str(payload.get("base_url") or "") or None)

    def geocode(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Resolve a grower's typed address to latitude/longitude.

        Kept as a thin wrapper so the endpoint is discoverable next to the other
        onboarding calls, and so the network transport is injectable. Tests
        monkeypatch :mod:`kasflex.data.geocode` -- there is no dependency on the
        UI to reach the real Open-Meteo endpoint.
        """
        from kasflex.data.geocode import GeocodingError, geocode  # noqa: PLC0415

        query = str(payload.get("address") or payload.get("query") or "").strip()
        if not query:
            raise ApiError("Enter a place name or address to look up.")
        # Prefer the interface language when the client hasn't passed one, so the
        # resolved place name reads back in the grower's own language.
        language = str(payload.get("language") or self.base.language or "en")
        try:
            place = geocode(query, language=language)
        except GeocodingError as exc:
            # 404 is right for "no such place"; the message is safe to display.
            raise ApiError(str(exc), status=404) from exc
        return {
            "latitude": round(place.latitude, 4),
            "longitude": round(place.longitude, 4),
            "name": place.name,
            "country": place.country,
            "admin": place.admin,
            "query": query,
        }

    # -- language -----------------------------------------------------------

    def translations(self, language: str) -> dict[str, Any]:
        code = i18n.normalise(language)
        return {"language": code, "languages": i18n.language_options(),
                "strings": i18n.catalog_for(code)}

    # -- research export ----------------------------------------------------

    def fair_bundle(self, anonymous: bool = True) -> dict[str, Any]:
        from kasflex.data.cache import DataCache  # noqa: PLC0415

        # A study in progress exports only what people agreed to share. With no
        # consent version configured there is no study and nothing to filter.
        if self.base.consent_version:
            withdrawn = [c.participant_id for c in self.consent.participants()
                         if not c.allows("research")]
            if withdrawn:
                raise ApiError(
                    "Export blocked: "
                    f"{len(withdrawn)} participant(s) have not consented to research "
                    "use or have withdrawn. Erase their data first, or export per "
                    "participant.", 409)

        try:
            provenance = {k: dataclasses.asdict(v) for k, v in DataCache().entries().items()}
        except OSError:
            provenance = {}
        return build_bundle(
            metadata=DatasetMetadata(language=i18n.normalise(self.base.language)),
            memory_export={**self.memory.export(), **self.reliance.export()},
            runs=self.reviews.history(limit=100),
            data_provenance=provenance,
            software={"scenario": self.base.name, "planner": self.base.planner,
                      "greenhouse_model": self.base.greenhouse,
                      "llm_provider": self.base.llm_provider,
                      "llm_model": self.base.llm_model},
            anonymous=anonymous,
        )

    # -- endpoints ---------------------------------------------------------

    def get_settings(self) -> dict[str, Any]:
        """The adjustable fields, their current values and their metadata."""
        fields = []
        for entry in ADJUSTABLE:
            item = dict(entry)
            item["value"] = _get_path(self.base, entry["path"])
            fields.append(item)
        return {
            "scenario": self.base.name,
            "config_path": self.config_path,
            "fields": fields,
            "entsoe_configured": bool(os.environ.get("ENTSOE_API_KEY")),
        }

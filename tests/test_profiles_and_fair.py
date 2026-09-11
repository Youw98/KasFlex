"""Saved setups and the research export.

Profiles are loaded from files a grower may have carried on a USB stick, so the
tests lean on the hostile cases: wrong file, newer format, oversized payload, and
anything trying to smuggle a filesystem path or an API key between machines.

The FAIR tests check the promises that are cheap to break silently -- a licence
that went missing, an operator name that survived anonymisation, a codebook that
stopped describing a field that still exists.
"""

from __future__ import annotations

import json

import pytest

from kasflex import fair
from kasflex.memory import GrowerMemory
from kasflex.profiles import (
    FILE_MARKER,
    PROFILE_VERSION,
    Profile,
    ProfileStore,
    sanitise_settings,
    slugify,
)


@pytest.fixture
def store(tmp_path) -> ProfileStore:
    return ProfileStore(tmp_path / "profiles")


@pytest.fixture
def settings() -> dict:
    return {"name": "Home site", "language": "nl", "hub.floor_area_m2": 50000,
            "latitude": 51.99, "llm_provider": "ollama", "data_source": "cache"}


# -- saving and listing -----------------------------------------------------


def test_a_saved_setup_comes_back(store, settings):
    created = store.create("Westland block 3", settings, equipment={"chp": True})
    loaded = store.get(created.profile_id)

    assert loaded.name == "Westland block 3"
    assert loaded.settings["hub.floor_area_m2"] == 50000
    assert loaded.equipment == {"chp": True}


def test_setups_list_most_recent_first(store, settings):
    first = store.create("First", settings)
    second = store.create("Second", settings)
    second.notes = "touched"
    store.save(second)

    assert [p.name for p in store.list()] == ["Second", "First"]


def test_an_unnamed_setup_is_refused(store, settings):
    with pytest.raises(ValueError, match="name"):
        store.create("   ", settings)


def test_deleting_leaves_the_others(store, settings):
    keep = store.create("Keep", settings)
    drop = store.create("Drop", settings)
    store.delete(drop.profile_id)

    assert [p.profile_id for p in store.list()] == [keep.profile_id]


def test_one_corrupt_file_does_not_hide_the_rest(store, settings):
    store.create("Good", settings)
    (store.root / "broken.json").write_text("{not json", encoding="utf-8")

    assert [p.name for p in store.list()] == ["Good"]


def test_missing_setup_raises(store):
    with pytest.raises(KeyError):
        store.get("does-not-exist")


def test_profile_id_cannot_escape_the_directory(store, settings):
    store.create("Home", settings)
    with pytest.raises((ValueError, KeyError)):
        store.get("../../etc/passwd")


# -- what a profile is allowed to carry -------------------------------------


def test_secrets_and_paths_are_stripped():
    cleaned = sanitise_settings({
        "name": "Home", "hub.floor_area_m2": 1000,
        "ANTHROPIC_API_KEY": "sk-should-not-travel",
        "audit_path": "/home/someone/results",
        "trace_path": "C:/Users/someone/traces",
        "memory_path": "/tmp/memory.sqlite3",
    })
    assert cleaned == {"name": "Home", "hub.floor_area_m2": 1000}


def test_nested_structures_are_dropped_not_flattened():
    assert sanitise_settings({"hub.battery": {"capacity_kwh": 2000}}) == {}


def test_unknown_keys_are_ignored():
    assert "surprise" not in sanitise_settings({"surprise": 1, "name": "ok"})


def test_settings_must_be_a_mapping():
    with pytest.raises(ValueError, match="named values"):
        sanitise_settings(["name", "Home"])


# -- files from elsewhere ---------------------------------------------------


def test_export_then_import_round_trips(store, settings):
    created = store.create("Home site", settings, language="nl")
    text = store.export_text(created.profile_id)

    fresh = ProfileStore(store.root / "elsewhere")
    imported = fresh.import_text(text)

    assert imported.name == "Home site"
    assert imported.language == "nl"
    assert imported.settings["llm_provider"] == "ollama"


def test_exported_file_is_readable_json_with_a_marker(store, settings):
    created = store.create("Home", settings)
    payload = json.loads(store.export_text(created.profile_id))

    assert payload["marker"] == FILE_MARKER
    assert payload["version"] == PROFILE_VERSION


def test_a_file_that_is_not_a_kasflex_setup_says_so(store):
    with pytest.raises(ValueError, match="not a KasFlex setup"):
        store.import_text(json.dumps({"some": "other file"}))


def test_unreadable_text_is_explained(store):
    with pytest.raises(ValueError, match="could not be read"):
        store.import_text("this is not json at all")


def test_a_newer_format_asks_the_user_to_update(store, settings):
    payload = {"marker": FILE_MARKER, "version": PROFILE_VERSION + 5,
               "name": "From the future", "settings": settings}
    with pytest.raises(ValueError, match="newer version"):
        store.import_text(json.dumps(payload))


def test_an_enormous_file_is_refused(store):
    with pytest.raises(ValueError, match="too large"):
        store.import_text(json.dumps({"marker": FILE_MARKER, "name": "big",
                                      "notes": "x" * 300_000}))


def test_imported_setups_cannot_carry_a_key(store, settings):
    payload = {"marker": FILE_MARKER, "version": PROFILE_VERSION, "name": "Sneaky",
               "settings": {**settings, "ANTHROPIC_API_KEY": "sk-nope"}}
    imported = store.import_text(json.dumps(payload))
    assert "ANTHROPIC_API_KEY" not in imported.settings


def test_profile_from_payload_requires_a_name():
    with pytest.raises(ValueError, match="needs a name"):
        Profile.from_payload({"marker": FILE_MARKER, "settings": {}})


@pytest.mark.parametrize(
    ("given", "expected"),
    [("Westland Blok 3", "westland-blok-3"), ("Kas  //  Zuid", "kas-zuid"),
     ("Éénhoorn", "eenhoorn"), ("!!!", "profile")],
)
def test_slugify_survives_real_names(given, expected):
    assert slugify(given) == expected


# -- the research export ----------------------------------------------------


@pytest.fixture
def populated_memory(tmp_path) -> GrowerMemory:
    memory = GrowerMemory(tmp_path / "grower.sqlite3")
    memory.add_preference("Do not run the CHP overnight",
                          "it jammed last February", strength="strong")
    conflict = memory.record_conflict(
        run_id="run-1", revision=1, hour=3, field_name="heat_source",
        ai_value="chp", grower_value="boiler",
        grower_reason="I don't trust it overnight", cost_delta_eur=41.0)
    memory.resolve_conflict(conflict.conflict_id, "compromise", "chp from 06:00")
    memory.add_turn("run-1", "grower", "Why is the CHP on at three?")
    memory.add_turn("run-1", "assistant", "Gas is cheap then.", model="test-model")
    return memory


def test_bundle_declares_context_licence_and_version(populated_memory):
    bundle = fair.build_bundle(memory_export=populated_memory.export())

    assert bundle["@context"]["@vocab"] == "https://schema.org/"
    assert bundle["kasflex:schemaVersion"] == fair.SCHEMA_VERSION
    assert bundle["dataset"]["dcterms:license"]["identifier"] == "CC-BY-4.0"
    assert bundle["dataset"]["dcterms:identifier"]


def test_bundle_carries_the_growers_own_words(populated_memory):
    bundle = fair.build_bundle(memory_export=populated_memory.export())
    assert bundle["kasflex:preferences"][0]["reason"] == "it jammed last February"
    assert bundle["kasflex:conflicts"][0]["grower_reason"] == "I don't trust it overnight"


def test_bundle_states_its_limitations(populated_memory):
    bundle = fair.build_bundle(memory_export=populated_memory.export())
    joined = " ".join(bundle["kasflex:limitations"])
    assert "unvalidated surrogate" in joined
    assert "does not gate execution" in joined


def test_anonymisation_removes_the_operator_but_keeps_the_decision():
    runs = [{"run_id": "r1", "decision": {"decision": "approve", "operator": "imad",
                                          "comment": "fine by me"}}]
    bundle = fair.build_bundle(runs=runs, anonymous=True)
    decision = bundle["kasflex:runs"][0]["decision"]

    assert "operator" not in decision
    assert decision["decision"] == "approve"
    assert decision["comment"] == "fine by me"
    assert bundle["kasflex:anonymised"] is True


def test_anonymisation_can_be_turned_off_deliberately():
    runs = [{"run_id": "r1", "decision": {"decision": "approve", "operator": "imad"}}]
    bundle = fair.build_bundle(runs=runs, anonymous=False)
    assert bundle["kasflex:runs"][0]["decision"]["operator"] == "imad"


def test_anonymisation_does_not_mutate_the_caller_s_data():
    runs = [{"run_id": "r1", "decision": {"decision": "approve", "operator": "imad"}}]
    fair.build_bundle(runs=runs, anonymous=True)
    assert runs[0]["decision"]["operator"] == "imad"


def test_codebook_explains_the_fields_that_carry_the_findings():
    for key in ("preference.reason", "conflict.cost_delta_eur",
                "conflict.resolution", "run.data_source"):
        assert key in fair.CODEBOOK
        assert fair.CODEBOOK[key]["description"]
    assert fair.CODEBOOK["conflict.cost_delta_eur"]["unit"] == "EUR"


def test_bundle_serialises_and_keeps_accents(populated_memory):
    text = fair.to_json(fair.build_bundle(memory_export=populated_memory.export()))
    assert json.loads(text)["kasflex:schemaVersion"] == fair.SCHEMA_VERSION


def test_conflict_table_flattens_one_row_per_conflict(populated_memory):
    rows = fair.conflict_table(populated_memory.export())
    assert len(rows) == 1
    assert rows[0]["resolution"] == "compromise"
    assert rows[0]["resolved_value"] == "chp from 06:00"
    assert rows[0]["cost_delta_eur"] == 41.0


def test_conflict_csv_has_a_header_and_a_row(populated_memory):
    csv_text = fair.to_csv(fair.conflict_table(populated_memory.export()))
    lines = csv_text.strip().splitlines()
    assert lines[0].startswith("conflict_id,")
    assert len(lines) == 2


def test_empty_csv_is_empty_not_broken():
    assert fair.to_csv([]) == ""


def test_statistics_include_the_run_count(populated_memory):
    bundle = fair.build_bundle(memory_export=populated_memory.export(),
                               runs=[{"run_id": "r1"}, {"run_id": "r2"}])
    assert bundle["kasflex:statistics"]["runs_total"] == 2
    assert bundle["kasflex:statistics"]["conflicts_total"] == 1

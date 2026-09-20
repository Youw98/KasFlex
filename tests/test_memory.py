"""Grower memory: append-only guarantees, prompt rendering, conflict arithmetic.

The append-only property is the one worth guarding hardest. A study that claims
"the planner honoured the grower's stated preferences" is only checkable if those
preferences cannot have been quietly rewritten after the fact.
"""

from __future__ import annotations

import sqlite3

import pytest

from kasflex.memory import GrowerMemory


@pytest.fixture
def memory(tmp_path) -> GrowerMemory:
    return GrowerMemory(tmp_path / "grower.sqlite3")


# -- preferences ------------------------------------------------------------


def test_a_preference_keeps_the_growers_own_words(memory):
    pref = memory.add_preference(
        "Do not run the CHP between 22:00 and 06:00",
        "it jammed last February and I could not get an engineer out",
        strength="strong", scope={"assets": ["chp"], "hours": [22, 23, 0, 1, 2, 3, 4, 5]},
    )
    assert pref.active
    assert "engineer" in pref.reason
    assert pref.strength == "strong"
    assert memory.preferences() == [pref]


def test_empty_rule_is_refused(memory):
    with pytest.raises(ValueError, match="rule"):
        memory.add_preference("   ", "because")


def test_unknown_strength_is_refused(memory):
    with pytest.raises(ValueError, match="strength"):
        memory.add_preference("Do a thing", "reason", strength="very-strong")


def test_retiring_hides_it_but_keeps_the_record(memory):
    pref = memory.add_preference("No CHP overnight", "noise complaints")
    memory.retire_preference(pref.pref_id, "moved to a quieter site")

    assert memory.preferences() == []
    archived = memory.get_preference(pref.pref_id)
    assert archived.active is False
    assert archived.retired_reason == "moved to a quieter site"
    assert archived.reason == "noise complaints"
    assert len(memory.preferences(active_only=False)) == 1


def test_preferences_cannot_be_rewritten(memory):
    pref = memory.add_preference("No CHP overnight", "it jammed")
    with sqlite3.connect(memory.path) as db, pytest.raises(sqlite3.IntegrityError,
                                                           match="append-only"):
        db.execute("UPDATE preferences SET reason='something else' WHERE pref_id=?",
                   (pref.pref_id,))


def test_inferred_preferences_wait_for_confirmation(memory):
    pref = memory.add_preference("Keep lights off after 20:00", "you said the neighbours mind",
                                 source="inferred", confirmed=False)
    assert memory.preferences() == []
    assert memory.preferences(include_unconfirmed=True)[0].pref_id == pref.pref_id

    memory.confirm_preference(pref.pref_id)
    assert [p.pref_id for p in memory.preferences()] == [pref.pref_id]


def test_use_is_counted_both_ways(memory):
    pref = memory.add_preference("No CHP overnight", "it jammed")
    memory.note_preference_use(pref.pref_id, honoured=True)
    memory.note_preference_use(pref.pref_id, honoured=True)
    memory.note_preference_use(pref.pref_id, honoured=False, detail="frost risk at 03:00")

    updated = memory.get_preference(pref.pref_id)
    assert updated.applied_count == 2
    assert updated.overridden_count == 1


# -- prompt rendering -------------------------------------------------------


def test_prompt_block_is_empty_when_nothing_is_known(memory):
    assert memory.prompt_block() == ""


def test_prompt_block_puts_absolutes_first(memory):
    memory.add_preference("Keep lights under 80%", "electricity bills", strength="preference")
    memory.add_preference("Never let the crop drop below 17C", "I lost a crop that way",
                          strength="absolute")
    block = memory.prompt_block()

    absolute_at = block.index("[absolute]")
    preference_at = block.index("[preference]")
    assert absolute_at < preference_at
    assert "I lost a crop that way" in block
    assert "Never cross an [absolute] instruction" in block


def test_prompt_block_carries_scope(memory):
    memory.add_preference("No CHP at night", "noise",
                          scope={"assets": ["chp"], "hours": [22, 23, 0, 1]})
    block = memory.prompt_block()
    assert "hours 0-23" in block
    assert "chp" in block


def test_retired_preferences_leave_the_prompt(memory):
    pref = memory.add_preference("No CHP overnight", "it jammed")
    assert "No CHP overnight" in memory.prompt_block()
    memory.retire_preference(pref.pref_id)
    assert memory.prompt_block() == ""


# -- conflicts --------------------------------------------------------------


def test_conflict_starts_open(memory):
    conflict = memory.record_conflict(
        run_id="run1", revision=1, hour=3, field_name="heat_source",
        ai_value="chp", grower_value="boiler",
        ai_rationale="gas is cheap and the CHP earns export revenue",
        grower_reason="I do not trust it overnight", cost_delta_eur=41.5,
    )
    assert conflict.resolution == "open"
    assert conflict.cost_delta_eur == 41.5
    assert memory.conflicts("run1") == [conflict]


def test_conflict_resolution_is_recorded(memory):
    conflict = memory.record_conflict(
        run_id="run1", revision=1, hour=3, field_name="heat_source",
        ai_value="chp", grower_value="boiler")
    resolved = memory.resolve_conflict(conflict.conflict_id, "compromise",
                                       resolved_value="chp from 06:00",
                                       note="grower accepted a daytime-only CHP window")
    assert resolved.resolution == "compromise"
    assert resolved.resolved_value == "chp from 06:00"
    assert resolved.resolved_at


def test_unknown_resolution_is_refused(memory):
    conflict = memory.record_conflict(run_id="r", revision=1, hour=0,
                                      field_name="battery", ai_value="charge",
                                      grower_value="idle")
    with pytest.raises(ValueError, match="resolution"):
        memory.resolve_conflict(conflict.conflict_id, "sort-of-agreed")


def test_conflicts_are_scoped_by_run(memory):
    memory.record_conflict(run_id="a", revision=1, hour=1, field_name="battery",
                           ai_value="charge", grower_value="idle")
    memory.record_conflict(run_id="b", revision=1, hour=2, field_name="battery",
                           ai_value="discharge", grower_value="idle")
    assert len(memory.conflicts("a")) == 1
    assert len(memory.conflicts()) == 2


# -- conversation -----------------------------------------------------------


def test_turns_come_back_in_order(memory):
    memory.add_turn("run1", "grower", "Why is the CHP on at three in the morning?")
    memory.add_turn("run1", "assistant", "Gas is cheap tonight, so...", model="claude-opus-5")
    memory.add_turn("run2", "grower", "different run")

    turns = memory.turns("run1")
    assert [t["role"] for t in turns] == ["grower", "assistant"]
    assert turns[1]["model"] == "claude-opus-5"
    assert len(memory.turns("run2")) == 1


def test_unknown_role_is_refused(memory):
    with pytest.raises(ValueError, match="role"):
        memory.add_turn("run1", "robot", "hello")


# -- statistics and export --------------------------------------------------


def test_statistics_on_an_empty_store_are_zeroed(memory):
    stats = memory.statistics()
    assert stats["preferences_total"] == 0
    assert stats["conflicts_total"] == 0
    assert stats["compromise_rate"] is None


def test_compromise_rate_ignores_open_conflicts(memory):
    ids = [memory.record_conflict(run_id="r", revision=1, hour=h, field_name="battery",
                                  ai_value="charge", grower_value="idle").conflict_id
           for h in range(4)]
    memory.resolve_conflict(ids[0], "compromise")
    memory.resolve_conflict(ids[1], "grower_kept")
    memory.resolve_conflict(ids[2], "ai_kept")
    # ids[3] deliberately left open.

    stats = memory.statistics()
    assert stats["conflicts_total"] == 4
    assert stats["conflicts_open"] == 1
    assert stats["compromise_rate"] == pytest.approx(1 / 3)


def test_export_carries_everything_needed_to_reanalyse(memory):
    pref = memory.add_preference("No CHP overnight", "it jammed")
    memory.retire_preference(pref.pref_id, "engine replaced")
    conflict = memory.record_conflict(run_id="r", revision=1, hour=3,
                                      field_name="heat_source", ai_value="chp",
                                      grower_value="boiler")
    memory.resolve_conflict(conflict.conflict_id, "grower_kept")
    memory.add_turn("r", "grower", "why?")

    export = memory.export()
    assert len(export["preferences"]) == 1
    assert export["preferences"][0]["reason"] == "it jammed"
    assert {e["event"] for e in export["preference_events"]} == {"created", "retired"}
    assert export["conflicts"][0]["resolution"] == "grower_kept"
    assert export["conversation"][0]["text"] == "why?"
    assert export["statistics"]["conflicts_total"] == 1


def test_reopening_the_same_file_sees_prior_memory(tmp_path):
    path = tmp_path / "grower.sqlite3"
    GrowerMemory(path).add_preference("No CHP overnight", "it jammed")
    assert len(GrowerMemory(path).preferences()) == 1

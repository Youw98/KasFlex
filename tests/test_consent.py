"""Consent, and the erasure that has to follow withdrawal.

The negative tests carry the weight here. Defaulting to permitted, or letting
consent under one version of the text stand for another, or leaving data in place
after a withdrawal, would each be an ethics failure that the code would otherwise
never complain about.
"""

from __future__ import annotations

import sqlite3

import pytest

from kasflex.consent import SCOPES, ConsentLog
from kasflex.memory import GrowerMemory
from kasflex.reliance import RelianceLog

VERSION = "2026-09-v1"


@pytest.fixture
def log(tmp_path) -> ConsentLog:
    return ConsentLog(tmp_path / "consent.sqlite3")


ALL_YES = dict.fromkeys(SCOPES, True)


# -- absence of consent is a no ---------------------------------------------


def test_someone_never_asked_permits_nothing(log):
    for scope in SCOPES:
        assert log.allows("grower-1", scope) is False


def test_an_unknown_participant_needs_consent(log):
    assert log.needs_consent("grower-1", VERSION) is True


def test_declining_research_blocks_every_scope(log):
    log.grant("grower-1", {"research": False, "quotes": True, "outcomes": True},
              version=VERSION)

    for scope in SCOPES:
        assert log.allows("grower-1", scope) is False, scope


# -- granular consent -------------------------------------------------------


def test_scopes_are_independent(log):
    log.grant("grower-1", {"research": True, "quotes": False, "outcomes": True},
              version=VERSION)

    assert log.allows("grower-1", "research") is True
    assert log.allows("grower-1", "outcomes") is True
    assert log.allows("grower-1", "quotes") is False


def test_unlisted_scopes_default_to_no(log):
    consent = log.grant("grower-1", {"research": True}, version=VERSION)

    assert consent.scopes["quotes"] is False
    assert set(consent.scopes) == set(SCOPES)


def test_an_unknown_scope_is_refused(log):
    with pytest.raises(ValueError, match="Unknown consent scope"):
        log.grant("grower-1", {"research": True, "sell_to_advertisers": True},
                  version=VERSION)


def test_a_participant_id_is_required(log):
    with pytest.raises(ValueError, match="participant identifier"):
        log.grant("  ", ALL_YES, version=VERSION)


def test_the_version_agreed_to_is_required(log):
    with pytest.raises(ValueError, match="version"):
        log.grant("grower-1", ALL_YES, version="")


# -- versioning -------------------------------------------------------------


def test_consent_to_one_version_is_not_consent_to_another(log):
    log.grant("grower-1", ALL_YES, version="2026-09-v1")

    assert log.needs_consent("grower-1", "2026-09-v1") is False
    assert log.needs_consent("grower-1", "2027-01-v2") is True


def test_re_granting_supersedes_the_earlier_decision(log):
    log.grant("grower-1", {"research": True, "quotes": True}, version=VERSION)
    log.grant("grower-1", {"research": True, "quotes": False}, version=VERSION)

    assert log.allows("grower-1", "quotes") is False
    assert len(log.participants()) == 1, "one row per participant in the summary"


def test_participants_are_kept_apart(log):
    log.grant("grower-1", {"research": True, "quotes": True}, version=VERSION)
    log.grant("grower-2", {"research": False}, version=VERSION)

    assert log.allows("grower-1", "quotes") is True
    assert log.allows("grower-2", "research") is False
    assert len(log.participants()) == 2


# -- withdrawal -------------------------------------------------------------


def test_withdrawal_stops_everything(log):
    log.grant("grower-1", ALL_YES, version=VERSION)
    withdrawn = log.withdraw("grower-1", "changed my mind")

    assert withdrawn.active is False
    assert withdrawn.withdrawal_reason == "changed my mind"
    for scope in SCOPES:
        assert log.allows("grower-1", scope) is False


def test_withdrawal_means_consent_is_needed_again(log):
    log.grant("grower-1", ALL_YES, version=VERSION)
    log.withdraw("grower-1")

    assert log.needs_consent("grower-1", VERSION) is True


def test_someone_may_re_consent_after_withdrawing(log):
    log.grant("grower-1", ALL_YES, version=VERSION)
    log.withdraw("grower-1")
    log.grant("grower-1", {"research": True}, version=VERSION)

    assert log.allows("grower-1", "research") is True


def test_withdrawing_without_a_record_raises(log):
    with pytest.raises(KeyError):
        log.withdraw("nobody")


def test_consent_records_cannot_be_rewritten(log):
    consent = log.grant("grower-1", ALL_YES, version=VERSION)
    with sqlite3.connect(log.path) as db, pytest.raises(sqlite3.IntegrityError,
                                                        match="append-only"):
        db.execute("UPDATE consents SET scopes='{}' WHERE consent_id=?",
                   (consent.consent_id,))


# -- erasure ----------------------------------------------------------------


def test_erasure_removes_the_participants_data(tmp_path, log):
    """Append-only guards tampering; it must not defeat a withdrawal."""
    store = tmp_path / "grower_memory.sqlite3"
    memory = GrowerMemory(store)
    reliance = RelianceLog(store)

    memory.add_turn("run-grower-1", "grower", "I don't trust the CHP overnight")
    memory.record_conflict(run_id="run-grower-1", revision=1, hour=3,
                           field_name="heat_source", ai_value="chp",
                           grower_value="boiler")
    reliance.record_outcome(run_id="run-grower-1", predicted_cost_eur=1,
                            actual_cost_eur=2)
    # Another participant, who must be left alone.
    memory.add_turn("run-grower-2", "grower", "keep this")

    log.grant("grower-1", ALL_YES, version=VERSION)
    log.withdraw("grower-1", "wish to be removed")
    deleted = log.erase("grower-1", [store])

    assert deleted["turns"] == 1
    assert deleted["conflicts"] == 1
    assert deleted["outcomes"] == 1
    assert memory.turns("run-grower-1") == []
    assert memory.conflicts("run-grower-1") == []
    assert len(memory.turns("run-grower-2")) == 1, "other participants untouched"


def test_the_consent_record_survives_erasure(log, tmp_path):
    log.grant("grower-1", ALL_YES, version=VERSION)
    log.withdraw("grower-1")
    log.erase("grower-1", [tmp_path / "missing.sqlite3"])

    consent = log.current("grower-1")
    assert consent is not None, "proof someone asked to be removed must outlive the removal"
    assert consent.erased_at
    assert consent.active is False


def test_erasing_tolerates_a_store_that_is_not_there(log, tmp_path):
    log.grant("grower-1", ALL_YES, version=VERSION)
    assert log.erase("grower-1", [tmp_path / "nope.sqlite3"]) == {}


def test_erasing_without_a_record_raises(log, tmp_path):
    with pytest.raises(KeyError):
        log.erase("nobody", [tmp_path / "x.sqlite3"])


# -- summary ----------------------------------------------------------------


def test_summary_counts_by_scope(log):
    log.grant("a", {"research": True, "quotes": True, "outcomes": True}, version=VERSION)
    log.grant("b", {"research": True, "quotes": False, "outcomes": True}, version=VERSION)
    log.grant("c", {"research": False}, version=VERSION)
    log.grant("d", ALL_YES, version=VERSION)
    log.withdraw("d")

    summary = log.summary()
    assert summary["participants"] == 4
    assert summary["active"] == 3
    assert summary["withdrawn"] == 1
    assert summary["by_scope"]["research"] == 2
    assert summary["by_scope"]["quotes"] == 1
    assert summary["scopes"]["quotes"]


def test_an_empty_log_summarises_cleanly(log):
    summary = log.summary()
    assert summary["participants"] == 0
    assert all(count == 0 for count in summary["by_scope"].values())


def test_reopening_the_file_sees_prior_consent(tmp_path):
    path = tmp_path / "consent.sqlite3"
    ConsentLog(path).grant("grower-1", {"research": True}, version=VERSION)

    assert ConsentLog(path).allows("grower-1", "research") is True

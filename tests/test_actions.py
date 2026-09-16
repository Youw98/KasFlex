"""Turning two plans into a handful of named changes.

The grower-facing unit is an action, so these tests are about what gets named,
what gets merged, what gets left out, and what happens when there is nothing to
say. Wording is template-driven rather than generated, so it can be asserted.
"""

from __future__ import annotations

import dataclasses

import pytest

from kasflex.actions import MAX_ACTIONS, Action, derive_actions, summarise


def row(hour, *, lighting=1.0, heat="boiler", chp="off", battery="idle", price=0.10):
    return {"hour": hour, "lighting_level": lighting, "heat_source": heat,
            "chp_mode": chp, "battery": battery, "battery_power_kw": 0,
            "co2_source": "liquid", "power_price_eur_kwh": price, "reasoning": ""}


@pytest.fixture
def baseline():
    """Normal settings: boiler all day, lights full, nothing clever."""
    return [row(h) for h in range(24)]


# -- nothing to say ---------------------------------------------------------


def test_an_identical_plan_produces_no_actions(baseline):
    assert derive_actions([dict(r) for r in baseline], baseline) == []


def test_no_actions_is_said_plainly(baseline):
    text = summarise(derive_actions([dict(r) for r in baseline], baseline), "en")
    assert "Nothing needs to change" in text


def test_no_actions_is_said_plainly_in_dutch(baseline):
    assert "niets te veranderen" in summarise([], "nl")


# -- naming a change --------------------------------------------------------


def test_dimming_is_named_with_its_level_and_time(baseline):
    plan = [dict(r) for r in baseline]
    for h in range(18, 21):
        plan[h]["lighting_level"] = 0.7

    actions = derive_actions(plan, baseline, language="en")
    assert len(actions) == 1
    assert actions[0].title == "Dim lighting to 70% this evening"
    assert actions[0].why == "Enough light for the crop, lower energy use."
    assert actions[0].status == "good_for_crop"
    assert actions[0].hours == (18, 19, 20)


def test_raising_light_is_named_differently_from_dimming(baseline):
    plan = [dict(r) for r in baseline]
    for h in range(2, 5):
        plan[h]["lighting_level"] = 0.4
    low = derive_actions(plan, [dict(r, lighting_level=0.2) for r in baseline])[0]
    assert low.title.startswith("Raise lighting")


def test_running_the_chp_is_named_with_the_time_of_day(baseline):
    plan = [dict(r) for r in baseline]
    for h in range(18, 22):
        plan[h]["chp_mode"] = "heat_led"

    action = derive_actions(plan, baseline, language="en")[0]
    assert action.title == "Run the CHP this evening"
    assert action.status == "within_limits"


def test_charging_and_discharging_are_told_apart(baseline):
    plan = [dict(r) for r in baseline]
    for h in range(1, 5):
        plan[h]["battery"] = "charge"
    for h in range(17, 20):
        plan[h]["battery"] = "discharge"

    titles = {a.title for a in derive_actions(plan, baseline, language="en")}
    assert "Charge the battery overnight" in titles
    assert "Use stored power this evening" in titles


def test_a_heat_source_change_names_the_equipment(baseline):
    plan = [dict(r) for r in baseline]
    for h in range(6, 10):
        plan[h]["heat_source"] = "chp"

    action = derive_actions(plan, baseline, language="en")[0]
    assert "CHP" in action.title
    assert "in the morning" in action.title


# -- grouping ---------------------------------------------------------------


def test_contiguous_hours_become_one_action(baseline):
    plan = [dict(r) for r in baseline]
    for h in range(12, 18):
        plan[h]["lighting_level"] = 0.5

    actions = derive_actions(plan, baseline)
    assert len(actions) == 1
    assert actions[0].hours == tuple(range(12, 18))


def test_a_gap_splits_the_action_in_two(baseline):
    plan = [dict(r) for r in baseline]
    for h in (8, 9, 14, 15):
        plan[h]["lighting_level"] = 0.5

    actions = derive_actions(plan, baseline)
    assert len(actions) == 2
    assert {a.hours for a in actions} == {(8, 9), (14, 15)}


def test_longer_changes_come_first(baseline):
    plan = [dict(r) for r in baseline]
    plan[3]["battery"] = "charge"                       # one hour
    for h in range(10, 18):
        plan[h]["lighting_level"] = 0.6                 # eight hours

    actions = derive_actions(plan, baseline)
    assert len(actions[0].hours) > len(actions[1].hours)


def test_the_list_is_capped(baseline):
    plan = [dict(r) for r in baseline]
    for h in range(0, 24, 2):        # alternating hours: many short stretches
        plan[h]["lighting_level"] = 0.5

    assert len(derive_actions(plan, baseline)) <= MAX_ACTIONS


def test_float_noise_is_not_a_change(baseline):
    plan = [dict(r) for r in baseline]
    plan[5]["lighting_level"] = 1.0 + 1e-12
    assert derive_actions(plan, baseline) == []


def test_going_idle_is_not_worth_naming(baseline):
    """A battery that stops doing something is not an action a grower acts on."""
    charging = [dict(r, battery="charge") for r in baseline]
    plan = [dict(r, battery="idle") for r in baseline]
    assert derive_actions(plan, charging) == []


# -- savings ----------------------------------------------------------------


def test_lighting_to_zero_says_off_not_zero_percent(baseline):
    """"Dim lighting to 0%" is not how anyone says it."""
    plan = [dict(r) for r in baseline]
    for h in range(1, 5):
        plan[h]["lighting_level"] = 0.0

    action = derive_actions(plan, baseline, language="en")[0]
    assert action.title == "Turn the lighting off overnight"
    assert "0%" not in action.title


def test_clashing_titles_get_a_clock_time(baseline):
    """Two runs of the same change at the same time of day read as one repeated
    instruction unless they are told apart."""
    plan = [dict(r) for r in baseline]
    for h in (1, 3):                       # two separate overnight stretches
        plan[h]["chp_mode"] = "heat_led"

    titles = [a.title for a in derive_actions(plan, baseline, language="en")]
    assert len(titles) == 2
    assert len(set(titles)) == 2, titles
    assert all("01:00" in t or "03:00" in t for t in titles)


def test_unique_titles_stay_plain(baseline):
    plan = [dict(r) for r in baseline]
    for h in range(18, 21):
        plan[h]["chp_mode"] = "heat_led"

    assert derive_actions(plan, baseline, language="en")[0].title == "Run the CHP this evening"


def test_equal_length_changes_share_the_saving_equally(baseline):
    plan = [dict(r) for r in baseline]
    for h in range(1, 4):
        plan[h]["battery"] = "charge"
    for h in range(18, 21):
        plan[h]["lighting_level"] = 0.7

    actions = derive_actions(plan, baseline, saving_eur=300.0)
    assert len(actions) == 2
    assert all(a.saving_eur == 150.0 for a in actions)


def test_a_longer_change_is_credited_with_more_of_the_saving(baseline):
    """An even split showed identical figures beside changes of very different
    size, which reads as five equally valuable suggestions."""
    plan = [dict(r) for r in baseline]
    plan[3]["battery"] = "charge"                     # 1 hour
    for h in range(10, 19):
        plan[h]["lighting_level"] = 0.6               # 9 hours

    actions = derive_actions(plan, baseline, saving_eur=1000.0)
    by_length = sorted(actions, key=lambda a: len(a.hours))

    assert by_length[0].saving_eur == pytest.approx(100.0)
    assert by_length[1].saving_eur == pytest.approx(900.0)
    assert sum(a.saving_eur for a in actions) == pytest.approx(1000.0)


def test_no_saving_given_leaves_it_unstated(baseline):
    plan = [dict(r) for r in baseline]
    plan[3]["battery"] = "charge"
    assert derive_actions(plan, baseline)[0].saving_eur is None


def test_a_saving_with_no_actions_does_not_divide_by_zero(baseline):
    assert derive_actions([dict(r) for r in baseline], baseline, saving_eur=300.0) == []


# -- language ---------------------------------------------------------------


def test_dutch_actions_are_written_in_dutch(baseline):
    plan = [dict(r) for r in baseline]
    for h in range(18, 21):
        plan[h]["lighting_level"] = 0.7

    action = derive_actions(plan, baseline, language="nl")[0]
    assert action.title == "Lampen naar 70% vanavond"
    assert "gewas" in action.why
    assert "Dim" not in action.title


def test_dutch_chp_is_called_wkk(baseline):
    plan = [dict(r) for r in baseline]
    for h in range(18, 22):
        plan[h]["chp_mode"] = "heat_led"

    assert "WKK" in derive_actions(plan, baseline, language="nl")[0].title


def test_the_count_sentence_is_translated(baseline):
    plan = [dict(r) for r in baseline]
    plan[3]["battery"] = "charge"
    actions = derive_actions(plan, baseline)

    assert "1 suggested" in summarise(actions, "en")
    assert "1 voorgestelde" in summarise(actions, "nl")


# -- serialisation ----------------------------------------------------------


def test_to_dict_is_json_safe_and_keeps_the_span(baseline):
    import json

    plan = [dict(r) for r in baseline]
    for h in range(18, 21):
        plan[h]["lighting_level"] = 0.7

    payload = json.loads(json.dumps(derive_actions(plan, baseline)[0].to_dict()))
    assert payload["hours"] == [18, 19, 20]
    assert payload["start"] == 18 and payload["end"] == 20
    assert payload["baseline_value"] == "1.0"
    assert payload["planned_value"] == "0.7"


def test_action_ids_are_stable_for_the_same_change(baseline):
    plan = [dict(r) for r in baseline]
    for h in range(18, 21):
        plan[h]["lighting_level"] = 0.7

    first = derive_actions(plan, baseline)[0].action_id
    second = derive_actions([dict(r) for r in plan], baseline)[0].action_id
    assert first == second, "a stable id lets the interface keep a selection"


def test_different_changes_get_different_ids(baseline):
    plan = [dict(r) for r in baseline]
    for h in (8, 9):
        plan[h]["lighting_level"] = 0.5
    for h in (14, 15):
        plan[h]["lighting_level"] = 0.5

    ids = {a.action_id for a in derive_actions(plan, baseline)}
    assert len(ids) == 2


def test_action_is_frozen():
    action = Action(action_id="a", kind="lighting", title="t", why="w",
                    status="safe", hours=(1,), field_name="lighting_level",
                    baseline_value="1.0", planned_value="0.7")
    with pytest.raises(dataclasses.FrozenInstanceError):
        action.title = "changed"  # type: ignore[misc]

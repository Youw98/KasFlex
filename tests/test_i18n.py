"""Both languages stay complete, and formatting follows local convention.

The completeness test is the important one. A key added in English and forgotten
in Dutch degrades silently into an English string on a Dutch grower's screen,
which is precisely the experience this module exists to prevent.
"""

from __future__ import annotations

import pytest

from kasflex import i18n


# -- completeness -----------------------------------------------------------


@pytest.mark.parametrize("language", sorted(i18n.LANGUAGES))
def test_no_language_has_a_missing_string(language):
    assert i18n.missing_keys(language) == []


@pytest.mark.parametrize("language", sorted(i18n.LANGUAGES))
def test_every_string_is_actually_translated(language):
    catalog = i18n.catalog_for(language)
    assert len(catalog) == len(i18n.CATALOG)
    assert all(isinstance(v, str) and v.strip() for v in catalog.values())


def test_dutch_is_not_just_english_copied():
    """A catalogue where the columns match everywhere has not been translated."""
    english, dutch = i18n.catalog_for("en"), i18n.catalog_for("nl")
    differing = [k for k in english if english[k] != dutch[k]]
    assert len(differing) > len(english) * 0.8, (
        "most Dutch strings are identical to the English ones; "
        "this usually means a block was pasted rather than translated"
    )


def test_placeholders_match_across_languages():
    """A {name} present in one language and absent in the other renders wrong."""
    import re

    mismatched = {}
    for key, entry in i18n.CATALOG.items():
        fields = {lang: set(re.findall(r"\{(\w+)\}", text)) for lang, text in entry.items()}
        if len(set(map(frozenset, fields.values()))) > 1:
            mismatched[key] = fields
    assert not mismatched, f"placeholder mismatch: {mismatched}"


# -- lookup -----------------------------------------------------------------


def test_translate_picks_the_language():
    assert i18n.translate("common.save", "en") == "Save"
    assert i18n.translate("common.save", "nl") == "Opslaan"


def test_unknown_key_returns_itself_rather_than_raising():
    assert i18n.translate("nope.not.a.key", "nl") == "nope.not.a.key"


def test_placeholders_are_filled():
    assert i18n.translate("onboard.step", "en", n=2, total=4) == "Step 2 of 4"
    assert i18n.translate("onboard.step", "nl", n=2, total=4) == "Stap 2 van 4"


def test_missing_placeholder_returns_the_template_not_a_crash():
    assert "{n}" in i18n.translate("onboard.step", "en")


@pytest.mark.parametrize(
    ("given", "expected"),
    [("nl", "nl"), ("NL", "nl"), ("nl-NL", "nl"), ("nl_NL", "nl"),
     ("en", "en"), ("fr", "en"), ("", "en"), (None, "en"), ("  Nl  ", "nl")],
)
def test_language_codes_are_normalised(given, expected):
    assert i18n.normalise(given) == expected


def test_unknown_language_falls_back_to_english():
    assert i18n.translate("common.save", "klingon") == "Save"


# -- formatting -------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "english", "dutch"),
    [(1234.5, "€1,234", "€ 1.234"), (0, "€0", "€ 0"), (-250, "-€250", "-€ 250")],
)
def test_money_follows_local_convention(amount, english, dutch):
    assert i18n.format_money(amount, "en") == english
    assert i18n.format_money(amount, "nl") == dutch


def test_hours_follow_local_convention():
    assert i18n.format_hour(13, "en") == "13:00"
    assert i18n.format_hour(13, "nl") == "13.00 uur"
    assert i18n.format_hour(3, "en") == "03:00"


def test_hour_ranges_read_naturally():
    assert i18n.format_range(22, 6, "en") == "22:00 to 06:00"
    assert i18n.format_range(22, 6, "nl") == "van 22.00 tot 06.00 uur"


# -- model instructions -----------------------------------------------------


def test_dutch_instruction_names_dutch_equipment_terms():
    instruction = i18n.language_instruction("nl")
    assert "Nederlands" in instruction
    assert "WKK" in instruction, "the model must say WKK, not CHP, to a Dutch grower"
    assert "'u'" in instruction, "Dutch growers are addressed formally"


def test_english_instruction_asks_for_plain_language():
    instruction = i18n.language_instruction("en")
    assert "plain English" in instruction
    assert "jargon" in instruction


def test_instruction_defaults_to_english_for_unknown_languages():
    assert i18n.language_instruction("de") == i18n.language_instruction("en")


# -- picker -----------------------------------------------------------------


def test_language_options_are_labelled_in_their_own_language():
    options = {o["code"]: o for o in i18n.language_options()}
    assert options["nl"]["endonym"] == "Nederlands"
    assert options["en"]["endonym"] == "English"

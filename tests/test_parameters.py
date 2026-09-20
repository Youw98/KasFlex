from pathlib import Path


PARAMETERS = Path("docs/PARAMETERS.md")


def test_parameter_table_is_canonical_and_uses_explicit_assumptions():
    text = PARAMETERS.read_text(encoding="utf-8")
    assert "# Parameter provenance" in text
    assert "**ASSUMPTION**" in text
    assert "guess" not in text.lower()
    assert "industry norm" not in text.lower()


def test_parameter_table_covers_every_tahir_demo_domain():
    text = PARAMETERS.read_text(encoding="utf-8").lower()
    required = (
        "greenhouse floor area",
        "grid import contract",
        "contracted base electricity position",
        "battery capacity",
        "battery charge efficiency",
        "chp electrical capacity",
        "chp electrical efficiency",
        "boiler thermal capacity",
        "heat-buffer capacity",
        "pv peak power",
        "supplemental-light target",
        "crop minimum temperature",
        "maximum relative humidity",
        "gas price",
        "electricity day-ahead price",
        "weather forecast",
        "checker max revisions",
    )
    for label in required:
        assert label in text, label


def test_high_value_unknowns_are_called_out_for_replacement():
    text = PARAMETERS.read_text(encoding="utf-8")
    assert "What still needs replacing first" in text
    assert "contracted base volume and contract price" in text
    assert "heat-buffer standing loss" in text

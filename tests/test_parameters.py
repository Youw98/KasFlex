"""Every operational number must have a source or be visibly marked as an assumption."""

from pathlib import Path

import pytest
import yaml

import kasflex.parameters as parameters
from kasflex.parameters import operational_values, parameter_registry


def test_registry_covers_every_operational_value():
    registry = parameter_registry()
    registered = {row["path"] for row in registry["parameters"]}

    assert registered == set(operational_values())
    assert all(row["rationale"] for row in registry["parameters"])
    assert all(
        row.get("source_url") for row in registry["parameters"] if row["status"] == "sourced"
    )


def test_known_guesses_are_not_mislabelled_as_sources():
    by_path = {row["path"]: row for row in parameter_registry()["parameters"]}

    assert by_path["hub.base_load_kw"]["status"] == "assumption"
    assert by_path["hub.buffer.standing_loss_frac_per_hour"]["status"] == "assumption"
    assert by_path["hub.chp.electrical_efficiency"]["status"] == "sourced"


def test_registry_rejects_a_stale_declared_value(tmp_path: Path, monkeypatch):
    registry = yaml.safe_load(parameters.registry_path().read_text(encoding="utf-8"))
    registry["parameters"]["hub.battery.capacity_kwh"]["value"] = 9999
    path = tmp_path / "parameters.yaml"
    path.write_text(yaml.safe_dump(registry), encoding="utf-8")
    monkeypatch.setattr(parameters, "registry_path", lambda: path)

    with pytest.raises(ValueError, match="does not match configured value"):
        parameter_registry()

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.services.deployment import (
    DEPLOY_MODE_ENV,
    IARIC_ALLOCATION_ENV,
    US_ORB_ALLOCATION_ENV,
    DeploymentConfigError,
    resolve_strategy_capital_allocation,
)


def test_combined_mode_defaults_to_equal_split(monkeypatch):
    monkeypatch.delenv(DEPLOY_MODE_ENV, raising=False)
    monkeypatch.delenv(IARIC_ALLOCATION_ENV, raising=False)
    monkeypatch.delenv(US_ORB_ALLOCATION_ENV, raising=False)

    iaric = resolve_strategy_capital_allocation("IARIC_v1", raw_nav=100_000.0)
    us_orb = resolve_strategy_capital_allocation("US_ORB_v1", raw_nav=100_000.0)

    assert iaric.enabled_for_strategy is True
    assert iaric.capital_fraction == 0.5
    assert iaric.allocated_nav == 50_000.0
    assert us_orb.capital_fraction == 0.5
    assert us_orb.allocated_nav == 50_000.0


def test_combined_mode_supports_uneven_split(monkeypatch):
    monkeypatch.setenv(DEPLOY_MODE_ENV, "both")
    monkeypatch.setenv(IARIC_ALLOCATION_ENV, "30")
    monkeypatch.setenv(US_ORB_ALLOCATION_ENV, "70")

    iaric = resolve_strategy_capital_allocation("IARIC_v1", raw_nav=100_000.0)
    us_orb = resolve_strategy_capital_allocation("US_ORB_v1", raw_nav=100_000.0)

    assert iaric.capital_fraction == pytest.approx(0.30)
    assert iaric.allocated_nav == pytest.approx(30_000.0)
    assert us_orb.capital_fraction == pytest.approx(0.70)
    assert us_orb.allocated_nav == pytest.approx(70_000.0)


def test_combined_mode_rejects_invalid_total(monkeypatch):
    monkeypatch.setenv(DEPLOY_MODE_ENV, "both")
    monkeypatch.setenv(IARIC_ALLOCATION_ENV, "60")
    monkeypatch.setenv(US_ORB_ALLOCATION_ENV, "50")

    with pytest.raises(DeploymentConfigError, match="must equal 100"):
        resolve_strategy_capital_allocation("IARIC_v1", raw_nav=100_000.0)


def test_combined_mode_rejects_non_positive_split(monkeypatch):
    monkeypatch.setenv(DEPLOY_MODE_ENV, "both")
    monkeypatch.setenv(IARIC_ALLOCATION_ENV, "0")
    monkeypatch.setenv(US_ORB_ALLOCATION_ENV, "100")

    with pytest.raises(DeploymentConfigError, match="must be > 0"):
        resolve_strategy_capital_allocation("IARIC_v1", raw_nav=100_000.0)


def test_invalid_mode_is_rejected(monkeypatch):
    monkeypatch.setenv(DEPLOY_MODE_ENV, "swing")

    with pytest.raises(DeploymentConfigError, match="must be one of"):
        resolve_strategy_capital_allocation("IARIC_v1", raw_nav=100_000.0)


def test_solo_modes_grant_full_capital_to_active_strategy(monkeypatch):
    monkeypatch.setenv(DEPLOY_MODE_ENV, "iaric")

    iaric = resolve_strategy_capital_allocation("IARIC_v1", raw_nav=100_000.0)
    us_orb = resolve_strategy_capital_allocation("US_ORB_v1", raw_nav=100_000.0)

    assert iaric.enabled_for_strategy is True
    assert iaric.capital_fraction == 1.0
    assert iaric.allocated_nav == 100_000.0
    assert us_orb.enabled_for_strategy is False
    assert us_orb.capital_fraction == 0.0
    assert us_orb.allocated_nav == 0.0
    with pytest.raises(RuntimeError, match="disabled by"):
        us_orb.assert_enabled()

    monkeypatch.setenv(DEPLOY_MODE_ENV, "us_orb")
    us_orb_only = resolve_strategy_capital_allocation("US_ORB_v1", raw_nav=100_000.0)
    assert us_orb_only.enabled_for_strategy is True
    assert us_orb_only.capital_fraction == 1.0
    assert us_orb_only.allocated_nav == 100_000.0


def test_positive_allocated_nav_validation(monkeypatch):
    monkeypatch.setenv(DEPLOY_MODE_ENV, "both")
    allocation = resolve_strategy_capital_allocation("IARIC_v1", raw_nav=0.0)

    with pytest.raises(RuntimeError, match="positive raw NAV"):
        allocation.assert_positive_allocated_nav()

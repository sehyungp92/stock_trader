"""Deployment-mode and capital-allocation helpers for live strategy runtimes."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

DEPLOY_MODE_ENV = "STOCK_TRADER_DEPLOY_MODE"
IARIC_ALLOCATION_ENV = "STOCK_TRADER_CAPITAL_ALLOCATION_IARIC_PCT"
US_ORB_ALLOCATION_ENV = "STOCK_TRADER_CAPITAL_ALLOCATION_US_ORB_PCT"

_VALID_DEPLOY_MODES = ("both", "iaric", "us_orb")
_STRATEGY_TO_MODE = {
    "IARIC_v1": "iaric",
    "US_ORB_v1": "us_orb",
}
_MODE_TO_STRATEGY = {mode: strategy for strategy, mode in _STRATEGY_TO_MODE.items()}


class DeploymentConfigError(ValueError):
    """Raised when deployment-mode or allocation environment is invalid."""


@dataclass(frozen=True)
class StrategyCapitalAllocation:
    """Resolved deployment-mode and NAV allocation for a single strategy."""

    strategy_id: str
    deploy_mode: str
    enabled_for_strategy: bool
    capital_fraction: float
    raw_nav: float
    allocated_nav: float

    @property
    def capital_pct(self) -> float:
        return self.capital_fraction * 100.0

    def assert_enabled(self) -> None:
        if self.enabled_for_strategy:
            return
        allowed_strategy = _MODE_TO_STRATEGY[self.deploy_mode]
        raise RuntimeError(
            f"{self.strategy_id} is disabled by {DEPLOY_MODE_ENV}={self.deploy_mode}. "
            f"Start only {allowed_strategy} or set {DEPLOY_MODE_ENV}=both."
        )

    def assert_positive_allocated_nav(self) -> None:
        if not math.isfinite(self.raw_nav) or self.raw_nav <= 0:
            raise RuntimeError(
                f"{self.strategy_id} requires a positive raw NAV; got {self.raw_nav!r}."
            )
        if not math.isfinite(self.allocated_nav) or self.allocated_nav <= 0:
            raise RuntimeError(
                f"{self.strategy_id} requires a positive allocated NAV; got {self.allocated_nav!r}."
            )


def _strategy_mode(strategy_id: str) -> str:
    try:
        return _STRATEGY_TO_MODE[strategy_id]
    except KeyError as exc:
        raise DeploymentConfigError(f"Unsupported strategy_id for deployment allocation: {strategy_id}") from exc


def _parse_deploy_mode() -> str:
    raw_mode = (os.environ.get(DEPLOY_MODE_ENV) or "both").strip().lower()
    if raw_mode not in _VALID_DEPLOY_MODES:
        valid = ", ".join(_VALID_DEPLOY_MODES)
        raise DeploymentConfigError(f"{DEPLOY_MODE_ENV} must be one of {valid}; got {raw_mode!r}")
    return raw_mode


def _parse_positive_pct(env_name: str, default: float) -> float:
    raw_value = os.environ.get(env_name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise DeploymentConfigError(f"{env_name} must be numeric; got {raw_value!r}") from exc
    if not math.isfinite(value) or value <= 0:
        raise DeploymentConfigError(f"{env_name} must be > 0; got {raw_value!r}")
    return value


def resolve_strategy_capital_allocation(strategy_id: str, raw_nav: float) -> StrategyCapitalAllocation:
    """Resolve deploy mode and effective capital allocation for a strategy."""

    strategy_mode = _strategy_mode(strategy_id)
    deploy_mode = _parse_deploy_mode()

    if deploy_mode == "both":
        iaric_pct = _parse_positive_pct(IARIC_ALLOCATION_ENV, 50.0)
        us_orb_pct = _parse_positive_pct(US_ORB_ALLOCATION_ENV, 50.0)
        total_pct = iaric_pct + us_orb_pct
        if not math.isclose(total_pct, 100.0, rel_tol=0.0, abs_tol=1e-6):
            raise DeploymentConfigError(
                f"{IARIC_ALLOCATION_ENV} + {US_ORB_ALLOCATION_ENV} must equal 100; got {total_pct:.6f}"
            )
        capital_fraction = (iaric_pct / 100.0) if strategy_mode == "iaric" else (us_orb_pct / 100.0)
        enabled = True
    else:
        enabled = strategy_mode == deploy_mode
        capital_fraction = 1.0 if enabled else 0.0

    nav_value = float(raw_nav)
    allocated_nav = nav_value * capital_fraction if enabled else 0.0
    return StrategyCapitalAllocation(
        strategy_id=strategy_id,
        deploy_mode=deploy_mode,
        enabled_for_strategy=enabled,
        capital_fraction=capital_fraction,
        raw_nav=nav_value,
        allocated_nav=allocated_nav,
    )

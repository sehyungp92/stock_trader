from pathlib import Path

import yaml


def test_compose_defines_two_stock_trader_services():
    compose_path = Path(__file__).resolve().parents[1] / "infra" / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    services = compose["services"]
    assert set(services) == {"strategy_iaric", "strategy_orb"}

    iaric = services["strategy_iaric"]
    us_orb = services["strategy_orb"]

    assert "profiles" not in iaric
    assert "profiles" not in us_orb
    assert iaric["command"] == ["python", "-m", "strategy_iaric"]
    assert us_orb["command"] == ["python", "-m", "strategy_orb"]
    assert iaric["networks"] == ["trading_net"]
    assert us_orb["networks"] == ["trading_net"]
    assert iaric["environment"]["STOCK_TRADER_DEPLOY_MODE"] == "${STOCK_TRADER_DEPLOY_MODE:-both}"
    assert us_orb["environment"]["STOCK_TRADER_DEPLOY_MODE"] == "${STOCK_TRADER_DEPLOY_MODE:-both}"
    assert iaric["environment"]["STOCK_TRADER_CAPITAL_ALLOCATION_IARIC_PCT"] == "${STOCK_TRADER_CAPITAL_ALLOCATION_IARIC_PCT:-50}"
    assert iaric["environment"]["STOCK_TRADER_CAPITAL_ALLOCATION_US_ORB_PCT"] == "${STOCK_TRADER_CAPITAL_ALLOCATION_US_ORB_PCT:-50}"
    assert us_orb["environment"]["STOCK_TRADER_CAPITAL_ALLOCATION_IARIC_PCT"] == "${STOCK_TRADER_CAPITAL_ALLOCATION_IARIC_PCT:-50}"
    assert us_orb["environment"]["STOCK_TRADER_CAPITAL_ALLOCATION_US_ORB_PCT"] == "${STOCK_TRADER_CAPITAL_ALLOCATION_US_ORB_PCT:-50}"
    assert "/app/data/strategy_iaric" in " ".join(iaric["volumes"])
    assert "/app/data/strategy_orb" in " ".join(us_orb["volumes"])
    assert "/app/instrumentation/data" in " ".join(iaric["volumes"])
    assert "/app/instrumentation/data" in " ".join(us_orb["volumes"])
    assert compose["networks"]["trading_net"]["external"] is True

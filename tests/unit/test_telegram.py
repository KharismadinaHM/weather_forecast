"""Unit tests for Telegram Bot, Message Formatters, and Command Handlers (PLAN.md Section 14)."""

from datetime import UTC, date, datetime

import httpx
import pytest
from sqlalchemy.orm import Session

from app.storage.models import (
    PolymarketMarket,
    PolymarketOutcome,
    PolymarketPrice,
    WeatherForecast,
    WeatherObservation,
)
from app.telegram.bot import TelegramCommandHandler
from app.telegram.client import TelegramClient
from app.telegram.formatter import TelegramFormatter
from app.trading.edge import OpportunityEvaluation
from app.trading.risk import RiskEngine


def test_telegram_formatter_daily_summary() -> None:
    """Verify Section 14 daily summary message formatting."""
    dist = {"31°C": 0.12, "32°C": 0.43, "33°C": 0.36, "34°C": 0.09}
    opp = OpportunityEvaluation(
        outcome_label="32°C",
        model_probability=0.43,
        market_probability=0.31,
        gross_edge=0.12,
        effective_entry_price=0.32,
        fees=0.005,
        slippage=0.005,
        net_ev=0.08,
        is_positive_ev=True,
        is_actionable=True,
        rationale="Edge >= 8%",
    )

    msg = TelegramFormatter.format_daily_summary(
        target_date=date(2026, 8, 22),
        model_distribution=dist,
        best_opportunity=opp,
        decision="BUY",
        risk_allocation=1.0,
        model_version="weather-v003",
    )

    assert "HONG KONG WEATHER AI" in msg
    assert "2026-08-22" in msg
    assert "31°C 12%  32°C 43%  33°C 36%  34°C 9%" in msg
    assert "<b>Best opportunity:</b> 32°C" in msg
    assert "Model: 43%  Market: 31%  Gross edge: +12%  Net EV: +8%" in msg
    assert "<b>Decision:</b> 🟢 BUY   <b>Risk allocation:</b> $1" in msg
    assert "<b>Model:</b> weather-v003" in msg


def test_telegram_formatter_alerts() -> None:
    """Verify opportunity alert, missing market alert, and health alert formats."""
    opp = OpportunityEvaluation(
        outcome_label="32°C",
        model_probability=0.45,
        market_probability=0.30,
        gross_edge=0.15,
        effective_entry_price=0.31,
        fees=0.005,
        slippage=0.005,
        net_ev=0.14,
        is_positive_ev=True,
        is_actionable=True,
        rationale="Actionable edge",
    )

    alert_msg = TelegramFormatter.format_opportunity_alert(
        market_question="High temp on Aug 23?",
        target_date=date(2026, 8, 23),
        opportunity=opp,
        recommended_size=1.0,
        model_version="weather-v001",
    )
    assert "TRADE OPPORTUNITY DETECTED" in alert_msg
    assert "32°C" in alert_msg

    miss_msg = TelegramFormatter.format_missing_market_alert(date(2026, 8, 23))
    assert "MISSING MARKET ALERT" in miss_msg
    assert "2026-08-23" in miss_msg

    health_msg = TelegramFormatter.format_health_alert("HKO Collector", "Timeout 408")
    assert "SYSTEM HEALTH ALERT" in health_msg
    assert "HKO Collector" in health_msg


@pytest.mark.asyncio
async def test_telegram_client_unconfigured_graceful_fallback() -> None:
    """Verify TelegramClient handles unconfigured credentials safely without crashing."""
    # Use empty strings (not None) so client doesn't fall back to .env values
    client = TelegramClient(bot_token="", chat_id="")
    assert client.is_configured is False
    res = await client.send_message("Test message")
    assert res is False



@pytest.mark.asyncio
async def test_telegram_client_mock_http_send() -> None:
    """Verify TelegramClient executes POST request against Telegram API endpoint."""

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        assert "bot123456:ABC/sendMessage" in str(request.url)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 999}})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = TelegramClient(
            bot_token="123456:ABC",
            chat_id="chat-789",
            http_client=http_client,
        )
        assert client.is_configured is True
        sent = await client.send_message("<b>Hello Test</b>")
        assert sent is True


def test_telegram_command_handler_pause_and_resume(db_session: Session) -> None:
    """Verify /pause activates kill switch and /resume deactivates it."""
    risk = RiskEngine(is_paused=False)
    handler = TelegramCommandHandler(risk_engine=risk)

    resp_pause = handler.handle_command(db_session, "/pause")
    assert "EXECUTION PAUSED" in resp_pause
    assert risk.is_paused is True

    resp_resume = handler.handle_command(db_session, "/resume")
    assert "EXECUTION RESUMED" in resp_resume
    assert risk.is_paused is False


def test_telegram_command_handler_status_and_help(db_session: Session) -> None:
    """Verify /status, /help, and unknown command handling."""
    handler = TelegramCommandHandler()

    resp_status = handler.handle_command(db_session, "/status")
    assert "AGENT SYSTEM STATUS" in resp_status

    resp_help = handler.handle_command(db_session, "/help")
    assert "AVAILABLE TELEGRAM COMMANDS" in resp_help
    assert "/today" in resp_help

    resp_unknown = handler.handle_command(db_session, "/unknown_cmd")
    assert "Unknown command" in resp_unknown


def test_telegram_command_handler_today_and_market(db_session: Session) -> None:
    """Verify /today and /market commands with database entities."""
    now = datetime.now(UTC)
    db_session.add(
        WeatherObservation(
            observed_at=now,
            station="Hong Kong Observatory",
            is_authoritative=True,
            temperature=31.2,
            rainfall=0.0,
            source="hko_rhrread",
        )
    )
    db_session.add(
        WeatherForecast(
            forecast_created_at=now,
            target_date=now.date(),
            forecast_max_temperature=33.0,
            forecast_min_temperature=27.0,
            source="hko_9day",
        )
    )

    m = PolymarketMarket(
        market_id="m_test_hk",
        event_id="evt-1",
        slug="test-market",
        question="Highest temp in HK today?",
        target_date=now.date(),
        status="active",
    )
    db_session.add(m)
    db_session.flush()

    out = PolymarketOutcome(market_id=m.market_id, token_id="tok_32", outcome_label="32°C")
    db_session.add(out)
    db_session.add(
        PolymarketPrice(market_id=m.market_id, token_id="tok_32", timestamp=now, price=0.35)
    )
    db_session.commit()

    handler = TelegramCommandHandler()

    resp_today = handler.handle_command(db_session, "/today")
    assert "HONG KONG WEATHER TODAY" in resp_today
    assert "31.2°C" in resp_today

    resp_market = handler.handle_command(db_session, "/market")
    assert "ACTIVE POLYMARKET WEATHER MARKETS" in resp_market
    assert "32°C: <code>35¢</code>" in resp_market

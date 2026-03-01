from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = Field(default="dev", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_dir: str = Field(default="./logs", alias="LOG_DIR")
    log_retention_days: int = Field(default=14, alias="LOG_RETENTION_DAYS")
    tz: str = Field(default="Australia/Sydney", alias="TZ")

    ibkr_host: str = Field(default="127.0.0.1", alias="IBKR_HOST")
    ibkr_port: int = Field(default=7497, alias="IBKR_PORT")
    ibkr_client_id: int = Field(default=1, alias="IBKR_CLIENT_ID")
    ibkr_account: str = Field(default="", alias="IBKR_ACCOUNT")
    trading_mode: Literal["paper", "live"] = Field(default="paper", alias="TRADING_MODE")

    max_positions: int = Field(default=5, alias="MAX_POSITIONS")
    max_daily_loss_usd: float = Field(default=200.0, alias="MAX_DAILY_LOSS_USD")
    max_order_notional_usd: float = Field(default=2000.0, alias="MAX_ORDER_NOTIONAL_USD")
    max_total_notional_usd: float = Field(default=8000.0, alias="MAX_TOTAL_NOTIONAL_USD")
    stop_loss_pct: float = Field(default=0.01, alias="STOP_LOSS_PCT")
    take_profit_pct: float = Field(default=0.02, alias="TAKE_PROFIT_PCT")

    database_url: str = Field(default="sqlite:///./executor.db", alias="DATABASE_URL")

    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")

    control_host: str = Field(
        default="0.0.0.0",
        validation_alias=AliasChoices("CONTROL_HOST", "HEALTH_HOST"),
    )
    control_port: int = Field(
        default=8080,
        validation_alias=AliasChoices("CONTROL_PORT", "HEALTH_PORT"),
    )
    control_api_key: str = Field(default="", alias="CONTROL_API_KEY")
    signal_queue_size: int = Field(default=10_000, alias="SIGNAL_QUEUE_SIZE")
    kill_switch: bool = Field(default=False, alias="KILL_SWITCH")
    kill_switch_file: str = Field(default="./KILL", alias="KILL_SWITCH_FILE")

    # AIStock Bridge (embedded mode)
    aistock_bridge_enabled: bool = Field(default=False, alias="AISTOCK_BRIDGE_ENABLED")
    aistock_url: str = Field(default="http://127.0.0.1:8000", alias="AISTOCK_URL")
    aistock_sentiment_url: str = Field(default="http://127.0.0.1:8002", alias="AISTOCK_SENTIMENT_URL")
    aistock_bridge_interval: int = Field(default=20, alias="AISTOCK_BRIDGE_INTERVAL")
    aistock_dashboard_limit: int = Field(default=30, alias="AISTOCK_DASHBOARD_LIMIT")
    aistock_bridge_dry_run: bool = Field(default=False, alias="AISTOCK_BRIDGE_DRY_RUN")
    aistock_cooldown_seconds: int = Field(default=180, alias="AISTOCK_COOLDOWN_SECONDS")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

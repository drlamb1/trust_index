"""
EdgeFinder — Application Settings

Single source of truth for all configuration. Reads from .env file.
All modules import `settings` from here — never use os.environ directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root (two levels up from this file)
PROJECT_ROOT = Path(__file__).parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -------------------------------------------------------------------------
    # Database — Neon PostgreSQL
    # -------------------------------------------------------------------------
    database_url: str = Field(description="Async PostgreSQL URL (postgresql+asyncpg://...)")

    # -------------------------------------------------------------------------
    # Redis — Upstash (production) or local Docker (development)
    # -------------------------------------------------------------------------
    redis_url: str = Field(
        default="redis://localhost:6379",
        description="Redis URL (rediss://... for Upstash with SSL)",
    )

    # -------------------------------------------------------------------------
    # AI — Anthropic
    # -------------------------------------------------------------------------
    anthropic_api_key: str = Field(default="", description="Anthropic API key")

    # -------------------------------------------------------------------------
    # Market Data
    # -------------------------------------------------------------------------
    alpha_vantage_api_key: str = Field(default="", description="Alpha Vantage API key")
    polygon_api_key: str = Field(default="", description="Polygon.io API key")
    finnhub_api_key: str = Field(default="", description="Finnhub API key")
    news_api_key: str = Field(default="", description="NewsAPI.org key")
    fred_api_key: str = Field(default="", description="FRED (St. Louis Fed) API key")
    fmp_api_key: str = Field(default="", description="Financial Modeling Prep API key")

    # -------------------------------------------------------------------------
    # SEC EDGAR — required by SEC data policy
    # -------------------------------------------------------------------------
    edgar_user_agent: str = Field(
        default="EdgeFinder/1.0 contact@example.com",
        description=(
            "User-Agent sent to SEC EDGAR. Must include app name + contact email. "
            "Required by https://www.sec.gov/os/accessing-edgar-data"
        ),
    )

    # -------------------------------------------------------------------------
    # Alert Delivery
    # -------------------------------------------------------------------------
    smtp_host: str = Field(default="", description="SMTP server hostname")
    smtp_port: int = Field(default=587)
    smtp_user: str = Field(default="")
    smtp_password: str = Field(default="")
    smtp_from: str = Field(default="alerts@edgefinder.local")
    alert_email_to: str = Field(default="")

    slack_webhook_url: str = Field(default="")
    discord_webhook_url: str = Field(default="")
    ntfy_topic: str = Field(default="edgefinder-alerts")
    ntfy_server: str = Field(default="https://ntfy.sh")

    # -------------------------------------------------------------------------
    # Application
    # -------------------------------------------------------------------------
    secret_key: str = Field(default="change-me-in-production")
    environment: Literal["development", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    dashboard_host: str = Field(default="0.0.0.0")
    dashboard_port: int = Field(default=8050)

    # -------------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------------
    jwt_algorithm: str = Field(default="HS256")
    access_token_expire_minutes: int = Field(default=1440, description="JWT expiry (default 24h)")
    registration_enabled: bool = Field(default=False, description="Allow public user registration")

    # -------------------------------------------------------------------------
    # Production hardening
    # -------------------------------------------------------------------------
    cors_origins: str = Field(default="*", description="Comma-separated CORS origins (e.g. 'https://app.railway.app,https://example.com' or '*')")

    @property
    def cors_origin_list(self) -> list[str]:
        """Parse cors_origins string into a list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
    chat_rate_limit: str = Field(default="10/minute", description="Rate limit for chat endpoint")

    # -------------------------------------------------------------------------
    # Ingestion limits
    # -------------------------------------------------------------------------
    edgar_rate_limit: float = Field(
        default=8.0,
        description="SEC EDGAR requests per second (SEC allows 10, use 8 for safety)",
    )
    price_history_days: int = Field(
        default=365,
        description="Default days of price history to fetch on initial load",
    )
    news_max_age_days: int = Field(
        default=30,
        description="Maximum age of news articles to ingest",
    )

    # -------------------------------------------------------------------------
    # Simulation Engine — all play-money, zero real capital
    # -------------------------------------------------------------------------
    simulation_initial_capital: float = Field(
        default=100_000.0, description="Starting capital for paper portfolios (play money)"
    )
    simulation_max_open_positions: int = Field(
        default=10, description="Max concurrent paper positions per portfolio"
    )
    simulation_default_stop_loss_pct: float = Field(
        default=8.0, description="Default stop-loss percentage for paper positions"
    )
    simulation_default_take_profit_pct: float = Field(
        default=20.0, description="Default take-profit percentage for paper positions"
    )
    heston_mc_paths: int = Field(
        default=10_000, description="Number of Monte Carlo paths for Heston simulation"
    )
    heston_mc_steps: int = Field(
        default=252, description="Time steps per path (252 = daily for 1 year)"
    )
    deep_hedging_enabled: bool = Field(
        default=False, description="Enable deep hedging experiments (requires PyTorch)"
    )

    # -------------------------------------------------------------------------
    # Derived helpers
    # -------------------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def redis_uses_ssl(self) -> bool:
        return self.redis_url.startswith("rediss://")

    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def has_finnhub(self) -> bool:
        return bool(self.finnhub_api_key)

    @property
    def has_fred(self) -> bool:
        return bool(self.fred_api_key)

    @property
    def has_fmp(self) -> bool:
        return bool(self.fmp_api_key)

    @property
    def has_polygon(self) -> bool:
        return bool(self.polygon_api_key)

    @field_validator("edgar_user_agent")
    @classmethod
    def validate_edgar_user_agent(cls, v: str) -> str:
        if "contact@example.com" in v or not v.strip():
            import warnings

            warnings.warn(
                "EDGAR_USER_AGENT is using the placeholder email. "
                "Set EDGAR_USER_AGENT to 'AppName/Version youremail@domain.com' "
                "in your .env file. SEC policy requires a valid contact email.",
                UserWarning,
                stacklevel=2,
            )
        return v

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        if v == "change-me-in-production":
            import warnings

            warnings.warn(
                "SECRET_KEY is using the default value. "
                "Generate a secure key: openssl rand -hex 32",
                UserWarning,
                stacklevel=2,
            )
        return v


# Module-level singleton — import this everywhere
settings = Settings()


# -------------------------------------------------------------------------
# Path helpers
# -------------------------------------------------------------------------
CONFIG_DIR = PROJECT_ROOT / "config"
TICKERS_FILE = CONFIG_DIR / "tickers.yaml"
THESES_FILE = CONFIG_DIR / "theses.yaml"

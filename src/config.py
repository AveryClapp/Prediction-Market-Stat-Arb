"""Configuration loading and validation for arbitrage detection system."""

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, HttpUrl, field_validator


class KalshiFees(BaseModel):
    """Kalshi fee structure."""

    maker_fee_pct: float = Field(ge=0, le=10)
    taker_fee_pct: float = Field(ge=0, le=10)
    withdrawal_cost_usd: float = Field(ge=0, le=100)


class PolymarketFees(BaseModel):
    """Polymarket fee structure."""

    gas_fee_usd: float = Field(ge=0, le=100)
    usdc_bridge_cost_usd: float = Field(ge=0, le=100)
    trading_fee_pct: float = Field(ge=0, le=10)


class PredictItFees(BaseModel):
    """PredictIt fee structure."""

    profit_fee_pct: float = Field(ge=0, le=100)  # 10% fee on profits
    withdrawal_fee_pct: float = Field(ge=0, le=100)  # 5% withdrawal fee


class Fees(BaseModel):
    """All platform fees."""

    kalshi: KalshiFees
    polymarket: PolymarketFees
    predictit: PredictItFees


class ApiKeys(BaseModel):
    """API authentication credentials."""

    kalshi_api_key: str
    kalshi_api_secret: str
    polymarket_api_key: Optional[str] = None


class Thresholds(BaseModel):
    """Detection and matching thresholds."""

    min_profit_pct: float = Field(gt=0, le=100)
    match_similarity: float = Field(ge=0, le=1)
    monitor_threshold_pct: float = Field(ge=0, le=10, default=2.0)


class CapitalTier(BaseModel):
    """Capital tier definition for alerts."""

    max: float = Field(gt=0)
    name: str
    color: str = Field(pattern="^(green|yellow|red)$")


class Discord(BaseModel):
    """Discord webhook configuration."""

    webhook_url: str = ""
    enabled: bool = True

    @field_validator("webhook_url")
    @classmethod
    def validate_webhook_url(cls, v: str, info) -> str:
        """Validate Discord webhook URL format if enabled."""
        # Get the 'enabled' field from the model being validated
        # If webhook is enabled, the URL must be valid
        if v and not v.startswith("https://discord.com/api/webhooks/"):
            raise ValueError(
                "Discord webhook URL must start with 'https://discord.com/api/webhooks/'"
            )
        return v


class Polling(BaseModel):
    """Polling configuration."""

    interval_seconds: int = Field(gt=0, le=3600)
    max_retries: int = Field(gt=0, le=10)
    backoff_base: float = Field(gt=1, le=10)


class EventFilters(BaseModel):
    """Event filtering configuration."""

    enabled: bool = False
    mode: str = Field(default="include", pattern="^(include|exclude)$")
    keywords: list[str] = Field(default_factory=list)

    @field_validator("keywords")
    @classmethod
    def normalize_keywords(cls, v: list[str]) -> list[str]:
        """Normalize keywords to lowercase for case-insensitive matching."""
        return [keyword.lower().strip() for keyword in v if keyword.strip()]


class Config(BaseModel):
    """Main configuration model."""

    api_keys: ApiKeys
    fees: Fees
    thresholds: Thresholds
    capital_tiers: list[CapitalTier]
    discord: Discord
    polling: Polling
    filters: EventFilters = Field(default_factory=EventFilters)

    @field_validator("capital_tiers")
    @classmethod
    def validate_tiers_ordered(cls, v: list[CapitalTier]) -> list[CapitalTier]:
        """Ensure capital tiers are ordered by max amount."""
        if len(v) < 1:
            raise ValueError("At least one capital tier must be defined")

        for i in range(len(v) - 1):
            if v[i].max >= v[i + 1].max:
                raise ValueError(
                    f"Capital tiers must be ordered: tier {i} max ({v[i].max}) "
                    f">= tier {i+1} max ({v[i+1].max})"
                )

        return v

    def get_tier_for_capital(self, capital: float) -> CapitalTier:
        """Get the appropriate tier for a given capital amount."""
        for tier in self.capital_tiers:
            if capital <= tier.max:
                return tier
        return self.capital_tiers[-1]


def load_config(config_path: Path = Path("config.yaml")) -> Config:
    """
    Load and validate configuration from YAML file.

    Args:
        config_path: Path to config.yaml file

    Returns:
        Validated Config object

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config validation fails
    """
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}\n"
            f"Create one based on config.example.yaml"
        )

    with open(config_path) as f:
        config_data = yaml.safe_load(f)

    try:
        config = Config(**config_data)
    except Exception as e:
        raise ValueError(f"Configuration validation failed: {e}") from e

    # Additional validation for Discord if enabled
    if config.discord.enabled and not config.discord.webhook_url:
        raise ValueError(
            "Discord webhook URL is required when discord.enabled is true"
        )

    return config

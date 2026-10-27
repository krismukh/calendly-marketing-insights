"""Configuration read from application settings (environment variables).

Every value has a default so that the modules can be imported and unit-tested without
an Azure environment. In Azure the values come from the Function App settings written by
infra/create_environment.sh.
"""

import os
from dataclasses import dataclass, field

SUBSCRIBED_EVENTS = ("invitee.created", "invitee.canceled")


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    storage_account_url: str = field(default_factory=lambda: os.getenv("STORAGE_ACCOUNT_URL", ""))
    bronze_container: str = field(default_factory=lambda: os.getenv("BRONZE_CONTAINER", "bronze"))
    calendly_landing_prefix: str = field(
        default_factory=lambda: os.getenv("CALENDLY_LANDING_PREFIX", "calendly/landing")
    )
    spend_landing_prefix: str = field(
        default_factory=lambda: os.getenv("SPEND_LANDING_PREFIX", "spend/landing")
    )
    spend_quarantine_prefix: str = field(
        default_factory=lambda: os.getenv("SPEND_QUARANTINE_PREFIX", "spend/quarantine")
    )
    spend_base_url: str = field(
        default_factory=lambda: os.getenv(
            "SPEND_BASE_URL",
            "https://dea-data-bucket.s3.us-east-1.amazonaws.com/calendly_spend_data",
        ).rstrip("/")
    )
    spend_lookback_days: int = field(
        default_factory=lambda: int(os.getenv("SPEND_LOOKBACK_DAYS", "35"))
    )
    verify_signature: bool = field(default_factory=lambda: _env_bool("VERIFY_SIGNATURE", False))
    signature_tolerance_seconds: int = field(
        default_factory=lambda: int(os.getenv("SIGNATURE_TOLERANCE_SECONDS", "300"))
    )
    calendly_signing_key: str = field(default_factory=lambda: os.getenv("CALENDLY_SIGNING_KEY", ""))
    subscribed_events: tuple[str, ...] = SUBSCRIBED_EVENTS


def load_settings() -> Settings:
    return Settings()

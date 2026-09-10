"""Environment-driven application settings.

Every value can be overridden with a ``HABIT_``-prefixed environment variable
or a line in ``.env``. Nothing here is a secret today, but the loader is
written so that adding one later does not mean hard-coding it: see
``.env.example`` for the full list.
"""

from __future__ import annotations

import functools
from enum import StrEnum
from pathlib import Path
from zoneinfo import ZoneInfo, available_timezones

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Repository root - ``<root>/app/config/settings.py`` is three levels down.
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]


class AppEnvironment(StrEnum):
    """Deployment environment the process believes it is running in."""

    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    """Log levels accepted by :mod:`logging`."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Settings(BaseSettings):
    """Runtime configuration, assembled from the environment.

    Attributes:
        app_env: Which environment the process is running in.
        database_url: SQLAlchemy URL. Relative SQLite paths are resolved
            against the project root so the app can be started from anywhere.
        log_level: Root log level for the application logger.
        log_dir: Directory that receives ``habit_tracker.log``.
        timezone: IANA timezone name that defines the user's day boundary.
        db_echo: Echo emitted SQL into the log (development aid).
        max_upload_mb: Hard cap on uploaded import files.
    """

    model_config = SettingsConfigDict(
        env_prefix="HABIT_",
        env_file=(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    app_env: AppEnvironment = AppEnvironment.DEVELOPMENT
    database_url: str = "sqlite:///data/habit_tracker.db"
    log_level: LogLevel = LogLevel.INFO
    log_dir: Path = Path("logs")
    timezone: str = "Asia/Kolkata"
    db_echo: bool = False
    max_upload_mb: int = Field(default=10, ge=1, le=200)

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        """Reject a timezone name that :mod:`zoneinfo` cannot resolve."""
        if value not in available_timezones():
            msg = f"Unknown IANA timezone {value!r}. Example: 'Asia/Kolkata', 'UTC'."
            raise ValueError(msg)
        return value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tzinfo(self) -> ZoneInfo:
        """The configured timezone as a :class:`~zoneinfo.ZoneInfo`."""
        return ZoneInfo(self.timezone)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_database_url(self) -> str:
        """``database_url`` with any relative SQLite path made absolute.

        ``sqlite:///data/habit_tracker.db`` means "relative to the project
        root", not "relative to whatever directory Streamlit was launched
        from" - which is what SQLAlchemy would otherwise assume.
        """
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            return self.database_url

        raw_path = self.database_url[len(prefix) :]
        if raw_path.startswith(":memory:") or raw_path == "":
            return self.database_url

        path = Path(raw_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"{prefix}{path.as_posix()}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_log_dir(self) -> Path:
        """``log_dir`` made absolute against the project root."""
        return self.log_dir if self.log_dir.is_absolute() else PROJECT_ROOT / self.log_dir

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_sqlite(self) -> bool:
        """Whether the configured database is SQLite."""
        return self.database_url.startswith("sqlite")

    @property
    def max_upload_bytes(self) -> int:
        """Upload cap expressed in bytes."""
        return self.max_upload_mb * 1024 * 1024


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Cached because reading ``.env`` on every call would be wasteful and
    because a single immutable instance keeps configuration honest.
    """
    return Settings()


def reload_settings() -> Settings:
    """Clear the settings cache and re-read the environment.

    Used by the test suite and by the Settings page after a change that must
    take effect without restarting the process.
    """
    get_settings.cache_clear()
    return get_settings()

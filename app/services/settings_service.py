"""Runtime settings the user can change.

Anything the application needs *before* the database exists lives in
``.env``. Everything a user might reasonably want to change from inside the
app lives here, in the ``app_settings`` table.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError as PydanticValidationError

from app.core.errors import ValidationError
from app.core.logging_config import get_logger
from app.domain.productivity.weights import SETTINGS_KEY, ProductivityWeights
from app.services.base import BaseService

logger = get_logger(__name__)

#: Keys with a defined meaning. Anything else is rejected, so a typo in a
#: settings key cannot silently create a setting nothing ever reads.
KNOWN_KEYS: dict[str, str] = {
    SETTINGS_KEY: "Weights used by the daily productivity score.",
    "time_tracking.prevent_overlap": "Refuse time entries that overlap an existing one.",
    "ui.theme": "Preferred colour theme: 'auto', 'light' or 'dark'.",
    "ui.units": "Measurement units: 'metric' or 'imperial'.",
    "analytics.heatmap_metric": "Default metric for the calendar heatmap.",
}


class SettingsService(BaseService):
    """Reading and writing the key/value settings table."""

    def get(self, key: str, default: Any = None) -> Any:
        """Return one setting's value, or ``default`` if unset."""
        with self.uow() as uow:
            value = uow.settings.get_value(key)
        return default if value is None else value

    def set(self, key: str, value: Any) -> None:
        """Write one setting.

        Raises:
            ValidationError: If the key is not one of :data:`KNOWN_KEYS`.
        """
        if key not in KNOWN_KEYS:
            raise ValidationError(
                "Unknown setting",
                field="key",
                value=key,
                user_hint=f"{key!r} is not a setting this application reads.",
            )
        with self.uow() as uow:
            uow.settings.set_value(key, value, KNOWN_KEYS[key])
            uow.commit()
        logger.info("Setting %s updated", key)

    def all_settings(self) -> dict[str, Any]:
        """Return every stored setting."""
        with self.uow() as uow:
            return uow.settings.all_values()

    # -- productivity weights ---------------------------------------------

    def weights(self) -> ProductivityWeights:
        """Return the configured productivity weights.

        Falls back to the defaults when nothing is stored, and also when
        what *is* stored no longer validates - a weight set saved before a
        component was renamed should degrade to the default rather than
        break every dashboard.
        """
        stored = self.get(SETTINGS_KEY)
        if not stored:
            return ProductivityWeights()
        try:
            return ProductivityWeights.model_validate(stored)
        except PydanticValidationError:
            logger.warning("Stored productivity weights are invalid; using defaults")
            return ProductivityWeights()

    def set_weights(self, weights: ProductivityWeights) -> ProductivityWeights:
        """Store a validated set of productivity weights."""
        self.set(SETTINGS_KEY, weights.model_dump())
        logger.info("Productivity weights updated")
        return weights

    def set_weights_from_values(self, **values: float) -> ProductivityWeights:
        """Validate raw numbers from a form and store them.

        Raises:
            ValidationError: If the weights do not sum to one, translated
                from pydantic's message into something a user can act on.
        """
        try:
            weights = ProductivityWeights(**values)
        except PydanticValidationError as error:
            first = error.errors()[0]
            raise ValidationError(
                "Invalid productivity weights",
                field="weights",
                user_hint=str(first.get("msg", "Those weights are not valid.")),
            ) from error
        return self.set_weights(weights)

    def reset_weights(self) -> ProductivityWeights:
        """Restore the default weights."""
        return self.set_weights(ProductivityWeights())


__all__ = ["KNOWN_KEYS", "SettingsService"]

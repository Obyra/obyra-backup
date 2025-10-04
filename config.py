"""Central configuration loader for the Flask application.

This module centralizes environment handling for the project and ensures
that required secrets are present before the rest of the app is
initialized.
"""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


load_dotenv()


def _to_bool(value: Optional[str], default: bool = False) -> bool:
    """Convert environment strings to boolean flags."""

    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


@dataclass
class AppConfig:
    """Representation of the runtime configuration for the app."""

    flask_env: str = os.getenv("FLASK_ENV", "development")
    secret_key: Optional[str] = os.getenv("SECRET_KEY")
    enable_reports: bool = _to_bool(os.getenv("ENABLE_REPORTS"))
    database_url: Optional[str] = os.getenv("DATABASE_URL")

    def apply(self, app) -> None:
        """Apply the configuration to the provided Flask app instance."""

        env = (self.flask_env or "").strip() or "development"
        env_lower = env.lower()
        secret = self.secret_key

        if env_lower == "production" and not secret:
            raise RuntimeError(
                "SECRET_KEY no configurada. Definila en tus variables de entorno"
                " antes de iniciar la aplicación en producción."
            )

        if not secret:
            secret = secrets.token_hex(32)
            logging.warning(
                "SECRET_KEY no definida. Se generó una clave temporal solo para"
                " este proceso. Definí SECRET_KEY en tu .env para mantener las"
                " sesiones activas entre reinicios."
            )

        self.secret_key = secret

        app.config["SECRET_KEY"] = secret
        app.secret_key = secret
        app.config["FLASK_ENV"] = env_lower
        app.config["ENABLE_REPORTS"] = self.enable_reports

        if self.database_url:
            app.config["DATABASE_URL"] = self.database_url


def load_config(app) -> AppConfig:
    """Load and apply the configuration, returning the data object."""

    config = AppConfig()
    config.apply(app)
    return config


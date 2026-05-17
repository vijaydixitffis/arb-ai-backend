"""Runtime config resolution: DB system_config table overrides .env / Settings defaults.

Usage:
    from app.core.db_config import db_config
    from app.core.config import settings

    temperature = db_config(db, "llm.temperature", settings.LLM_TEMPERATURE)
"""

from typing import Any
from sqlalchemy.orm import Session


def db_config(db: Session, key: str, default: Any) -> Any:
    """Return the DB system_config value for *key*, falling back to *default*.

    DB value takes precedence so that changes made via Admin → System Config
    take effect on the next request without a process restart.
    """
    from app.db.admin_models import SystemConfig
    row = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
    if row is not None and row.config_value is not None:
        return row.config_value
    return default

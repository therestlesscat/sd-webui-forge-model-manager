"""Database access for the extension.

Import ModelsDatabase or get_models_db from here; the modules behind it are
implementation detail.
"""
from .database import ModelsDatabase, SCHEMA_VERSION, get_models_db

__all__ = ["ModelsDatabase", "SCHEMA_VERSION", "get_models_db"]

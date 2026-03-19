from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from ..config.settings import config

logger = logging.getLogger(__name__)


class SQLManager:
    """Registry-backed SQLite access for manual structured queries."""

    _instance: "SQLManager | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "SQLManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    obj = super().__new__(cls)
                    obj._initialized = False
                    cls._instance = obj
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self._setup()
            self._initialized = True

    def _setup(self) -> None:
        self._registry = self._load_registry()
        self._engines: dict[str, Any] = {}

        for db_id, db_conf in self._registry.get("databases", {}).items():
            self._engines[db_id] = self._create_engine(db_conf)

    @staticmethod
    def _load_registry() -> dict[str, Any]:
        with open(config.db.table_registry_path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    @staticmethod
    def _create_engine(db_conf: dict[str, Any]):
        db_type = db_conf.get("type", "sqlite")
        if db_type != "sqlite":
            raise ValueError(f"Unsupported database type: {db_type}")

        db_path = Path(str(db_conf["path"])).expanduser()
        db_path.parent.mkdir(parents=True, exist_ok=True)

        return create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            pool_pre_ping=True,
        )

    def get_all_table_meta(self) -> dict[str, Any]:
        return self._registry.get("tables", {})

    def get_table_meta(self, table_name: str) -> dict[str, Any] | None:
        return self.get_all_table_meta().get(table_name)

    def get_registered_table_names(self) -> list[str]:
        return list(self.get_all_table_meta().keys())

    def get_physical_table_name(self, table_name: str) -> str:
        meta = self._require_table_meta(table_name)
        return str(meta.get("physical_name", table_name))

    def get_query_key(self, table_name: str) -> list[str]:
        meta = self._require_table_meta(table_name)
        return list(meta.get("query_key", []))

    def get_tool_name(self, table_name: str) -> str:
        meta = self._require_table_meta(table_name)
        return str(meta["tool_name"])

    def _require_table_meta(self, table_name: str) -> dict[str, Any]:
        meta = self.get_table_meta(table_name)
        if meta is None:
            raise KeyError(f"Unregistered table: {table_name}")
        return meta

    def get_engine(self, db_id: str):
        if db_id not in self._engines:
            raise KeyError(f"Unknown db_id: {db_id}")
        return self._engines[db_id]

    def execute(
        self,
        sql: str,
        db_id: str = "main_db",
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        engine = self.get_engine(db_id)
        with engine.begin() as conn:
            result = conn.execute(text(sql), params or {})
            if not result.returns_rows:
                return []
            return [dict(row) for row in result.mappings().all()]

    def list_tables(self, db_id: str = "main_db") -> list[str]:
        return inspect(self.get_engine(db_id)).get_table_names()

    def table_exists(self, table_name: str, db_id: str = "main_db") -> bool:
        return inspect(self.get_engine(db_id)).has_table(table_name)

    def get_table_columns(self, table_name: str, db_id: str = "main_db") -> list[str]:
        inspector = inspect(self.get_engine(db_id))
        if not inspector.has_table(table_name):
            return []
        return [column["name"] for column in inspector.get_columns(table_name)]

    def validate_registered_tables(self) -> dict[str, dict[str, Any]]:
        report: dict[str, dict[str, Any]] = {}

        for table_name, meta in self.get_all_table_meta().items():
            db_id = str(meta["db_id"])
            physical_name = str(meta.get("physical_name", table_name))
            query_key = list(meta.get("query_key", []))
            table_exists = self.table_exists(physical_name, db_id=db_id)
            actual_columns = self.get_table_columns(physical_name, db_id=db_id)
            missing_query_key_columns = [
                column for column in query_key if column not in actual_columns
            ]

            report[table_name] = {
                "table_exists": table_exists,
                "physical_name": physical_name,
                "query_key": query_key,
                "tool_name": meta.get("tool_name"),
                "missing_query_key_columns": missing_query_key_columns,
            }

        return report

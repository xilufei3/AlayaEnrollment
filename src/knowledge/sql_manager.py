"""
SQLManager
──────────
纯基础设施，只负责：
  - 数据库连接管理（连接池）
  - 从 table_registry.yaml 读取表结构
  - 执行原始 SQL，返回结果

不包含任何业务逻辑（不做表路由、不生成 SQL、不调用 LLM）。
LLM 选表、SQL 生成等逻辑由上层调用方负责。
"""
from __future__ import annotations

import logging
import threading
from typing import Any

import yaml
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.pool import StaticPool

from ..config.settings import config

logger = logging.getLogger(__name__)


class SQLManager:
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
        logger.info("SQLManager: 初始化 ...")
        self._registry = self._load_registry()
        self._engines: dict[str, Any] = {}

        for db_id, db_conf in self._registry.get("databases", {}).items():
            engine = create_engine(
                f"sqlite:///{db_conf['path']}",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
                pool_pre_ping=True,
            )
            self._engines[db_id] = engine
            logger.info("数据库连接就绪：%s → %s", db_id, db_conf["path"])

        logger.info("SQLManager: 初始化完成，共 %d 个数据库", len(self._engines))

    @staticmethod
    def _load_registry() -> dict:
        with open(config.db.table_registry_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    # ════════════════════════════════════════════════════════
    # 元数据查询（供上层 LLM 构建 prompt 用）
    # ════════════════════════════════════════════════════════

    def get_all_table_meta(self) -> dict[str, Any]:
        """返回 registry 中所有表的元数据"""
        return self._registry.get("tables", {})

    def get_table_meta(self, table_name: str) -> dict | None:
        """返回单张表的元数据，不存在返回 None"""
        return self._registry.get("tables", {}).get(table_name)

    def get_engine(self, db_id: str):
        """返回指定 db_id 的 SQLAlchemy engine"""
        if db_id not in self._engines:
            raise KeyError(f"未知的 db_id：{db_id}")
        return self._engines[db_id]

    # ════════════════════════════════════════════════════════
    # SQL 执行
    # ════════════════════════════════════════════════════════

    def execute(
        self,
        sql: str,
        db_id: str = "main_db",
        params: dict | None = None,
    ) -> list[dict[str, Any]]:
        """
        执行 SQL，返回行列表。
        上层负责构造 SQL，此处只负责执行。

        Args:
            sql    : 待执行的 SQL 字符串
            db_id  : 目标数据库 ID，默认 main_db
            params : 绑定参数（防注入），例如 {"province": "广东"}
                     SQL 中对应写 :province

        Returns:
            list[dict]，每项为一行数据
        """
        engine = self.get_engine(db_id)
        try:
            with engine.connect() as conn:
                result = conn.execute(text(sql), params or {})
                columns = list(result.keys())
                return [dict(zip(columns, row)) for row in result.fetchall()]
        except Exception as e:
            logger.error("SQL 执行失败 [%s]：%s\nSQL: %s", db_id, e, sql)
            raise

    # ════════════════════════════════════════════════════════
    # 数据库实际状态查询（不依赖 registry，查真实表结构）
    # ════════════════════════════════════════════════════════

    def list_tables(self, db_id: str = "main_db") -> list[str]:
        """返回数据库中实际存在的表名列表"""
        engine = self.get_engine(db_id)
        return inspect(engine).get_table_names()

    def table_exists(self, table_name: str, db_id: str = "main_db") -> bool:
        """检查表是否实际存在于数据库"""
        return table_name in self.list_tables(db_id)

    def get_table_columns(self, table_name: str, db_id: str = "main_db") -> list[str]:
        """返回表的实际列名列表"""
        engine = self.get_engine(db_id)
        columns = inspect(engine).get_columns(table_name)
        return [col["name"] for col in columns]

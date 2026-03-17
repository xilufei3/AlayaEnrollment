"""
SQLManager
──────────
纯基础设施，只负责：
  - 从 table_registry.yaml 读取表结构与数据库连接配置
  - 数据库连接管理（连接池，支持 SQLite / MySQL / PostgreSQL 等）
  - 执行原始 SQL，返回结果
  - 为上层 LLM 提供格式化的 schema 描述

不包含任何业务逻辑（不做表路由、不生成 SQL、不调用 LLM）。
LLM 选表、SQL 生成等逻辑由上层调用方负责。

配置：
  - TABLE_REGISTRY_PATH  环境变量（可选）：覆盖默认 registry 路径
  - 默认路径：与本文件同目录的 table_registry.yaml
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

logger = logging.getLogger(__name__)

# registry 默认与本文件同目录
_DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parent / "table_registry.yaml"
# 用于解析 registry 中相对路径（相对于仓库根目录）
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_registry_path() -> Path:
    env_path = os.getenv("TABLE_REGISTRY_PATH")
    if env_path:
        p = Path(env_path)
        return p if p.is_absolute() else _REPO_ROOT / p
    return _DEFAULT_REGISTRY_PATH


def _build_engine(db_id: str, db_conf: dict) -> Any:
    """根据 registry 条目构建 SQLAlchemy engine。

    支持两种配置方式：
      - url  字段：直接作为 SQLAlchemy 连接字符串（适用于 MySQL/PostgreSQL 等）
      - path 字段：构建 SQLite 连接（路径若为相对路径则相对于仓库根目录）
    """
    if "url" in db_conf:
        url = db_conf["url"]
        logger.info("数据库连接就绪（url 模式）：%s", db_id)
        return create_engine(url, pool_pre_ping=True)

    if "path" in db_conf:
        raw_path = db_conf["path"]
        p = Path(raw_path)
        abs_path = p if p.is_absolute() else (_REPO_ROOT / p).resolve()
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        db_uri = "sqlite:///" + str(abs_path).replace("\\", "/")
        logger.info("数据库连接就绪（SQLite）：%s → %s", db_id, abs_path)
        return create_engine(
            db_uri,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            pool_pre_ping=True,
        )

    raise ValueError(
        f"数据库 '{db_id}' 配置缺少 'url' 或 'path' 字段。"
    )


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
        self._registry_path = _resolve_registry_path()
        self._registry = self._load_registry(self._registry_path)
        self._engines: dict[str, Any] = {}

        for db_id, db_conf in self._registry.get("databases", {}).items():
            self._engines[db_id] = _build_engine(db_id, db_conf)

        logger.info("SQLManager: 初始化完成，共 %d 个数据库", len(self._engines))

    @staticmethod
    def _load_registry(path: Path) -> dict:
        if not path.exists():
            logger.warning("table_registry.yaml 未找到：%s", path)
            return {"databases": {}, "tables": {}}
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    # ════════════════════════════════════════════════════════
    # 元数据查询（供上层 LLM 构建 prompt 用）
    # ════════════════════════════════════════════════════════

    def get_all_table_meta(self) -> dict[str, Any]:
        """返回 registry 中所有表的元数据"""
        return self._registry.get("tables", {})

    def get_table_meta(self, table_name: str) -> dict | None:
        """返回单张表的元数据，不存在返回 None"""
        return self._registry.get("tables", {}).get(table_name)

    def get_schema_for_prompt(self, table_names: list[str] | None = None) -> str:
        """返回格式化的 schema 描述，供 LLM prompt 使用。

        Args:
            table_names: 指定只返回这些表的 schema；为 None 时返回全部。

        Returns:
            可直接嵌入 prompt 的多行文本字符串。
        """
        tables: dict[str, Any] = self._registry.get("tables", {})
        if table_names is not None:
            tables = {k: v for k, v in tables.items() if k in table_names}

        if not tables:
            return "（无可用表结构）"

        lines: list[str] = []
        for table_name, meta in tables.items():
            db_id = meta.get("db_id", "main_db")
            description = meta.get("description", "")
            lines.append(f"【{table_name}】（数据库：{db_id}）")
            if description:
                lines.append(f"  说明：{description}")
            use_when: list[str] = meta.get("use_when", [])
            if use_when:
                lines.append("  适用场景：")
                for uw in use_when:
                    lines.append(f"    · {uw}")
            columns: dict[str, str] = meta.get("columns", {})
            if columns:
                lines.append("  字段：")
                for col_name, col_desc in columns.items():
                    lines.append(f"    {col_name}：{col_desc}")
            lines.append("")

        return "\n".join(lines).rstrip()

    def get_engine(self, db_id: str):
        """返回指定 db_id 的 SQLAlchemy engine"""
        if db_id not in self._engines:
            raise KeyError(f"未知的 db_id：'{db_id}'。已注册：{list(self._engines)}")
        return self._engines[db_id]

    def reload_registry(self) -> None:
        """热重载 table_registry.yaml（只更新元数据，不重建连接池）。"""
        with self._lock:
            self._registry = self._load_registry(self._registry_path)
            logger.info("SQLManager: registry 已重新加载")

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

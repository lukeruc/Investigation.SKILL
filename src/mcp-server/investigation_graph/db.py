"""数据库连接管理、Schema 初始化与活跃案件路径管理。

本模块不持有长期活跃的 sqlite3.Connection 对象，只保存当前活跃案件的
数据库文件路径字符串。每次工具调用通过 `db_connection(path)` 上下文
独立开闭连接，避免全局连接的生命周期和并发问题。
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


# ---------------------------------------------------------------------------
# Time helper
# ---------------------------------------------------------------------------


def now_iso() -> str:
    """返回当前 UTC 时间的 ISO 8601 字符串。"""
    return datetime.now(timezone.utc).isoformat()

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    goal TEXT NOT NULL DEFAULT '',
    depth_limit INTEGER NOT NULL DEFAULT 3,
    round_number INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'paused', 'completed')),
    seed_node_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (seed_node_id) REFERENCES nodes(id)
);

CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    exploration_status TEXT NOT NULL DEFAULT 'unexplored'
        CHECK(exploration_status IN ('unexplored', 'exploring', 'explored', 'partial', 'skipped', 'exhausted')),
    confidence TEXT NOT NULL DEFAULT 'medium' CHECK(confidence IN ('high', 'medium', 'low')),
    anomaly_flags TEXT NOT NULL DEFAULT '[]',
    first_seen TEXT NOT NULL,
    last_updated TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    type TEXT NOT NULL,
    direction TEXT NOT NULL DEFAULT 'directed' CHECK(direction IN ('directed', 'undirected')),
    body TEXT NOT NULL DEFAULT '',
    verification_status TEXT NOT NULL DEFAULT 'unverified'
        CHECK(verification_status IN ('unverified', 'verified', 'contradicted', 'retracted')),
    confidence TEXT NOT NULL DEFAULT 'medium' CHECK(confidence IN ('high', 'medium', 'low')),
    intensity REAL NOT NULL DEFAULT 0.5 CHECK(intensity BETWEEN 0.0 AND 1.0),
    contradicted_by TEXT NOT NULL DEFAULT '[]',
    anomaly_flags TEXT NOT NULL DEFAULT '[]',
    first_seen TEXT NOT NULL,
    last_updated TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES nodes(id),
    FOREIGN KEY (target_id) REFERENCES nodes(id)
);

CREATE TABLE IF NOT EXISTS source_chains (
    id TEXT PRIMARY KEY,
    target_type TEXT NOT NULL CHECK(target_type IN ('node', 'edge')),
    target_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'web_search',
    source_reliability TEXT NOT NULL DEFAULT 'X' CHECK(source_reliability IN ('A', 'B', 'C', 'D', 'E', 'X')),
    info_credibility TEXT NOT NULL DEFAULT '6' CHECK(info_credibility IN ('1', '2', '3', '4', '5', '6')),
    discovery_time TEXT NOT NULL,
    discovery_agent TEXT,
    discovery_context TEXT,
    raw_data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (target_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES edges(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS merge_history (
    id TEXT PRIMARY KEY,
    merged_node_id TEXT NOT NULL,
    absorbed_node_ids TEXT NOT NULL,
    identity_edge_id TEXT,
    reason TEXT NOT NULL,
    evidence_snapshot TEXT,
    merged_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS identity_evidence (
    id TEXT PRIMARY KEY,
    identity_edge_id TEXT NOT NULL,
    signal_name TEXT NOT NULL,
    signal_value TEXT,
    direction TEXT NOT NULL CHECK(direction IN ('supporting', 'opposing', 'neutral')),
    weight TEXT NOT NULL DEFAULT 'medium' CHECK(weight IN ('high', 'medium', 'low')),
    source_entry_id TEXT,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (identity_edge_id) REFERENCES edges(id),
    FOREIGN KEY (source_entry_id) REFERENCES source_chains(id)
);

CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
CREATE INDEX IF NOT EXISTS idx_nodes_status ON nodes(exploration_status);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(type);
CREATE INDEX IF NOT EXISTS idx_edges_vstatus ON edges(verification_status);
CREATE INDEX IF NOT EXISTS idx_source_chains_target ON source_chains(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_merge_history_node ON merge_history(merged_node_id);
CREATE INDEX IF NOT EXISTS idx_identity_evidence_edge ON identity_evidence(identity_edge_id);
"""

# ---------------------------------------------------------------------------
# Active case path management
# ---------------------------------------------------------------------------

_active_case_path: Path | None = None
_lock = threading.Lock()


class NoActiveCaseError(Exception):
    """当前没有活跃案件时被抛出。"""

    pass


def set_active_case(path: str | Path) -> None:
    """切换活跃案件路径。"""
    global _active_case_path
    with _lock:
        _active_case_path = Path(path)


def get_active_case() -> Path:
    """返回当前活跃案件路径；如无则抛出 NoActiveCaseError。"""
    with _lock:
        if _active_case_path is None:
            raise NoActiveCaseError("no active case. call session_create or session_open first")
        return _active_case_path


def clear_active_case() -> None:
    """清除活跃案件路径（主要用于测试）。"""
    global _active_case_path
    with _lock:
        _active_case_path = None


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

@contextmanager
def db_connection(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """打开一个配置好的 SQLite 连接，退出上下文时自动关闭。

    参数：
        db_path: 数据库文件路径。默认为当前活跃案件路径。
    """
    if db_path is None:
        db_path = get_active_case()

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str | Path) -> None:
    """在指定路径创建新的 case.db 并执行 DDL。"""
    with db_connection(db_path) as conn:
        conn.executescript(DDL)


def ensure_schema(db_path: str | Path) -> None:
    """确保指定数据库已初始化 schema（用于打开旧案件时 schema 升级）。"""
    with db_connection(db_path) as conn:
        conn.executescript(DDL)

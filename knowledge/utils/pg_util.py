"""PostgreSQL 连接工具（Lumy 结构化链路）

连接配置读 knowledge/.env：
  PG_HOST / PG_PORT / PG_USER / PG_PASSWORD / PG_DB
"""

import os
import threading
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

_lock = threading.Lock()
_conn = None


def get_pg_conn():
    """获取全局 PG 连接（单例，线程安全）"""
    global _conn
    with _lock:
        if _conn is None or _conn.closed:
            _conn = psycopg2.connect(
                host=os.getenv("PG_HOST", "192.168.245.128"),
                port=int(os.getenv("PG_PORT", "5432")),
                user=os.getenv("PG_USER", "postgres"),
                password=os.getenv("PG_PASSWORD", ""),
                dbname=os.getenv("PG_DB", "lumy"),
            )
        return _conn


def close_pg_conn():
    global _conn
    with _lock:
        if _conn is not None and not _conn.closed:
            _conn.close()
        _conn = None

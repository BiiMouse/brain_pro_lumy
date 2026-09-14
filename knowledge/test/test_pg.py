"""PostgreSQL 连通性验证（Lumy 结构化链路 Step 0）

验证内容：
1. 读取 knowledge/.env 中的 PG_* 配置
2. 连接 PostgreSQL（lumy 库不存在时自动创建）
3. 建表 → 插入 → 查询 → 清理 冒烟测试

使用方法：
    cd D:\AIpractise\shopkeer_brain - 副本
    .venv/Scripts/python.exe knowledge/test/test_pg.py

.env 需要包含：
    PG_HOST=192.168.245.128
    PG_PORT=5432
    PG_USER=postgres
    PG_PASSWORD=<你的密码>
    PG_DB=lumy
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# 加载 knowledge/.env（脚本在 knowledge/test/ 下，向上两级）
PROJECT_KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_KNOWLEDGE_DIR / ".env")

import psycopg2


def get_pg_config() -> dict:
    """读取 PG 连接配置"""
    config = {
        "host": os.getenv("PG_HOST", "192.168.245.128"),
        "port": int(os.getenv("PG_PORT", "5432")),
        "user": os.getenv("PG_USER", "postgres"),
        "password": os.getenv("PG_PASSWORD", ""),
        "dbname": os.getenv("PG_DB", "lumy"),
    }
    if not config["password"]:
        print("[FAIL] PG_PASSWORD 未配置，请在 knowledge/.env 中添加 PG_* 配置")
        sys.exit(1)
    return config


def ensure_database(config: dict):
    """目标库不存在时连接默认 postgres 库创建"""
    conn = psycopg2.connect(
        host=config["host"], port=config["port"],
        user=config["user"], password=config["password"],
        dbname="postgres",
    )
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s",
                        (config["dbname"],))
            if cur.fetchone():
                print(f"[OK] 数据库 {config['dbname']} 已存在")
            else:
                cur.execute(f'CREATE DATABASE "{config["dbname"]}"')
                print(f"[OK] 数据库 {config['dbname']} 创建成功")
    finally:
        conn.close()


def smoke_test(config: dict):
    """建表 → 插入 → 查询 → 清理"""
    conn = psycopg2.connect(**config)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pg_smoke_test (
                    id SERIAL PRIMARY KEY,
                    model VARCHAR(100) NOT NULL,
                    attrs JSONB
                )
            """)
            cur.execute(
                "INSERT INTO pg_smoke_test (model, attrs) VALUES (%s, %s)",
                ("MAX20029ATIA/V+", '{"package": "TQFN-EP", "channels": 4}'),
            )
            conn.commit()

            cur.execute(
                "SELECT model, attrs->>'package' FROM pg_smoke_test "
                "WHERE attrs @> '{\"channels\": 4}'"
            )
            row = cur.fetchone()
            assert row == ("MAX20029ATIA/V+", "TQFN-EP"), f"查询结果异常: {row}"
            print(f"[OK] JSONB 写入与 @> 查询正常: {row}")

            cur.execute("DROP TABLE pg_smoke_test")
            conn.commit()
            print("[OK] 冒烟表已清理")
    finally:
        conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("PostgreSQL 连通性验证（Lumy Step 0）")
    print("=" * 60)
    config = get_pg_config()
    print(f"目标: {config['user']}@{config['host']}:{config['port']}"
          f"/{config['dbname']}")
    ensure_database(config)
    smoke_test(config)
    print("\n全部通过 ✓  PG 就绪，可以进入 Step 1/4")

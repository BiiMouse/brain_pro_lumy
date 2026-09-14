### Lumy 链路B-步骤4 结构化型号入库（PostgreSQL）

"""
把 models.json + regions.json 写入 PostgreSQL（幂等：同一文件重导入先删旧行）。
"""

import json
from pathlib import Path
from typing import Dict

from knowledge.processor.import_process.base import BaseNode
from knowledge.processor.import_process.state import ImportGraphState
from knowledge.utils.pg_util import get_pg_conn

SCHEMA_DIR = Path(__file__).resolve().parents[3] / "schema"
DDL_PATH = SCHEMA_DIR / "lumy_pg.sql"


def ensure_schema(conn):
    """幂等建表（DDL 全部 IF NOT EXISTS）"""
    with open(DDL_PATH, encoding="utf-8") as f:
        ddl = f.read()
    with conn.cursor() as cur:
        cur.execute(ddl)
    conn.commit()


class PgImportNode(BaseNode):
    """链路B 节点：models.json/regions.json → PostgreSQL"""
    name = "pg_import"

    def process(self, state: ImportGraphState) -> ImportGraphState:
        models_path = state.get("models_path")
        regions_path = state.get("regions_path")
        pdf_tables_path = state.get("pdf_tables_path")
        if not models_path:
            raise ValueError("models_path 为空（请先运行 model_extract）")

        with open(models_path, encoding="utf-8") as f:
            models = json.load(f)
        regions = {}
        if regions_path and Path(regions_path).exists():
            with open(regions_path, encoding="utf-8") as f:
                regions = json.load(f)
        pdf_tables = {}
        if pdf_tables_path and Path(pdf_tables_path).exists():
            with open(pdf_tables_path, encoding="utf-8") as f:
                pdf_tables = json.load(f)

        conn = get_pg_conn()
        ensure_schema(conn)
        counts = self.import_pdf(conn, models, regions, pdf_tables)

        state["pg_counts"] = counts
        self.log_step("done", f"{models['file_name']} 入库: {counts}")
        return state

    def import_pdf(self, conn, models: Dict, regions: Dict, pdf_tables: Dict) -> Dict:
        file_name = models["file_name"]
        with conn.cursor() as cur:
            # 幂等：删旧数据（级联清空子表）
            cur.execute("DELETE FROM pdf_sources WHERE file_name = %s", (file_name,))
            cur.execute(
                "INSERT INTO pdf_sources (file_name, pdf_path, page_count) "
                "VALUES (%s, %s, %s) RETURNING id",
                (file_name,
                 pdf_tables.get("pdf_path") or "",
                 pdf_tables.get("page_count") or models.get("page_count")),
            )
            pdf_id = cur.fetchone()[0]

            for r in regions.get("regions", []):
                cur.execute(
                    "INSERT INTO regions (pdf_id, page_start, page_end, "
                    "region_type, title, role) VALUES (%s,%s,%s,%s,%s,%s)",
                    (pdf_id, r["page_start"], r["page_end"],
                     r["type"], (r.get("title") or "")[:200], r.get("role", "")),
                )

            for f in models.get("families", []):
                cur.execute(
                    "INSERT INTO families (pdf_id, family_name, family_type, "
                    "notes, evidence_page) VALUES (%s,%s,%s,%s,%s)",
                    (pdf_id, f["family_name"], f.get("family_type", "normal"),
                     f.get("notes", ""), f.get("evidence_page")),
                )

            for p in models.get("ppns", []):
                cur.execute(
                    "INSERT INTO ppns (pdf_id, family_name, ppn, attributes, "
                    "evidence_page, evidence) VALUES (%s,%s,%s,%s,%s,%s)",
                    (pdf_id, p.get("family") or "", p["ppn"],
                     json.dumps(p.get("attributes") or {}, ensure_ascii=False),
                     p.get("evidence_page"), (p.get("evidence") or "")[:500]),
                )

            for o in models.get("opns", []):
                cur.execute(
                    "INSERT INTO opns (pdf_id, family_name, ppn, opn, package, "
                    "packing, notes, evidence_page) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (pdf_id, o.get("family") or "", o.get("ppn") or "", o["opn"],
                     (o.get("package") or "")[:200], (o.get("packing") or "")[:200],
                     o.get("notes", ""), o.get("evidence_page")),
                )

            for n in models.get("naming_rules", []):
                cur.execute(
                    "INSERT INTO naming_rules (pdf_id, family_name, pattern, "
                    "positions, source_page, expanded) VALUES (%s,%s,%s,%s,%s,%s)",
                    (pdf_id, n.get("family") or "", n.get("pattern") or "",
                     json.dumps(n.get("positions") or [], ensure_ascii=False),
                     n.get("source_page"), bool(n.get("expanded", False))),
                )
        conn.commit()
        return {
            "families": len(models.get("families", [])),
            "ppns": len(models.get("ppns", [])),
            "opns": len(models.get("opns", [])),
            "naming_rules": len(models.get("naming_rules", [])),
            "regions": len(regions.get("regions", [])),
        }


# ==================== 独立运行入口（5 份 models.json 批量入库 + 验证查询） ====================

if __name__ == "__main__":
    import sys
    from knowledge.processor.import_process.base import setup_logging

    setup_logging()
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("referencePDF/lumy_extract")

    conn = get_pg_conn()
    ensure_schema(conn)

    total = {"families": 0, "ppns": 0, "opns": 0, "naming_rules": 0}
    for models_json in sorted(root.glob("*/models.json")):
        work = models_json.parent
        state = {
            "models_path": str(models_json),
            "regions_path": str(work / "regions.json"),
            "pdf_tables_path": str(work / "pdf_tables.json"),
        }
        node = PgImportNode()
        state = node(state)
        counts = state["pg_counts"]
        for k in total:
            total[k] += counts[k]
        print(f"{work.name}: {counts}")
    print(f"合计入库: {total}")

    # ============ 验证查询 ============
    print("\n===== 验证1：家族 → PPN → OPN 遍历（MAX20029B） =====")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT p.ppn, COUNT(o.id) AS opn_count
            FROM ppns p LEFT JOIN opns o ON o.pdf_id = p.pdf_id AND o.ppn = p.ppn
            WHERE p.family_name = 'MAX20029B'
            GROUP BY p.ppn ORDER BY p.ppn
        """)
        for row in cur.fetchall():
            print("  ", row)

    print("\n===== 验证2：OPN 反查（TL432BIDBZR → PPN/家族/文件） =====")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT o.opn, o.ppn, o.family_name, s.file_name, o.package
            FROM opns o JOIN pdf_sources s ON s.id = o.pdf_id
            WHERE o.opn = 'TL432BIDBZR'
        """)
        for row in cur.fetchall():
            print("  ", row)

    print("\n===== 验证3：JSONB 属性查询（max20029 扩频 +3% 的 PPN） =====")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT p.ppn, p.attributes->>'扩频' AS spread
            FROM ppns p JOIN pdf_sources s ON s.id = p.pdf_id
            WHERE s.file_name LIKE 'max20029%'
              AND p.attributes @> '{"扩频": "+3%"}'::jsonb
            ORDER BY p.ppn LIMIT 6
        """)
        for row in cur.fetchall():
            print("  ", row)

    print("\n===== 验证4：跨文档 OPN 计数 =====")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.file_name, COUNT(o.id) FROM opns o
            JOIN pdf_sources s ON s.id = o.pdf_id
            GROUP BY s.file_name ORDER BY s.file_name
        """)
        for row in cur.fetchall():
            print("  ", row)

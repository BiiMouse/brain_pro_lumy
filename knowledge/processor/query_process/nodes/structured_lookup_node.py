### Lumy 查询-步骤2 结构化检索节点（PostgreSQL 型号库）

"""
按意图查询 PG 型号库，产出 structured_docs（带证据页码）：
  - model_list:    家族 → PPN（→ OPN 计数/清单）
  - model_detail:  型号 → 层级归属（OPN 反查 PPN/家族 + 封装/包装）
  - rule_explain:  命名规则文法（positions 逐位含义）
  - 其他意图:      实体对齐结果作为上下文补充 + 提供向量检索的文件过滤

对齐策略（Lumy 规则）：严格对齐（OPN/PPN/家族精确匹配）优先，
失败降级前缀对齐（用户输入常是型号前缀或家族名）。
"""

from typing import Dict, Any, List

from knowledge.processor.query_process.base import BaseNode
from knowledge.processor.query_process.state import QueryGraphState
from knowledge.utils.pg_util import get_pg_conn


class StructuredLookupNode(BaseNode):
    name = "structured_lookup"

    def process(self, state: QueryGraphState) -> QueryGraphState:
        intent = state.get("intent", "param_query")
        models = state.get("model_entities") or []
        structured_docs: List[Dict[str, Any]] = []

        if models:
            with get_pg_conn() as conn:
                with conn.cursor() as cur:
                    for token in models[:4]:
                        for doc in self.lookup_model(cur, token):
                            structured_docs.append(doc)
                    # 意图定向补充
                    if intent == "model_list":
                        structured_docs.extend(self.list_models(cur, models))
                    if intent == "rule_explain":
                        structured_docs.extend(self.lookup_rules(cur, models))

        state["structured_docs"] = structured_docs
        # 向量检索的文件过滤：从命中型号反查所在文件
        files = sorted({d["file"] for d in structured_docs if d.get("file")})
        state["entity_files"] = files
        self.logger.info(
            f"结构化检索(PG)命中 {len(structured_docs)} 条 | 文件过滤: {files}")
        return state

    # ---------- 对齐与查询 ----------

    def lookup_model(self, cur, token: str) -> List[Dict[str, Any]]:
        """单个型号 token 的层级解析：严格对齐 → 前缀对齐"""
        docs = []
        # 1. 严格对齐：OPN 精确
        cur.execute(
            "SELECT o.opn, o.ppn, o.family_name, o.package, o.packing, "
            "s.file_name, o.evidence_page FROM opns o "
            "JOIN pdf_sources s ON s.id = o.pdf_id WHERE o.opn = %s LIMIT 20",
            (token,))
        for r in cur.fetchall():
            docs.append(self._row(cur, "opn", token, r))
        # 2. 严格对齐：PPN 精确
        cur.execute(
            "SELECT p.ppn, p.family_name, p.attributes, p.evidence_page, "
            "s.file_name FROM ppns p "
            "JOIN pdf_sources s ON s.id = p.pdf_id WHERE p.ppn = %s LIMIT 20",
            (token,))
        for r in cur.fetchall():
            docs.append(self._row(cur, "ppn", token, r))
        # 3. 家族精确
        cur.execute(
            "SELECT f.family_name, f.family_type, f.notes, f.evidence_page, "
            "s.file_name FROM families f "
            "JOIN pdf_sources s ON s.id = f.pdf_id WHERE f.family_name = %s LIMIT 10",
            (token,))
        for r in cur.fetchall():
            docs.append(self._row(cur, "family", token, r))

        if docs:
            return docs
        # 4. 前缀对齐（通配下沉：输入是家族或PPN前缀 → 列出下一级清单）
        cur.execute(
            "SELECT p.ppn, p.family_name, p.attributes, p.evidence_page, "
            "s.file_name FROM ppns p "
            "JOIN pdf_sources s ON s.id = p.pdf_id "
            "WHERE p.ppn LIKE %s LIMIT 20", (token + "%",))
        for r in cur.fetchall():
            docs.append(self._row(cur, "ppn_prefix", token, r))
        cur.execute(
            "SELECT o.opn, o.ppn, o.family_name, o.package, o.packing, "
            "s.file_name, o.evidence_page FROM opns o "
            "JOIN pdf_sources s ON s.id = o.pdf_id "
            "WHERE o.opn LIKE %s LIMIT 30", (token + "%",))
        for r in cur.fetchall()[:15]:
            docs.append(self._row(cur, "opn_prefix", token, r))
        return docs

    def list_models(self, cur, models: List[str]) -> List[Dict[str, Any]]:
        """model_list：家族 → PPN 清单（带 OPN 计数）"""
        docs = []
        for token in models[:3]:
            cur.execute(
                "SELECT f.family_name, s.file_name FROM families f "
                "JOIN pdf_sources s ON s.id = f.pdf_id "
                "WHERE f.family_name = %s", (token,))
            fam_rows = cur.fetchall()
            if not fam_rows:
                cur.execute(
                    "SELECT DISTINCT p.family_name, s.file_name FROM ppns p "
                    "JOIN pdf_sources s ON s.id = p.pdf_id "
                    "WHERE p.family_name = %s OR p.ppn LIKE %s LIMIT 5",
                    (token, token + "%"))
                fam_rows = cur.fetchall()
            for fam, fname in fam_rows:
                if not fam:
                    continue
                cur.execute(
                    "SELECT p.ppn, p.evidence_page, "
                    "(SELECT COUNT(*) FROM opns o WHERE o.pdf_id = p.pdf_id "
                    " AND o.ppn = p.ppn) AS opn_count "
                    "FROM ppns p JOIN pdf_sources s ON s.id = p.pdf_id "
                    "WHERE p.family_name = %s ORDER BY p.ppn LIMIT 40", (fam,))
                ppns = cur.fetchall()
                docs.append({
                    "type": "family_ppn_list", "match": fam, "file": fname,
                    "page": ppns[0][1] if ppns else None,
                    "payload": {
                        "family": fam,
                        "ppns": [{"ppn": r[0], "page": r[1], "opn_count": r[2]}
                                 for r in ppns],
                    },
                })
        return docs

    def lookup_rules(self, cur, models: List[str]) -> List[Dict[str, Any]]:
        """rule_explain：命名规则文法（家族名或型号前缀匹配）"""
        docs = []
        for token in models[:3]:
            cur.execute(
                "SELECT n.family_name, n.pattern, n.positions, n.source_page, "
                "s.file_name FROM naming_rules n "
                "JOIN pdf_sources s ON s.id = n.pdf_id "
                "WHERE n.family_name = %s OR %s LIKE n.family_name || '%%' "
                "OR n.family_name || '%%' LIKE %s || '%%' LIMIT 5",
                (token, token, token))
            for fam, pattern, positions, page, fname in cur.fetchall():
                docs.append({
                    "type": "naming_rule", "match": token, "file": fname,
                    "page": page,
                    "payload": {"family": fam, "pattern": pattern,
                                "positions": positions},
                })
        return docs

    def _row(self, cur, rtype, token, r) -> Dict[str, Any]:
        """统一行封装（opn/ppn/family 各查询列不同，按长度适配）"""
        doc = {"type": rtype, "match": token, "file": None, "page": None,
               "payload": {}}
        if rtype in ("opn", "opn_prefix"):
            opn, ppn, fam, pkg, packing, fname, page = r
            doc.update(file=fname, page=page,
                       payload={"opn": opn, "ppn": ppn, "family": fam,
                                "package": pkg, "packing": packing})
        elif rtype in ("ppn", "ppn_prefix"):
            ppn, fam, attrs, page, fname = r
            doc.update(file=fname, page=page,
                       payload={"ppn": ppn, "family": fam,
                                "attributes": attrs})
        elif rtype == "family":
            fam, ftype, notes, page, fname = r
            doc.update(file=fname, page=page,
                       payload={"family": fam, "family_type": ftype,
                                "notes": notes})
        return doc


if __name__ == "__main__":
    import json

    from knowledge.processor.query_process.base import setup_logging

    setup_logging()
    node = StructuredLookupNode()
    tests = [
        {"intent": "model_list", "model_entities": ["MAX20029B"]},
        {"intent": "model_detail", "model_entities": ["TL432BIDBZR"]},
        {"intent": "rule_explain", "model_entities": ["MAX20029ATIA/V+"]},
        {"intent": "param_query", "model_entities": ["LM317"]},
    ]
    for t in tests:
        st = node(t)
        print(f"\n== {t['intent']} {t['model_entities']} → "
              f"{len(st['structured_docs'])} 条, files={st['entity_files']}")
        for d in st["structured_docs"][:3]:
            print("  ", d["type"],
                  json.dumps(d["payload"], ensure_ascii=False)[:160])

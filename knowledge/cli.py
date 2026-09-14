"""Lumy 知识库命令行入口（笔试交付物）

用法：
    python -m knowledge.cli ingest <pdf路径...>        # 导入（结构化+语义双链路）
    python -m knowledge.cli ask "问题" [--show-context] # 问答（带证据引用）
    python -m knowledge.cli export-models -o out.jsonl  # 导出结构化提取结果

示例：
    set KB_SCENARIO=lumy
    python -m knowledge.cli ingest referencePDF/max20029-max20029d.pdf
    python -m knowledge.cli ask "MAX20029B系列有哪些产品型号？" --show-context
"""

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

# CLI 默认 lumy 场景（除非显式指定 brain）
os.environ.setdefault("KB_SCENARIO", "lumy")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def cmd_ingest(args):
    from knowledge.processor.import_process.main_graph import graph
    from knowledge.processor.import_process.base import setup_logging

    setup_logging()
    ok = 0
    for pdf in args.pdfs:
        pdf = str(Path(pdf).resolve())
        state = {
            "import_file_path": pdf,
            "file_dir": str(Path(pdf).parent / "lumy_import" / Path(pdf).stem),
        }
        pg_counts, n_chunks = None, None
        try:
            for event in graph.stream(state):
                for node, st in event.items():
                    if node == "pg_import":
                        pg_counts = (st or {}).get("pg_counts")
                    if node == "lumy_split":
                        n_chunks = len((st or {}).get("chunks") or [])
            print(f"[OK] {Path(pdf).name}: pg={pg_counts} chunks={n_chunks}")
            ok += 1
        except Exception as e:
            print(f"[FAIL] {Path(pdf).name}: {e}")
    print(f"完成 {ok}/{len(args.pdfs)}")
    return 0 if ok == len(args.pdfs) else 1


def cmd_ask(args):
    from knowledge.processor.query_process.main_graph import query_app

    state = {
        "original_query": args.question,
        "session_id": f"lumy_cli_{uuid.uuid4().hex[:8]}",
        "task_id": uuid.uuid4().hex,
        "is_stream": False,
    }
    st = query_app.invoke(state)

    print("=" * 72)
    print(f"问题: {args.question}")
    print(f"意图: {st.get('intent')}  实体: {st.get('model_entities')} "
          f"{st.get('param_entities')}")
    print("=" * 72)

    # 结构化证据
    structured = st.get("structured_docs") or []
    print(f"\n【结构化检索】{len(structured)} 条:")
    for d in structured[:10]:
        page = f" 第{d['page']}页" if d.get("page") else ""
        print(f"  [型号库]({d['type']}) {d.get('file') or ''}{page} "
              f"match={d.get('match')}")

    # 向量证据
    docs = st.get("reranked_docs") or []
    print(f"\n【文档检索】{len(docs)} 条（按相关度）:")
    for i, d in enumerate(docs[:10]):
        page = d.get("page", "")
        cite = f"{d.get('file_title') or d.get('title') or ''}"
        if page != "":
            cite += f" 第{page}页"
        print(f"  [{i}] 相关度{d.get('score', 0):.2f} {cite}")
        if args.show_context:
            print("      " + (d.get("content") or "")[:400].replace("\n", "\n      "))

    # 答案
    print("\n" + "=" * 72)
    print("回答:")
    print("-" * 72)
    print(st.get("answer") or "(空)")
    return 0


def cmd_export_models(args):
    from knowledge.utils.pg_util import get_pg_conn

    conn = get_pg_conn()
    out_path = Path(args.output)
    with conn.cursor() as cur:
        cur.execute("SELECT id, file_name FROM pdf_sources ORDER BY file_name")
        pdfs = cur.fetchall()
        with open(out_path, "w", encoding="utf-8") as f:
            for pdf_id, fname in pdfs:
                row = {"pdf_file": fname}
                cur.execute("SELECT family_name, family_type, notes, evidence_page "
                            "FROM families WHERE pdf_id=%s ORDER BY family_name", (pdf_id,))
                row["families"] = [dict(zip(("family_name", "family_type", "notes",
                                             "evidence_page"), r)) for r in cur.fetchall()]
                cur.execute("SELECT ppn, family_name, attributes, evidence_page, evidence "
                            "FROM ppns WHERE pdf_id=%s ORDER BY ppn", (pdf_id,))
                row["ppns"] = [dict(zip(("ppn", "family", "attributes",
                                         "evidence_page", "evidence"), r))
                               for r in cur.fetchall()]
                cur.execute("SELECT opn, ppn, family_name, package, packing, evidence_page "
                            "FROM opns WHERE pdf_id=%s ORDER BY opn", (pdf_id,))
                row["opns"] = [dict(zip(("opn", "ppn", "family", "package",
                                         "packing", "evidence_page"), r))
                               for r in cur.fetchall()]
                cur.execute("SELECT family_name, pattern, positions, source_page "
                            "FROM naming_rules WHERE pdf_id=%s", (pdf_id,))
                row["naming_rules"] = [dict(zip(("family", "pattern", "positions",
                                                 "source_page"), r))
                                       for r in cur.fetchall()]
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"导出 {len(pdfs)} 份 → {out_path}")
    return 0


def main():
    parser = argparse.ArgumentParser(prog="knowledge.cli",
                                     description="Lumy 型号知识库 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ingest = sub.add_parser("ingest", help="导入 PDF（双链路）")
    p_ingest.add_argument("pdfs", nargs="+")

    p_ask = sub.add_parser("ask", help="知识库问答")
    p_ask.add_argument("question")
    p_ask.add_argument("--show-context", action="store_true",
                       help="展示检索到的原文内容")

    p_export = sub.add_parser("export-models", help="导出结构化提取结果 JSONL")
    p_export.add_argument("-o", "--output", default="eval/lumy_models.jsonl")

    args = parser.parse_args()
    if args.cmd == "ingest":
        sys.exit(cmd_ingest(args))
    if args.cmd == "ask":
        sys.exit(cmd_ask(args))
    if args.cmd == "export-models":
        sys.exit(cmd_export_models(args))


if __name__ == "__main__":
    main()

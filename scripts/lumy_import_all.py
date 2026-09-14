"""Lumy 批量导入脚本：referencePDF 下全部 PDF 走 lumy 双链路导入图

用法：
    KB_SCENARIO=lumy python scripts/lumy_import_all.py [pdf目录] [--only 名称过滤]
"""

import glob
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from knowledge.processor.import_process.main_graph import graph  # noqa: E402
from knowledge.processor.import_process.base import setup_logging  # noqa: E402


def main():
    setup_logging()
    root = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") \
        else "referencePDF"
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else ""

    pdfs = sorted(glob.glob(str(Path(root) / "*.pdf")))
    if only:
        pdfs = [p for p in pdfs if only in Path(p).stem]
    print(f"待导入 {len(pdfs)} 份: {[Path(p).name for p in pdfs]}", flush=True)

    results = []
    for pdf in pdfs:
        stem = Path(pdf).stem
        state = {"import_file_path": pdf,
                 "file_dir": str(Path(root) / "lumy_import" / stem)}
        t0 = time.time()
        pg_counts = None
        n_chunks = None
        try:
            for event in graph.stream(state):
                for node, st in event.items():
                    if node == "pg_import":
                        pg_counts = (st or {}).get("pg_counts")
                    if node == "lumy_split":
                        n_chunks = len((st or {}).get("chunks") or [])
            print(f"[OK] {stem}: {time.time()-t0:.0f}s pg={pg_counts} "
                  f"chunks={n_chunks}", flush=True)
            results.append((stem, True))
        except Exception as e:
            traceback.print_exc()
            print(f"[FAIL] {stem}: {e}", flush=True)
            results.append((stem, False))

    print("=" * 60)
    ok = sum(1 for _, s in results if s)
    print(f"完成 {ok}/{len(results)}")
    for stem, s in results:
        print(f"  {'✓' if s else '✗'} {stem}")


if __name__ == "__main__":
    main()

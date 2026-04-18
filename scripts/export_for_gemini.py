"""
絞り込み条件で ir_sections / ir_presentation_slides を Markdown にまとめ出力。
Gemini CLI の `@path` 参照で食わせる想定。

使い方:
  # 飲食業全体の business_risks だけ
  python scripts/export_for_gemini.py --section-code business_risks --out data/ctx_risks.md

  # 特定会社の全セクション
  python scripts/export_for_gemini.py --sec-code 3197 --out data/ctx_skylark.md

  # 決算説明資料側のスライドも (lang=auto で JA+EN 両方)
  python scripts/export_for_gemini.py --include-slides --sec-code 3197 --out data/ctx_skylark_full.md

その後:
  gemini -p "@data/ctx_skylark.md\n\n経営者による分析の構成を要約してください"
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import load_config  # noqa: E402


def _open(db: str):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    return c


def export(
    db: str,
    out: str,
    sec_code: Optional[str] = None,
    section_code: Optional[str] = None,
    include_slides: bool = False,
    latest_only: bool = True,
) -> int:
    c = _open(db)

    where = ["1=1"]
    params = []
    if sec_code:
        where.append("cm.sec_code = ?")
        params.append(sec_code)
    if section_code:
        where.append("s.section_code = ?")
        params.append(section_code)
    if latest_only:
        where.append("d.is_latest = 1")

    sections = c.execute(
        f"""SELECT cm.sec_code, cm.company_name, d.period_end,
                   s.section_code, s.section_name_ja, s.section_name_en,
                   s.content_text, s.content_text_en,
                   s.keywords_ja, s.keywords_en
            FROM ir_sections s
            JOIN ir_documents d ON s.doc_id = d.doc_id
            LEFT JOIN ir_companies cm ON d.edinet_code = cm.edinet_code
            WHERE {' AND '.join(where)}
            ORDER BY cm.sec_code, d.period_end DESC, s.section_order""",
        params,
    ).fetchall()

    n_sections = 0
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# IR Corpus Export\n\n")
        f.write(f"- filters: sec_code={sec_code or '*'} / section_code={section_code or '*'}\n\n")
        for r in sections:
            f.write(f"---\n\n")
            f.write(f"## {r['sec_code'] or '?'} {r['company_name'] or ''}"
                    f" / {r['section_code']} / {r['period_end'] or ''}\n\n")
            if r["section_name_ja"] or r["section_name_en"]:
                f.write(f"*{r['section_name_ja'] or ''} / {r['section_name_en'] or ''}*\n\n")
            if r["keywords_ja"] or r["keywords_en"]:
                f.write(f"`keywords: {r['keywords_ja'] or ''} | {r['keywords_en'] or ''}`\n\n")
            f.write(f"### JA\n\n{(r['content_text'] or '').strip()}\n\n")
            if r["content_text_en"]:
                f.write(f"### EN\n\n{r['content_text_en'].strip()}\n\n")
            n_sections += 1

        if include_slides:
            slide_where = ["1=1"]
            slide_params = []
            if sec_code:
                slide_where.append("p.sec_code = ?")
                slide_params.append(sec_code)
            slides = c.execute(
                f"""SELECT p.sec_code, p.company_name, p.fiscal_period, p.title,
                           sl.slide_no, sl.slide_url, sl.title AS stitle, sl.title_en,
                           sl.content_text, sl.content_text_en,
                           sl.keywords_ja, sl.keywords_en
                    FROM ir_presentation_slides sl
                    JOIN ir_presentations p ON sl.presentation_id = p.presentation_id
                    WHERE {' AND '.join(slide_where)}
                    ORDER BY p.sec_code, p.fiscal_period, sl.slide_no""",
                slide_params,
            ).fetchall()
            for r in slides:
                f.write(f"---\n\n## [slide] {r['sec_code']} {r['title']}"
                        f" / p{r['slide_no']} / {r['fiscal_period'] or ''}\n\n")
                if r["slide_url"]:
                    f.write(f"url: {r['slide_url']}\n\n")
                body = (r["content_text"] or "").strip()
                if body:
                    f.write(f"### JA\n\n{body}\n\n")
                if r["content_text_en"]:
                    f.write(f"### EN\n\n{r['content_text_en'].strip()}\n\n")
    c.close()
    return n_sections


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/gemini_context.md")
    ap.add_argument("--sec-code")
    ap.add_argument("--section-code")
    ap.add_argument("--include-slides", action="store_true")
    ap.add_argument("--all-versions", action="store_true",
                    help="訂正等で差し替えられた古い書類も含める")
    args = ap.parse_args()
    db = load_config()["db_path"]
    n = export(
        db, out=args.out,
        sec_code=args.sec_code,
        section_code=args.section_code,
        include_slides=args.include_slides,
        latest_only=not args.all_versions,
    )
    size = os.path.getsize(args.out)
    print(f"[OK] {args.out}  sections={n}  bytes={size}")
    print(f"次のコマンドで食わせられる:")
    print(f"  gemini -p \"@{args.out}\\n\\n<質問>\"")


if __name__ == "__main__":
    main()

"""
RAG 回答生成 (典拠付き)。

SoyLM パターンを採用:
  検索結果 → 【ソースデータ】[1]...[N] に整形 → LLM が [1],[2] 付きで回答生成。
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from src.ir.queries import fetch_sections_by_ids

CITATION_SYSTEM_PROMPT = (
    "あなたは日本の有価証券報告書を分析する調査員です。\n\n"
    "ルール:\n"
    "- 回答にはソースを [1], [2] のように引用してください。"
    "【ソースデータ】に表示される番号に対応します。\n"
    "- 複数ソースをまとめる場合は [1, 3] と併記してください。\n"
    "- ソースに含まれない情報は「ソースには記載がありません」と明示してから補足してください。\n"
    "- 企業名・期間を明示し、どの企業のどの期の記載かを常に明確にしてください。\n"
    "- 日本語で、要点を箇条書き→詳細の順で回答してください。"
)


def format_sources_for_context(
    rows: List[Dict[str, Any]],
    db_path: str,
    max_total_chars: int = 60000,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    検索結果行を LLM コンテキスト文字列 + 出典メタデータに変換。

    Returns:
        (context_str, source_meta)
        context_str: 【ソースデータ】に入れる文字列
        source_meta: UI の出典セクション用メタデータ (index, company_name, ...)
    """
    if not rows:
        return "", []

    # content_text が欠けている行を補完
    missing_ids = [r["section_id"] for r in rows if not r.get("content_text")]
    if missing_ids:
        full = fetch_sections_by_ids(db_path, missing_ids)
        for r in rows:
            if not r.get("content_text") and r["section_id"] in full:
                r.update(full[r["section_id"]])

    per_budget = max_total_chars // len(rows)
    blocks: List[str] = []
    source_meta: List[Dict[str, Any]] = []

    for i, r in enumerate(rows, 1):
        company = r.get("company_name") or "?"
        sec_code = r.get("sec_code") or "?"
        section = r.get("section_code") or "other"
        period = r.get("period_end") or "?"

        header = f"[{i}] {company} ({sec_code}) / {section} / {period}"
        content = r.get("content_text") or ""
        if len(content) > per_budget:
            content = content[:per_budget] + "\n…（以下省略）"

        blocks.append(f"{header}\n{content}")
        source_meta.append({
            "index": i,
            "company_name": company,
            "sec_code": sec_code,
            "section_code": section,
            "section_name_ja": r.get("section_name_ja") or "",
            "period_end": period,
            "content_text": r.get("content_text") or "",
        })

    return "\n\n---\n\n".join(blocks), source_meta


def build_answer_prompt(query: str, context_str: str) -> Tuple[str, str]:
    """
    SoyLM パターン: 【ソースデータ】+ 【質問】。

    Returns:
        (system_prompt, user_prompt)
    """
    user = f"【ソースデータ】\n{context_str}\n\n【質問】\n{query}"
    return CITATION_SYSTEM_PROMPT, user

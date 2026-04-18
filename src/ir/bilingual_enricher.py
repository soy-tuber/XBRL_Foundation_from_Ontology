"""
LLM で各セクション/スライドに:
- 英訳 (content_text_en)
- 日本語キーワード (keywords_ja)
- 英語キーワード (keywords_en)
を付与する。FTS5 検索で英語側のヒットも取りたいので、投入後に実行する後処理。

方針:
- Gemini / ローカル LLM どちらでも動くよう llm_client.LlmClient に寄せる
- 出力は JSON 固定にする (Markdown にすると後処理が煩雑)
- 1件ずつ処理 (バッチは LLM 側がコケた時の切り分けが面倒なので直列で安全運用)
- enriched_at が埋まっている行はデフォルトでスキップ
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.ir.llm_client import LlmClient

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are an IR analyst helping build a bilingual search index for Japanese securities filings "
    "and earnings presentations. Output MUST be valid minified JSON with keys: "
    "content_text_en (faithful English translation, preserve numbers and tables), "
    "keywords_ja (8-15 comma-separated Japanese keywords incl. domain terms), "
    "keywords_en (8-15 comma-separated English keywords, use IFRS/SEC style financial terms). "
    "No explanation, no code fences."
)

_RE_JSON = re.compile(r"\{.*\}", re.S)


def _call_llm(client: LlmClient, text: str, max_chars: int = 6000) -> Dict[str, str]:
    payload = text if len(text) <= max_chars else text[:max_chars] + "\n...[truncated]"
    raw = client.generate(_SYSTEM, payload, temperature=0.0)
    m = _RE_JSON.search(raw)
    if not m:
        raise ValueError(f"non-JSON LLM response: {raw[:200]}")
    data = json.loads(m.group(0))
    return {
        "content_text_en": data.get("content_text_en", "").strip(),
        "keywords_ja": data.get("keywords_ja", "").strip(),
        "keywords_en": data.get("keywords_en", "").strip(),
    }


# ---------- 対 ir_sections ----------

def enrich_sections(
    db_path: str,
    limit: Optional[int] = None,
    force: bool = False,
    client: Optional[LlmClient] = None,
) -> Tuple[int, int]:
    """
    返り値: (処理成功件数, 失敗件数)
    """
    import sqlite3
    client = client or LlmClient()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    where = "" if force else "WHERE enriched_at IS NULL OR enriched_at = ''"
    q = f"SELECT section_id, content_text FROM ir_sections {where} ORDER BY section_id"
    if limit:
        q += f" LIMIT {int(limit)}"
    rows = conn.execute(q).fetchall()
    ok = ng = 0
    for r in rows:
        sid = r["section_id"]
        text = r["content_text"] or ""
        if not text.strip():
            continue
        try:
            result = _call_llm(client, text)
            conn.execute(
                """UPDATE ir_sections
                   SET content_text_en = ?, keywords_ja = ?, keywords_en = ?, enriched_at = ?
                   WHERE section_id = ?""",
                (result["content_text_en"], result["keywords_ja"], result["keywords_en"],
                 datetime.utcnow().isoformat(timespec="seconds"), sid),
            )
            conn.commit()
            ok += 1
            logger.info(f"enriched section {sid}")
        except Exception as e:
            ng += 1
            logger.exception(f"failed section {sid}: {e}")
    conn.close()
    return ok, ng


# ---------- 対 ir_presentation_slides ----------

def enrich_slides(
    db_path: str,
    limit: Optional[int] = None,
    force: bool = False,
    client: Optional[LlmClient] = None,
) -> Tuple[int, int]:
    import sqlite3
    client = client or LlmClient()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    where = "" if force else "WHERE enriched_at IS NULL OR enriched_at = ''"
    q = f"SELECT slide_id, title, content_text FROM ir_presentation_slides {where} ORDER BY slide_id"
    if limit:
        q += f" LIMIT {int(limit)}"
    rows = conn.execute(q).fetchall()
    ok = ng = 0
    for r in rows:
        sid = r["slide_id"]
        text = (r["title"] or "") + "\n" + (r["content_text"] or "")
        if not text.strip():
            continue
        try:
            result = _call_llm(client, text)
            # タイトル英訳は先頭のキーワード or 翻訳先頭行を流用
            title_en = ""
            if result["content_text_en"]:
                title_en = result["content_text_en"].split("\n", 1)[0][:255]
            conn.execute(
                """UPDATE ir_presentation_slides
                   SET content_text_en = ?, keywords_ja = ?, keywords_en = ?,
                       title_en = COALESCE(NULLIF(title_en, ''), ?),
                       enriched_at = ?
                   WHERE slide_id = ?""",
                (result["content_text_en"], result["keywords_ja"], result["keywords_en"],
                 title_en, datetime.utcnow().isoformat(timespec="seconds"), sid),
            )
            conn.commit()
            ok += 1
            logger.info(f"enriched slide {sid}")
        except Exception as e:
            ng += 1
            logger.exception(f"failed slide {sid}: {e}")
    conn.close()
    return ok, ng

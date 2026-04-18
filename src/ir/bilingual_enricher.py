"""
LLM で英訳とキーワードを「補完」する後処理。ただし公式英文ソース (英文有報・
英文アニュアルレポート) があればそちらを優先し、これはフォールバックのみ。

優先順位:
  1. native_xbrl_label  (公式タクソノミのラベル: section_name_en のみ自動付与済)
  2. official_english   (英文有報 / 英文アニュアル PDF から取り込んだ本文)
  3. llm_translated     ← このモジュール (1, 2 が無いときのみ)

実行挙動:
- ir_sections.content_source = 'official_english' の行はスキップ
- content_text_en が既に埋まっている行もスキップ (--force で上書き)
- 上記以外は LLM で訳+キーワード生成 → content_source を 'llm_translated' に更新
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
    # 公式英文が入っている行はスキップ。--force は LLM 翻訳を上書きするだけで
    # official_english は守る
    if force:
        where = "WHERE COALESCE(content_source, '') != 'official_english'"
    else:
        where = (
            "WHERE (enriched_at IS NULL OR enriched_at = '')"
            "  AND (content_text_en IS NULL OR content_text_en = '')"
            "  AND COALESCE(content_source, '') != 'official_english'"
        )
    q = (
        "SELECT section_id, content_text FROM ir_sections "
        f"{where} ORDER BY section_id"
    )
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
                   SET content_text_en = ?, keywords_ja = ?, keywords_en = ?,
                       content_source = 'llm_translated', enriched_at = ?
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

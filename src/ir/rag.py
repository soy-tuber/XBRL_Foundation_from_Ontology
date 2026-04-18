"""
SQLite で完結する RAG レイヤ。

- 埋め込みは ir_section_embeddings (BLOB=numpy float32 packed) に格納
- クエリ時はセクションごとのベクトルを一括ロード → numpy で cosine
- 件数規模 (1年×60社×15セクション ≒ 900) なら一括ロードで十分高速
- FTS5 + semantic のハイブリッドは Reciprocal Rank Fusion (RRF) で結合

外部LLMコールを避けたい場合は `embed_fn` に dummy 関数を渡せば動作する (テスト用)。
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

import numpy as np

from src.ir.llm_client import LlmClient

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini/text-embedding-004"
DEFAULT_DIM = 768  # text-embedding-004 既定


@contextmanager
def _conn(db_path: str) -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    try:
        yield c
    finally:
        c.close()


def _pack(vec: List[float]) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def _unpack(blob: bytes, dim: int) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32, count=dim)


def _compose_text(row: sqlite3.Row) -> str:
    """埋め込みに投入するテキスト。JA/EN/キーワードを全部混ぜて多言語検索に強くする。"""
    parts = [
        row["section_name_ja"] or "",
        row["section_name_en"] or "",
        row["keywords_ja"] or "",
        row["keywords_en"] or "",
        row["content_text"] or "",
        row["content_text_en"] or "",
    ]
    return "\n".join(p for p in parts if p).strip()


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


# ---------- 構築 ----------

def build_embeddings(
    db_path: str,
    model: str = DEFAULT_MODEL,
    limit: Optional[int] = None,
    batch_size: int = 16,
    embed_fn: Optional[Callable[[List[str]], List[List[float]]]] = None,
    force: bool = False,
) -> Tuple[int, int]:
    """
    ir_sections 全行の埋め込みを作って ir_section_embeddings に upsert。
    既に同一 source_hash が保存されている行はスキップ (--force で強制再計算)。
    """
    if embed_fn is None:
        client = LlmClient()
        # model 文字列からプロバイダ部分を剥がして渡す (gemini/text-embedding-004 -> text-embedding-004)
        raw_model = model.split("/", 1)[-1] if "/" in model else model
        embed_fn = lambda texts: client.embed(texts, model=raw_model)

    ok = ng = 0
    with _conn(db_path) as c:
        rows = c.execute(
            """SELECT s.section_id, s.section_name_ja, s.section_name_en,
                      s.keywords_ja, s.keywords_en,
                      s.content_text, s.content_text_en
               FROM ir_sections s
               ORDER BY s.section_id""" + (f" LIMIT {int(limit)}" if limit else "")
        ).fetchall()

        existing = {
            (r[0], r[1]): r[2]
            for r in c.execute(
                "SELECT section_id, model, source_hash FROM ir_section_embeddings WHERE model = ?",
                (model,),
            ).fetchall()
        }

        # バッチ化
        pending: List[Tuple[int, str, str]] = []  # (section_id, text, hash)
        for r in rows:
            text = _compose_text(r)
            if not text:
                continue
            h = _hash(text)
            prev = existing.get((r["section_id"], model))
            if prev == h and not force:
                continue
            pending.append((r["section_id"], text, h))

        logger.info(f"build_embeddings: {len(pending)} pending / {len(rows)} total, model={model}")

        for i in range(0, len(pending), batch_size):
            chunk = pending[i : i + batch_size]
            try:
                vectors = embed_fn([t for _, t, _ in chunk])
            except Exception as e:
                ng += len(chunk)
                logger.exception(f"embed batch failed ({i}..{i+len(chunk)}): {e}")
                continue

            for (sid, _text, h), vec in zip(chunk, vectors):
                c.execute(
                    """INSERT INTO ir_section_embeddings
                        (section_id, model, dim, vector, source_hash, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(section_id, model) DO UPDATE SET
                        dim = excluded.dim,
                        vector = excluded.vector,
                        source_hash = excluded.source_hash,
                        created_at = excluded.created_at""",
                    (sid, model, len(vec), _pack(vec), h,
                     datetime.utcnow().isoformat(timespec="seconds")),
                )
            c.commit()
            ok += len(chunk)

    return ok, ng


# ---------- 検索 ----------

def _load_matrix(conn: sqlite3.Connection, model: str):
    """そのモデルの全埋め込みをメモリに展開する。小規模 (≦10万件) 前提。"""
    rows = conn.execute(
        "SELECT section_id, dim, vector FROM ir_section_embeddings WHERE model = ?",
        (model,),
    ).fetchall()
    if not rows:
        return None, None
    dim = rows[0]["dim"]
    ids = np.empty(len(rows), dtype=np.int64)
    mat = np.empty((len(rows), dim), dtype=np.float32)
    for i, r in enumerate(rows):
        ids[i] = r["section_id"]
        mat[i] = _unpack(r["vector"], r["dim"])
    # 正規化しておけば内積でコサイン類似度
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    mat /= norms
    return ids, mat


def semantic_search(
    db_path: str,
    query: str,
    k: int = 20,
    section_code: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    embed_fn: Optional[Callable[[List[str]], List[List[float]]]] = None,
) -> List[Dict[str, Any]]:
    if embed_fn is None:
        client = LlmClient()
        raw_model = model.split("/", 1)[-1] if "/" in model else model
        embed_fn = lambda texts: client.embed(texts, model=raw_model)
    qvec = np.asarray(embed_fn([query])[0], dtype=np.float32)
    n = np.linalg.norm(qvec)
    if n > 0:
        qvec /= n

    with _conn(db_path) as c:
        ids, mat = _load_matrix(c, model)
        if ids is None:
            return []
        sims = mat @ qvec  # (N,)
        # section_code 絞り込みは事後フィルタで十分 (小規模前提)
        order = np.argsort(-sims)
        top_ids: List[int] = []
        for idx in order:
            top_ids.append(int(ids[idx]))
            if len(top_ids) >= k * 4:  # 後段フィルタで削れる余地
                break

        if not top_ids:
            return []

        placeholders = ",".join("?" * len(top_ids))
        where_extra = "AND s.section_code = ?" if section_code else ""
        params: List[Any] = list(top_ids)
        if section_code:
            params.append(section_code)
        rows = c.execute(
            f"""SELECT s.section_id, s.section_code, s.section_name_ja, s.section_name_en,
                       s.content_text, s.content_text_en, s.keywords_ja, s.keywords_en,
                       s.content_source,
                       d.doc_id, d.period_end, cm.sec_code, cm.company_name
                FROM ir_sections s
                JOIN ir_documents d ON s.doc_id = d.doc_id
                LEFT JOIN ir_companies cm ON d.edinet_code = cm.edinet_code
                WHERE s.section_id IN ({placeholders}) {where_extra}
                  AND d.is_latest = 1""",
            params,
        ).fetchall()

        by_id = {r["section_id"]: dict(r) for r in rows}
        scored: List[Tuple[float, Dict[str, Any]]] = []
        sim_map = {int(ids[i]): float(sims[i]) for i in range(len(ids))}
        for sid in top_ids:
            if sid in by_id:
                row = dict(by_id[sid])
                row["score"] = sim_map[sid]
                scored.append(row)
                if len(scored) >= k:
                    break
        return scored


def hybrid_search(
    db_path: str,
    query: str,
    k: int = 20,
    section_code: Optional[str] = None,
    lang: str = "auto",
    model: str = DEFAULT_MODEL,
    embed_fn: Optional[Callable[[List[str]], List[List[float]]]] = None,
    rrf_k: int = 60,
) -> List[Dict[str, Any]]:
    """
    FTS5 と semantic の結果を Reciprocal Rank Fusion (RRF) で結合。
    score = sum(1 / (rrf_k + rank_in_each_list))
    """
    from src.ir import queries as Q

    fts = Q.fts_search(db_path, query, section_code=section_code, limit=k * 3, lang=lang)
    sem = semantic_search(
        db_path, query, k=k * 3,
        section_code=section_code, model=model, embed_fn=embed_fn,
    )

    bucket: Dict[int, Dict[str, Any]] = {}
    for rank, r in enumerate(fts):
        sid = r["section_id"]
        bucket.setdefault(sid, {"row": r, "fts_rank": None, "sem_rank": None})
        bucket[sid]["fts_rank"] = rank
        bucket[sid]["row"] = {**bucket[sid]["row"], **r}
    for rank, r in enumerate(sem):
        sid = r["section_id"]
        bucket.setdefault(sid, {"row": r, "fts_rank": None, "sem_rank": None})
        bucket[sid]["sem_rank"] = rank
        bucket[sid]["row"] = {**bucket[sid]["row"], **r}

    scored: List[Tuple[float, Dict[str, Any]]] = []
    for sid, b in bucket.items():
        s = 0.0
        if b["fts_rank"] is not None:
            s += 1.0 / (rrf_k + b["fts_rank"] + 1)
        if b["sem_rank"] is not None:
            s += 1.0 / (rrf_k + b["sem_rank"] + 1)
        row = dict(b["row"])
        row["score"] = s
        row["fts_rank"] = b["fts_rank"]
        row["sem_rank"] = b["sem_rank"]
        scored.append((s, row))

    scored.sort(key=lambda x: -x[0])
    return [row for _, row in scored[:k]]

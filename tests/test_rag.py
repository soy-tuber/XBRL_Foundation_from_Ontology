"""
RAG レイヤのテスト。外部 LLM コールを避けるため、埋め込み関数をダミーで差し込む。
ダミー埋め込みは「テキストに含まれるトークンごとに決まった次元を立てる」方式で、
同じトークンを含むセクションが類似度で上位に来ることを検証できる。
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from typing import List

import numpy as np

from src.db.ir_schema import init_ir_schema
from src.ir import rag as RAG


VOCAB = [
    "supply", "chain", "risk", "same-store", "sales", "governance",
    "サプライチェーン", "リスク", "既存店", "ガバナンス", "価格高騰",
]
DIM = len(VOCAB)


def dummy_embed(texts: List[str]) -> List[List[float]]:
    """
    語彙ごとに 1 次元を立てる。そのテキストに語彙が含まれていれば 1.0、無ければ 0.0。
    """
    out = []
    for t in texts:
        low = t.lower()
        v = [1.0 if w.lower() in low else 0.0 for w in VOCAB]
        if sum(v) == 0:
            # 0 ベクトルだと正規化で NaN になるので hash fallback で1箇所立てる
            idx = int(hashlib.md5(t.encode()).hexdigest(), 16) % DIM
            v[idx] = 1.0
        out.append(v)
    return out


def _bootstrap_db(db: str):
    init_ir_schema(db)
    conn = sqlite3.connect(db)
    # 会社 + 書類 + 3セクション (テーマの異なる英日文章)
    conn.execute("INSERT INTO ir_companies (edinet_code, sec_code, company_name) VALUES ('E1','1111','Aco')")
    conn.execute("INSERT INTO ir_documents (doc_id, edinet_code, sec_code, is_latest) VALUES ('DOC1','E1','1111',1)")
    rows = [
        ("business_risks",
         "サプライチェーン依存のリスクと価格高騰が収益を圧迫する可能性がある",
         "Risks from supply chain dependency and price hikes",
         "サプライチェーン, リスク, 価格高騰", "supply chain, risk"),
        ("mdna",
         "既存店売上は前年同期比 +5% で推移した",
         "Same-store sales grew +5% YoY",
         "既存店, 売上", "same-store, sales"),
        ("corporate_governance",
         "社外取締役を過半数配置しガバナンス体制を強化した",
         "Independent directors form a majority, strengthening governance",
         "ガバナンス, 社外取締役", "governance, independent directors"),
    ]
    for code, ja, en, kja, ken in rows:
        conn.execute(
            """INSERT INTO ir_sections (doc_id, section_code, section_name_ja, section_name_en,
                                        content_text, content_text_en, keywords_ja, keywords_en, char_count)
               VALUES ('DOC1', ?, ?, '', ?, ?, ?, ?, ?)""",
            (code, code, ja, en, kja, ken, len(ja)),
        )
    conn.commit()
    conn.close()


def test_build_and_semantic_search_with_dummy_embeddings():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "rag.db")
        _bootstrap_db(db)

        ok, ng = RAG.build_embeddings(db, model="dummy/vocab", embed_fn=dummy_embed)
        assert ok == 3 and ng == 0

        # 同じ本文に対して source_hash が一致するのでスキップ
        ok2, _ = RAG.build_embeddings(db, model="dummy/vocab", embed_fn=dummy_embed)
        assert ok2 == 0, "second run should skip on matching source_hash"

        # サプライチェーン関連のクエリで business_risks が 1 位
        rows = RAG.semantic_search(
            db, "supply chain risk 価格高騰", k=3,
            model="dummy/vocab", embed_fn=dummy_embed,
        )
        assert rows, "expected hits"
        assert rows[0]["section_code"] == "business_risks"


def test_hybrid_search_combines_fts_and_semantic():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "rag2.db")
        _bootstrap_db(db)
        RAG.build_embeddings(db, model="dummy/vocab", embed_fn=dummy_embed)

        rows = RAG.hybrid_search(
            db, "same-store sales", k=3,
            model="dummy/vocab", embed_fn=dummy_embed, lang="auto",
        )
        assert rows
        # MDNA (same-store sales を含むセクション) が上位に来る
        assert rows[0]["section_code"] == "mdna"
        # fts_rank / sem_rank がメタとして載っている
        assert "fts_rank" in rows[0] and "sem_rank" in rows[0]


if __name__ == "__main__":
    test_build_and_semantic_search_with_dummy_embeddings()
    test_hybrid_search_combines_fts_and_semantic()
    print("OK")

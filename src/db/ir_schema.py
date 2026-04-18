"""
IR/法務支援 DB 用の拡張スキーマ。
既存の financial_raw (EAV) とは独立して、要件書5章のテーブルを追加する。
同じ SQLite ファイル内に同居させるため、既存資産を壊さない。
"""

from sqlalchemy import (
    Column, String, Float, Integer, Text, Boolean, Date, Index, ForeignKey, LargeBinary,
    create_engine
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

IRBase = declarative_base()


class Company(IRBase):
    __tablename__ = "ir_companies"

    edinet_code = Column(String(10), primary_key=True)
    sec_code = Column(String(10), index=True)
    company_name = Column(String(255), nullable=False)
    industry_code = Column(String(20), comment="EDINET業種コード")
    industry_name = Column(String(64))
    fiscal_year_end = Column(String(10), comment="MM-DD")
    has_english_filing = Column(
        Boolean, default=False, index=True,
        comment="EDINETに英文有報を一度でも提出したことがあるか (参考銘柄の指標)",
    )


class Document(IRBase):
    __tablename__ = "ir_documents"

    doc_id = Column(String(20), primary_key=True)
    edinet_code = Column(String(10), ForeignKey("ir_companies.edinet_code"), index=True)
    sec_code = Column(String(10), index=True)
    doc_type_code = Column(String(10), index=True, comment="120/130/160/350 等")
    period_start = Column(Date)
    period_end = Column(Date, index=True)
    submit_date = Column(Date, index=True)
    is_amended = Column(Boolean, default=False, comment="訂正報告書フラグ")
    superseded_by = Column(String(20), comment="本書を差し替える訂正報告書のdoc_id")
    is_latest = Column(Boolean, default=True, index=True)
    taxonomy_version = Column(String(10), comment="2014/2019/2023 等")
    source_zip_path = Column(Text)
    has_english_doc = Column(
        Boolean, default=False, index=True,
        comment="EDINET API englishDocFlag=1 (英文ZIP type=4 で取得可能)",
    )


class Section(IRBase):
    __tablename__ = "ir_sections"

    section_id = Column(Integer, primary_key=True, autoincrement=True)
    doc_id = Column(String(20), ForeignKey("ir_documents.doc_id"), index=True, nullable=False)
    section_code = Column(String(64), index=True, comment="正規化済み (business_risks 等)")
    section_name_ja = Column(String(255))
    section_name_en = Column(String(255))
    section_order = Column(Integer)
    raw_tag_name = Column(String(255), comment="元XBRL要素名 (診断用)")
    content_text = Column(Text, comment="原文 (日本語)")
    content_text_en = Column(Text, comment="英語本文 (公式英文有報 / 英文アニュアル / LLM翻訳 の順で埋める)")
    content_source = Column(
        String(32),
        comment="native_xbrl_label (ラベルのみ) / official_english (英文有報/アニュアル) / llm_translated (LLMフォールバック)",
    )
    keywords_ja = Column(Text, comment="日本語キーワード (カンマ区切り)")
    keywords_en = Column(Text, comment="英語キーワード (カンマ区切り)")
    char_count = Column(Integer, index=True)
    enriched_at = Column(String(32), comment="バイリンガル付与日時 (ISO)")

    __table_args__ = (
        Index("idx_ir_sections_code_doc", "section_code", "doc_id"),
    )


class FinancialFigure(IRBase):
    """
    既存の financial_raw を IR 用に正規化投影したビュー相当のテーブル。
    要件書5章の financial_figures に対応。
    数値のみ、連結/単体と当期/前期を context_ref に短縮コードで保持。
    """
    __tablename__ = "ir_financial_figures"

    fig_id = Column(Integer, primary_key=True, autoincrement=True)
    doc_id = Column(String(20), ForeignKey("ir_documents.doc_id"), index=True, nullable=False)
    element_name = Column(String(255), index=True)
    context_ref = Column(String(128), comment="CurrentYear/Prior1Year x Consolidated/NonConsolidated")
    is_current = Column(Boolean, default=True)
    is_consolidated = Column(Boolean, default=True)
    value = Column(String(64))
    unit = Column(String(32))
    decimals = Column(String(16))


class SectionEmbedding(IRBase):
    """
    RAG 用: ir_sections の本文を LLM で埋め込みベクトル化したもの。
    SQLite 内で完結する。ベクトルは numpy float32 を LargeBinary に pack。
    1 セクションに対し複数モデル分の埋め込みを保持できるよう (section_id, model) 複合PK。
    """
    __tablename__ = "ir_section_embeddings"

    section_id = Column(Integer, ForeignKey("ir_sections.section_id"), primary_key=True)
    model = Column(String(64), primary_key=True, comment="例: gemini/text-embedding-004")
    dim = Column(Integer, nullable=False)
    vector = Column(LargeBinary, nullable=False, comment="numpy float32 を .tobytes() で直列化")
    # 埋め込みに使った本文のハッシュ (本文が変わった時の再計算判定用)
    source_hash = Column(String(64), index=True)
    created_at = Column(String(32))


def init_ir_schema(db_path: str):
    """既存DBに IR 拡張テーブルを追加する。何度呼んでも安全 (create_all は冪等)。"""
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    IRBase.metadata.create_all(engine)
    _ensure_fts5(engine)
    return engine


def _ensure_fts5(engine):
    """
    ir_sections_fts: content_text の全文検索用 FTS5 仮想テーブル。
    トリガで ir_sections と同期する。
    """
    with engine.begin() as conn:
        from sqlalchemy import text
        conn.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS ir_sections_fts
            USING fts5(
                content_text,
                content_text_en,
                keywords_ja,
                keywords_en,
                section_code UNINDEXED,
                doc_id UNINDEXED,
                content='ir_sections',
                content_rowid='section_id',
                tokenize="trigram"
            );
        """))
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS ir_sections_ai AFTER INSERT ON ir_sections BEGIN
                INSERT INTO ir_sections_fts(
                    rowid, content_text, content_text_en, keywords_ja, keywords_en,
                    section_code, doc_id
                ) VALUES (
                    new.section_id, new.content_text, new.content_text_en,
                    new.keywords_ja, new.keywords_en, new.section_code, new.doc_id
                );
            END;
        """))
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS ir_sections_ad AFTER DELETE ON ir_sections BEGIN
                INSERT INTO ir_sections_fts(
                    ir_sections_fts, rowid, content_text, content_text_en,
                    keywords_ja, keywords_en, section_code, doc_id
                ) VALUES (
                    'delete', old.section_id, old.content_text, old.content_text_en,
                    old.keywords_ja, old.keywords_en, old.section_code, old.doc_id
                );
            END;
        """))
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS ir_sections_au AFTER UPDATE ON ir_sections BEGIN
                INSERT INTO ir_sections_fts(
                    ir_sections_fts, rowid, content_text, content_text_en,
                    keywords_ja, keywords_en, section_code, doc_id
                ) VALUES (
                    'delete', old.section_id, old.content_text, old.content_text_en,
                    old.keywords_ja, old.keywords_en, old.section_code, old.doc_id
                );
                INSERT INTO ir_sections_fts(
                    rowid, content_text, content_text_en, keywords_ja, keywords_en,
                    section_code, doc_id
                ) VALUES (
                    new.section_id, new.content_text, new.content_text_en,
                    new.keywords_ja, new.keywords_en, new.section_code, new.doc_id
                );
            END;
        """))


def get_ir_session(db_path: str):
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Session = sessionmaker(bind=engine)
    return Session()

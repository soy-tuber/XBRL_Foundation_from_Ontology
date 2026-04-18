"""
Phase 2: 決算説明資料の検索用スキーマ。
IR スキーマと同じ SQLite に同居させる。
"""

from __future__ import annotations

from sqlalchemy import (
    Column, String, Integer, Text, Date, ForeignKey, create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker

P2Base = declarative_base()


class Presentation(P2Base):
    __tablename__ = "ir_presentations"

    presentation_id = Column(Integer, primary_key=True, autoincrement=True)
    sec_code = Column(String(10), index=True)
    company_name = Column(String(255))
    fiscal_period = Column(String(16), comment="FY2024Q1 等")
    period_end = Column(Date, index=True)
    source_type = Column(String(16), comment="gdrive/local")
    source_uri = Column(Text, comment="Drive ID または ローカルパス")
    source_url = Column(Text, comment="Drive URL (https://drive.google.com/...) または ローカル絶対パス")
    file_type = Column(String(10), comment="pdf/pptx")
    title = Column(String(255))


class PresentationSlide(P2Base):
    __tablename__ = "ir_presentation_slides"

    slide_id = Column(Integer, primary_key=True, autoincrement=True)
    presentation_id = Column(Integer, ForeignKey("ir_presentations.presentation_id"), index=True)
    slide_no = Column(Integer)
    slide_url = Column(Text, comment="スライド個別 URL (Drive: #slide=id.X, PDF: ?page=N)")
    title = Column(String(255))
    title_en = Column(String(255))
    content_text = Column(Text, comment="原文 (日本語想定)")
    content_text_en = Column(Text, comment="LLM 翻訳済み英語")
    keywords_ja = Column(Text, comment="日本語キーワード (カンマ区切り)")
    keywords_en = Column(Text, comment="英語キーワード (カンマ区切り)")
    has_table = Column(Integer, default=0, comment="1: 表含有")
    has_chart = Column(Integer, default=0, comment="1: グラフ含有")
    char_count = Column(Integer)
    enriched_at = Column(String(32))


def init_phase2_schema(db_path: str):
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    P2Base.metadata.create_all(engine)
    _ensure_fts5(engine)
    return engine


def _ensure_fts5(engine):
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS ir_slides_fts
            USING fts5(
                content_text,
                content_text_en,
                keywords_ja,
                keywords_en,
                title,
                title_en,
                presentation_id UNINDEXED,
                content='ir_presentation_slides',
                content_rowid='slide_id',
                tokenize="trigram"
            );
        """))
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS ir_slides_ai AFTER INSERT ON ir_presentation_slides BEGIN
                INSERT INTO ir_slides_fts(
                    rowid, content_text, content_text_en, keywords_ja, keywords_en,
                    title, title_en, presentation_id
                ) VALUES (
                    new.slide_id, new.content_text, new.content_text_en,
                    new.keywords_ja, new.keywords_en, new.title, new.title_en,
                    new.presentation_id
                );
            END;
        """))
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS ir_slides_ad AFTER DELETE ON ir_presentation_slides BEGIN
                INSERT INTO ir_slides_fts(
                    ir_slides_fts, rowid, content_text, content_text_en,
                    keywords_ja, keywords_en, title, title_en, presentation_id
                ) VALUES (
                    'delete', old.slide_id, old.content_text, old.content_text_en,
                    old.keywords_ja, old.keywords_en, old.title, old.title_en,
                    old.presentation_id
                );
            END;
        """))
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS ir_slides_au AFTER UPDATE ON ir_presentation_slides BEGIN
                INSERT INTO ir_slides_fts(
                    ir_slides_fts, rowid, content_text, content_text_en,
                    keywords_ja, keywords_en, title, title_en, presentation_id
                ) VALUES (
                    'delete', old.slide_id, old.content_text, old.content_text_en,
                    old.keywords_ja, old.keywords_en, old.title, old.title_en,
                    old.presentation_id
                );
                INSERT INTO ir_slides_fts(
                    rowid, content_text, content_text_en, keywords_ja, keywords_en,
                    title, title_en, presentation_id
                ) VALUES (
                    new.slide_id, new.content_text, new.content_text_en,
                    new.keywords_ja, new.keywords_en, new.title, new.title_en,
                    new.presentation_id
                );
            END;
        """))


def get_phase2_session(db_path: str):
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    return sessionmaker(bind=engine)()

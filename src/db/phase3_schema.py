"""
Phase 3: 生成系アーティファクト管理のスキーマ。
Sheets + GAS コードの生成履歴と、元データへの参照を保持。
"""

from __future__ import annotations

from sqlalchemy import (
    Column, String, Integer, Text, Date, DateTime, ForeignKey, create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

P3Base = declarative_base()


class GeneratedArtifact(P3Base):
    __tablename__ = "ir_generated_artifacts"

    artifact_id = Column(Integer, primary_key=True, autoincrement=True)
    artifact_type = Column(String(32), comment="sheet/gas_script/chart_spec")
    source_presentation_id = Column(Integer, comment="ir_presentations.presentation_id (任意)")
    source_doc_id = Column(String(20), comment="ir_documents.doc_id (任意)")
    prompt = Column(Text, comment="生成に使った system+user プロンプト")
    content = Column(Text, comment="生成物 (JSON/CSV/GAS)")
    created_at = Column(DateTime, default=datetime.utcnow)
    note = Column(Text)


class ExtractedTable(P3Base):
    """
    マルチモーダル LLM でスライド画像から復元した表の中間表現。
    列ヘッダ x 行ヘッダ x 数値 の正規化後データ。
    """
    __tablename__ = "ir_extracted_tables"

    table_id = Column(Integer, primary_key=True, autoincrement=True)
    source_slide_id = Column(Integer, comment="ir_presentation_slides.slide_id")
    caption = Column(Text)
    json_table = Column(Text, comment="JSON: {columns, rows, meta}")
    created_at = Column(DateTime, default=datetime.utcnow)


def init_phase3_schema(db_path: str):
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    P3Base.metadata.create_all(engine)
    return engine


def get_phase3_session(db_path: str):
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    return sessionmaker(bind=engine)()

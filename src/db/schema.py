from sqlalchemy import Column, String, Float, Integer, Text, Index, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()

class FinancialRaw(Base):
    """
    XBRLから抽出した生データを格納するEAV(Entity-Attribute-Value)テーブルモデル。
    """
    __tablename__ = 'financial_raw'

    # 主キー（サロゲートキー）
    id = Column(Integer, primary_key=True, autoincrement=True)

    # エンティティ識別子
    security_code = Column(String(10), nullable=False, comment="証券コード") 
    doc_id = Column(String(50), nullable=False, comment="書類管理ID (EDINETのdocIDなど)")

    # 属性（Attribute）
    period = Column(String(50), comment="期間情報 (YYYY-MM-DD または Duration文字列)")
    tag_name = Column(String(255), nullable=False, comment="XBRL要素名 (Tag Name)")
    context_id = Column(String(255), comment="ContextRef値")

    # 値（Value）と単位
    raw_value = Column(Text, comment="元の値 (文字列)")
    normalized_value = Column(Float, comment="スケーリング後の数値")
    unit = Column(String(50), comment="単位 (JPY, Shares等)")
    decimals = Column(String(20), comment="精度属性値")

    # インデックス設計
    __table_args__ = (
        # 1. 分析用クエリの高速化: 特定企業の特定の科目を時系列で取得する場合
        #    WHERE security_code = ? AND tag_name = ?
        Index('idx_financial_sec_tag', 'security_code', 'tag_name'),

        # 2. ドキュメント単位の操作用: 特定の提出書類データをまとめて取得または削除する場合
        #    WHERE doc_id = ?
        Index('idx_financial_doc_id', 'doc_id'),

        # 3. 横断分析用: 特定の科目を全社横断で比較する場合
        #    WHERE tag_name = ? AND period = ?
        Index('idx_financial_tag_period', 'tag_name', 'period'),
    )

    def __repr__(self):
        return f"<FinancialRaw(code={self.security_code}, tag={self.tag_name}, val={self.normalized_value})>"

def init_db(db_path: str):
    """
    データベースとテーブルを初期化する。
    
    Args:
        db_path (str): SQLiteデータベースファイルへのパス
    """
    engine = create_engine(f'sqlite:///{db_path}', echo=False)
    Base.metadata.create_all(engine)
    return engine

def get_session(db_path: str):
    """
    セッションファクトリを返すヘルパー関数
    """
    engine = create_engine(f'sqlite:///{db_path}', echo=False)
    Session = sessionmaker(bind=engine)
    return Session()

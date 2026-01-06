from typing import List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
import logging

from src.db.schema import get_session, FinancialRaw

logger = logging.getLogger(__name__)

class FinancialDbClient:
    """
    FinancialRawテーブルへのバルクインサートを管理するDBクライアント。
    データをメモリバッファに保持し、一定量に達した時点で一括挿入を行う。
    """

    def __init__(self, db_path: str, batch_size: int = 10000):
        """
        Args:
            db_path (str): SQLiteデータベースのパス
            batch_size (int): 一括コミットするレコード数の閾値
        """
        self.session: Session = get_session(db_path)
        self.batch_size = batch_size
        self.buffer: List[Dict[str, Any]] = []

    def insert_record(self, record: Dict[str, Any]):
        """
        1件のデータをバッファに追加する。
        
        Args:
            record (Dict[str, Any]): FinancialRawモデルに対応する辞書データ
        """
        self.buffer.append(record)
        if len(self.buffer) >= self.batch_size:
            self.flush()

    def insert_many(self, records: List[Dict[str, Any]]):
        """
        複数のデータを一括でバッファに追加する。
        1ファイル分のデータをまとめて追加する場合などに使用。
        
        Args:
            records (List[Dict[str, Any]]): 辞書データのリスト
        """
        self.buffer.extend(records)
        if len(self.buffer) >= self.batch_size:
            self.flush()

    def flush(self):
        """
        バッファ内のデータをデータベースに一括挿入（バルクインサート）し、コミットする。
        SQLAlchemyの bulk_insert_mappings を使用して高速化を図る。
        """
        if not self.buffer:
            return

        try:
            # bulk_insert_mappings はORMオブジェクト生成コストをスキップするため高速
            self.session.bulk_insert_mappings(FinancialRaw, self.buffer)
            self.session.commit()
            # logger.info(f"Flushed {len(self.buffer)} records to DB.")
            self.buffer.clear()
        except SQLAlchemyError as e:
            self.session.rollback()
            logger.error(f"Database error during flush: {e}")
            raise e
        except Exception as e:
            self.session.rollback()
            logger.error(f"Unexpected error during flush: {e}")
            raise e

    def close(self):
        """
        残存データをフラッシュし、セッションをクローズする。
        """
        try:
            self.flush()
        finally:
            self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        コンテキストマネージャ終了時の処理。
        例外発生時はロールバックし、正常終了時は残データをフラッシュして閉じる。
        """
        if exc_type:
            logger.error(f"Exception in DB context: {exc_val}")
            self.session.rollback()
            self.session.close()
            return False # 例外を伝播
        
        self.close()

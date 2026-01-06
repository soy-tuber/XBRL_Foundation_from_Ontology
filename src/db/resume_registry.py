import sqlite3
import logging
from datetime import datetime
from typing import List, Callable, Tuple, Set

logger = logging.getLogger(__name__)

class ResumeRegistry:
    """
    処理済みのファイル（docID）を管理し、重複処理をスキップするためのレジストリクラス。
    SQLiteを使用して永続化する。
    """

    def __init__(self, db_path: str = "processing_history.db"):
        """
        Args:
            db_path (str): 履歴管理用SQLiteデータベースのパス
        """
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """データベースとテーブルの初期化"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS processing_history (
                        doc_id TEXT PRIMARY KEY,
                        file_path TEXT,
                        status TEXT,
                        processed_at TIMESTAMP,
                        error_message TEXT
                    )
                """)
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to initialize resume database: {e}")
            raise

    def is_processed(self, doc_id: str) -> bool:
        """
        指定されたdoc_idが正常に処理済みかを確認する。
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT 1 FROM processing_history WHERE doc_id = ? AND status = 'success'", 
                    (doc_id,)
                )
                return cursor.fetchone() is not None
        except sqlite3.Error as e:
            logger.error(f"Error checking status for {doc_id}: {e}")
            return False

    def mark_as_processed(self, doc_id: str, file_path: str):
        """
        処理成功として記録する。
        """
        self._upsert(doc_id, file_path, "success", None)

    def mark_as_error(self, doc_id: str, file_path: str, error_message: str):
        """
        処理失敗（エラー）として記録する。
        """
        self._upsert(doc_id, file_path, "error", error_message)

    def _upsert(self, doc_id: str, file_path: str, status: str, error_message: str):
        """
        INSERT OR REPLACE でステータスを更新する。
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO processing_history (doc_id, file_path, status, processed_at, error_message)
                    VALUES (?, ?, ?, ?, ?)
                """, (doc_id, file_path, status, datetime.now(), error_message))
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to update status for {doc_id}: {e}")

    def filter_unprocessed_files(self, file_paths: List[str], id_extractor: Callable[[str], str]) -> List[str]:
        """
        ファイルリストを受け取り、未処理のファイルのみのリストを返す。
        
        Args:
            file_paths (List[str]): 処理候補のファイルパスリスト
            id_extractor (Callable[[str], str]): ファイルパスからdocIDを抽出する関数

        Returns:
            List[str]: 未処理のファイルパスリスト
        """
        # パフォーマンス向上のため、処理済みIDを一括取得してセットにする
        processed_ids = self._get_all_processed_ids()
        
        unprocessed_files = []
        skipped_count = 0
        
        for path in file_paths:
            try:
                doc_id = id_extractor(path)
                if doc_id not in processed_ids:
                    unprocessed_files.append(path)
                else:
                    skipped_count += 1
            except Exception as e:
                logger.warning(f"Failed to extract ID from {path}, skipping check: {e}")
                # ID抽出できないものはとりあえず処理対象に含めるか、スキップするか方針によるが、
                # ここでは安全のため処理対象に含める
                unprocessed_files.append(path)

        logger.info(f"Resume check: {len(file_paths)} files provided -> {len(unprocessed_files)} to process ({skipped_count} skipped).")
        return unprocessed_files

    def _get_all_processed_ids(self) -> Set[str]:
        """全ての処理成功済みdoc_idを取得する"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT doc_id FROM processing_history WHERE status = 'success'")
                return {row[0] for row in cursor.fetchall()}
        except sqlite3.Error:
            return set()

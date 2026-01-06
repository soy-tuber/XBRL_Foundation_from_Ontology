import os
import glob
import logging
import shutil
import tempfile
import zipfile
from typing import List, Dict, Any, Tuple, Optional

from src.parser.xbrl_parser import XbrlParser
from src.db.client import FinancialDbClient
from src.db.resume_registry import ResumeRegistry
from src.executor import BatchExecutor

logger = logging.getLogger(__name__)

def process_zip_file(zip_path: str) -> Optional[Tuple[str, List[Dict[str, Any]]]]:
    """
    1つのZIPファイルを処理するワーカー関数。
    ZIPを展開し、XBRLファイルを特定してパースする。
    
    Args:
        zip_path (str): ZIPファイルのパス

    Returns:
        Tuple[str, List[Dict]]: (doc_id, 抽出されたレコードのリスト)。エラー時はNone。
                                doc_idはZIPファイル名の先頭部分（[DocID]_....zip）を使用する。
    """
    # doc_id はZIPファイル名の先頭部分を使用する
    # 例: S100X_7203_トヨタ_2024-05.zip -> S100X
    filename = os.path.basename(zip_path)
    if '_' in filename:
        doc_id = filename.split('_')[0]
    else:
        doc_id = os.path.splitext(filename)[0]
    
    temp_dir = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        
        # .xbrl ファイルを探す (PublicDocフォルダにあるものを優先探索)
        # 通常構造: XBRL/PublicDoc/*.xbrl
        xbrl_files = glob.glob(os.path.join(temp_dir, '**', '*.xbrl'), recursive=True)
        
        # 監査用(AuditDoc)ではなく公開用(PublicDoc)が望ましいが、
        # シンプルに "PublicDoc" がパスに含まれるものを優先、なければ最初のxbrlを使う
        target_xbrl = None
        for xf in xbrl_files:
            if 'PublicDoc' in xf:
                target_xbrl = xf
                break
        
        if not target_xbrl and xbrl_files:
            target_xbrl = xbrl_files[0]
            
        if not target_xbrl:
            logger.warning(f"No XBRL file found in {zip_path}")
            return (doc_id, []) # データなしとして返す

        # パース実行
        parser = XbrlParser(target_xbrl)
        records = parser.parse()
        
        # doc_id をZIPファイル名ベースのもので上書き（パース内部ではxbrlファイル名を使っているため）
        for record in records:
            record['doc_id'] = doc_id
            
        return (doc_id, records)

    except zipfile.BadZipFile:
        logger.error(f"Bad zip file: {zip_path}")
        raise # executorで捕捉させる
    except Exception as e:
        logger.error(f"Error processing zip {zip_path}: {e}")
        raise
    finally:
        # クリーンアップ
        shutil.rmtree(temp_dir, ignore_errors=True)


class EtlRunner:
    """
    指定ディレクトリ内のZIPファイルを探索し、パースしてDBに格納するパイプラインランナー。
    """

    def __init__(self, db_path: str, processing_chunk_size: int = 50):
        """
        Args:
            db_path (str): データベース・ファイルのパス
            processing_chunk_size (int): 1回のバッチ処理（並列実行）で投入するファイル数
        """
        self.db_path = db_path
        self.processing_chunk_size = processing_chunk_size
        self.resume_registry = ResumeRegistry(db_path.replace('.db', '_history.db')) # 履歴DBは別名で管理推奨だが、ここではsuffixで対応

    def run(self, source_dir: str, max_workers: Optional[int] = None):
        """
        パイプラインを実行する。

        Args:
            source_dir (str): XBRL(ZIP)ファイルが格納されているディレクトリ
            max_workers (int): 並列数
        """
        logger.info(f"Starting ETL pipeline for directory: {source_dir}")
        
        # 1. ファイルリストアップ
        all_zips = glob.glob(os.path.join(source_dir, "*.zip"))
        
        # 2. レジューム機能によるフィルタ
        files_to_process = self.resume_registry.filter_unprocessed_files(
            all_zips, 
            lambda p: os.path.splitext(os.path.basename(p))[0]
        )
        
        if not files_to_process:
            logger.info("No new files to process.")
            return

        executor = BatchExecutor(max_workers=max_workers, error_dir=os.path.join(source_dir, "failed"))
        total_files = len(files_to_process)
        
        # 3. チャンクごとに処理（メモリ溢れ防止）
        for i in range(0, total_files, self.processing_chunk_size):
            chunk = files_to_process[i : i + self.processing_chunk_size]
            logger.info(f"Processing chunk {i // self.processing_chunk_size + 1}: {len(chunk)} files...")

            # A. 並列パース実行
            # executor.process_files は List[Result] を返す
            # Result は process_zip_file の戻り値 = (doc_id, records)
            results = executor.process_files(chunk, process_zip_file)
            
            # B. DB格納フェーズ
            success_count = 0
            with FinancialDbClient(self.db_path) as db_client:
                for res in results:
                    if not res:
                        continue
                        
                    doc_id, records = res
                    
                    try:
                        # 0件でも処理済みとみなすか、データがある場合のみとするか
                        # ここではレコードがあればインサート
                        if records:
                            db_client.insert_many(records)
                        
                        # C. 履歴更新
                        # DBコミットは insert_many 内のバッファフラッシュで行われるため、
                        # ここでの履歴更新は厳密にはトランザクション外だが、許容範囲とする
                        # (より厳密にするならDBClientとResumeRegistryで同じConnを使う必要がある)
                        self.resume_registry.mark_as_processed(doc_id, "source_path_info_omitted")
                        success_count += 1
                        
                    except Exception as e:
                        logger.error(f"Failed to save records for {doc_id}: {e}")
                        self.resume_registry.mark_as_error(doc_id, "unknown", str(e))

            logger.info(f"Chunk completed. Saved data for {success_count} documents.")

        logger.info("ETL pipeline completed.")

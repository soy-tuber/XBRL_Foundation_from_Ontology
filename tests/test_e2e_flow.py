import sys
import os
import shutil
import logging
from datetime import datetime

# プロジェクトルートにパスを通す
sys.path.append(os.getcwd())

from src.config import load_config
from src.downloader.edinet_api_client import EdinetApiClient
from src.downloader.gdrive_manager import GDriveManager
from src.pipeline.etl_runner import EtlRunner
from src.db.schema import get_session, FinancialRaw, init_db

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("E2ETest")

def test_pipeline():
    print("=== Starting End-to-End Pipeline Test ===")
    
    config = load_config()
    target_date = "2024-05-31" # テスト対象日（有報が出ている可能性が高い月末）
    target_month = "2024-05"

    # 1. API Client Init
    print(f"\n[1] Initializing Client with key ending in ...{config['api_key'][-4:] if config['api_key'] else 'None'}")
    api_client = EdinetApiClient(api_key=config['api_key'])
    
    # 2. Drive Manager Init
    # テスト用に一時的なダウンロードフォルダを使うか、構成通りの場所を使うか
    # ここでは構成通りの場所を使うが、既存ファイルを上書きしないか注意
    print(f"\n[2] Drive Manager Init at {config['drive_path']}")
    drive_manager = GDriveManager(base_path=config['drive_path'])
    
    # 3. Get List
    print(f"\n[3] Fetching document list for {target_date}...")
    doc_list = api_client.get_document_list(target_date, type_code=2)
    results = doc_list.get("results", [])
    print(f"    Found {len(results)} documents.")
    
    if not results:
        print("    No documents found. Test Aborted.")
        return

    # XBRLフラグがあり、かつ証券コードがある最初の1件を探す
    target_doc = None
    for doc in results:
        if doc.get("xbrlFlag") == "1" and doc.get("secCode"):
            target_doc = doc
            break
            
    if not target_doc:
        # 見つからない場合は適当な日を変える等検討
        # 5/31なら確実にあるはず
        print("    No XBRL document found in list. Test Aborted.")
        return

    doc_id = target_doc["docID"]
    filer_name = target_doc.get("filerName", "Unknown")
    print(f"    Target Document: {doc_id} ({filer_name})")

    # 4. Download
    # 保存先チェック
    save_path = drive_manager.get_save_path_if_not_exists(
        year_month=target_month,
        doc_id=doc_id,
        sec_code=target_doc.get("secCode", "0000")[:4],
        company_name=filer_name,
        filing_date=target_date
    )
    
    if save_path:
        print(f"\n[4] Downloading {doc_id} ...")
        zip_bytes = api_client.download_document(doc_id, type_code=1)
        if zip_bytes:
            saved_path = drive_manager.save_file(zip_bytes, target_month, save_path.name)
            print(f"    Saved to {saved_path}")
        else:
            print("    Download failed. Test Aborted.")
            return
    else:
        print(f"\n[4] File already exists, skipping download phase.")

    # 5. ETL run
    print(f"\n[5] Running ETL for folder {target_month} ...")
    # テストなので、対象の月フォルダ全体をスキャンするが、
    # 処理済み履歴(processing_history)によってどうなるか確認
    # ConfigのDBパスを使用
    db_path = config["db_path"]
    
    # DBの親ディレクトリ作成
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    # テーブル初期化（create table if not exists）
    init_db(db_path)
    
    runner = EtlRunner(db_path=db_path, processing_chunk_size=1)
    
    target_dir = drive_manager.get_context_directory(target_month)
    runner.run(source_dir=str(target_dir))
    
    # 6. Verify DB
    print(f"\n[6] Verifying DB content in {db_path} ...")
    session = get_session(db_path)
    try:
        count = session.query(FinancialRaw).filter(FinancialRaw.doc_id == doc_id).count()
        print(f"    Records found for doc_id={doc_id}: {count}")
        
        if count > 0:
            sample = session.query(FinancialRaw).filter(FinancialRaw.doc_id == doc_id).first()
            print(f"    Sample Record: {sample.tag_name} = {sample.raw_value} (Unit: {sample.unit})")
        else:
            print("    No records found! ETL might have failed or skipped.")
            
    finally:
        session.close()

if __name__ == "__main__":
    test_pipeline()

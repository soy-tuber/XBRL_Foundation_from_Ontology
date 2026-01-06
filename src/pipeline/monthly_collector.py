import sys
import os
import argparse
import time
import logging
from datetime import datetime, timedelta
from typing import List

# プロジェクトルートにパスを通す
sys.path.append(os.getcwd())

from src.config import load_config
from src.downloader.edinet_api_client import EdinetApiClient
from src.downloader.gdrive_manager import GDriveManager
from src.pipeline.etl_runner import EtlRunner

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("monthly_collector.log")
    ]
)
logger = logging.getLogger(__name__)

def get_target_dates(year_month: str) -> List[str]:
    """
    指定された年月（YYYY-MM）に含まれる全ての日付リスト（YYYY-MM-DD）を返す。
    """
    try:
        # 月初
        start_date = datetime.strptime(year_month, "%Y-%m")
        # 翌月月初 - 1日 = 月末
        if start_date.month == 12:
            next_month = start_date.replace(year=start_date.year + 1, month=1)
        else:
            next_month = start_date.replace(month=start_date.month + 1)
        
        end_date = next_month - timedelta(days=1)
        
        dates = []
        current = start_date
        while current <= end_date:
            dates.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)
        return dates
        
    except ValueError:
        logger.error(f"Invalid date format: {year_month}. Use YYYY-MM.")
        return []

def main():
    parser = argparse.ArgumentParser(description="Monthly EDINET Collector & ETL")
    parser.add_argument("target_month", help="Target month in YYYY-MM format (e.g., 2024-05)")
    parser.add_argument("--skip-download", action="store_true", help="Skip download phase")
    parser.add_argument("--skip-db", action="store_true", help="Skip DB insert phase")
    parser.add_argument("--auto-yes", action="store_true", help="Skip confirmation")
    
    args = parser.parse_args()
    config = load_config()
    
    # 1. コンポーネント初期化
    api_client = EdinetApiClient(api_key=config["api_key"])
    # GDriveManagerのbase_pathは環境変数かデフォルト値を使用
    drive_manager = GDriveManager(base_path=config["drive_path"])
    
    target_month = args.target_month
    dates = get_target_dates(target_month)
    
    if not dates:
        logger.error("No dates calculated.")
        return

    logger.info(f"=== Starting Monthly Collection for {target_month} ===")
    logger.info(f"Target path: {drive_manager.base_path}/{target_month}")
    
    # --- Phase 1: Download ---
    if not args.skip_download:
        logger.info(">>> Phase 1: Downloading Documents...")
        
        for date_str in dates:
            logger.info(f"Checking documents for {date_str}...")
            try:
                # 書類一覧取得 (type=2: 一覧+メタデータ)
                doc_list = api_client.get_document_list(date_str, type_code=2)
                results = doc_list.get("results", [])
                
                if not results:
                    logger.info(f"  No documents found for {date_str}.")
                    time.sleep(1) # API制限考慮（簡易）
                    continue
                
                target_docs = []
                for doc in results:
                    # フィルタリング条件:
                    # 1. 提出本文書である (docTypeCode=120, 130など 有報・四半期)
                    #    ここでは広めに 120(有報), 130(四半期), 140(半期), 150(臨時), 160(訂正) 等を取得するか？
                    #    一旦、XBRLがあるもの(legalStatus='1')、かつ docInfoEditStatus='0'(訂正なし) または適宜
                    #    シンプルに「XBRLフラグがあるもの」を対象とする
                    if doc.get("xbrlFlag") == "1":
                        target_docs.append(doc)
                
                logger.info(f"  Found {len(target_docs)} XBRL documents.")
                
                for doc in target_docs:
                    doc_id = doc["docID"]
                    sec_code = doc.get("secCode")
                    
                    if not sec_code:
                        # 証券コードがない（ファンド等）はスキップ
                        continue
                        
                    sec_code = sec_code[:4] # 5桁目をカット
                    filer_name = doc.get("filerName", "Unknown")
                    
                    # 保存パスの確認（重複チェック）
                    save_path = drive_manager.get_save_path_if_not_exists(
                        year_month=target_month,
                        doc_id=doc_id,
                        sec_code=sec_code,
                        company_name=filer_name,
                        filing_date=date_str
                    )
                    
                    if save_path is None:
                        # 既に存在する
                        logger.debug(f"  Skipping {doc_id}, already exists.")
                        continue
                        
                    # ダウンロード実行
                    logger.info(f"  Downloading {doc_id} ({filer_name})...")
                    zip_bytes = api_client.download_document(doc_id, type_code=1)
                    
                    if zip_bytes:
                        # 保存
                        drive_manager.save_file(
                            content=zip_bytes,
                            year_month=target_month,
                            filename=save_path.name
                        )
                        # APIレートリミット考慮（適宜調整）
                        time.sleep(0.5)
                    else:
                        logger.warning(f"  Failed to download content for {doc_id}")

            except Exception as e:
                logger.error(f"Error processing date {date_str}: {e}")
                
            # 日付ごとのウェイト
            time.sleep(2)
            
    else:
        logger.info(">>> Phase 1 Skipped.")

    # --- Phase 2: ETL (DB Insert) ---
    if not args.skip_db:
        logger.info(">>> Phase 2: Parse & DB Insert...")
        
        # 月次フォルダのパスを取得
        target_dir = drive_manager.get_context_directory(target_month)
        
        # ETLランナー起動
        try:
            etl_runner = EtlRunner(db_path=config["db_path"])
            # 並列数はデフォルト（CPUコア数）に任せる
            etl_runner.run(source_dir=str(target_dir))
            
        except Exception as e:
            logger.error(f"ETL Runner failed: {e}")
            
    else:
        logger.info(">>> Phase 2 Skipped.")

    logger.info(f"=== Monthly Collection for {target_month} Completed ===")

if __name__ == "__main__":
    main()

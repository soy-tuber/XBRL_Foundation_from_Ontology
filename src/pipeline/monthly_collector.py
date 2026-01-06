import sys
import os
import time
import argparse
import logging
import calendar
from datetime import datetime, timedelta
from typing import List

# プロジェクトルートパスを明示的に追加（srcフォルダの2階層上）
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.config import load_config
from src.downloader.edinet_api_client import EdinetApiClient
from src.downloader.gdrive_manager import GDriveManager
from src.pipeline.etl_runner import EtlRunner

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MonthlyCollector:
    def __init__(self):
        config = load_config()
        self.api_client = EdinetApiClient(config['api_key'])
        self.drive_manager = GDriveManager(base_path=config['drive_path'])
        self.etl_runner = EtlRunner(db_path=config['db_path'])

    def run(self, target_month: str, skip_download: bool = False, prime_annual_only: bool = False):
        logger.info(f"Starting monthly collection for {target_month}")
        
        try:
            year, month = map(int, target_month.split('-'))
            _, last_day = calendar.monthrange(year, month)
            start_date = datetime(year, month, 1)
            end_date = datetime(year, month, last_day)
        except ValueError:
            logger.error("Invalid date format. Use YYYY-MM.")
            return
        
        month_dir = self.drive_manager.get_context_directory(target_month)
        logger.info(f"Target directory: {month_dir}")

        # 1. ダウンロードフェーズ
        if not skip_download:
            current_date = start_date
            while current_date <= end_date:
                date_str = current_date.strftime('%Y-%m-%d')
                logger.info(f"Checking documents for {date_str}...")
                
                try:
                    documents = self.api_client.get_document_list(date_str)
                    target_docs = []
                    
                    if isinstance(documents, list):
                        for doc in documents:
                            if not isinstance(doc, dict):
                                continue

                            if prime_annual_only:
                                # 有価証券報告書(120)かつ証券コードありのみ
                                if doc.get('secCode') and doc.get('docTypeCode') == '120':
                                    target_docs.append(doc)
                            else:
                                # 証券コードがあるものは一通り対象
                                if doc.get('secCode'):
                                    target_docs.append(doc)
                        
                        logger.info(f"Found {len(documents)} docs. Targets: {len(target_docs)}")

                        for doc in target_docs:
                            self._process_single_doc(doc, date_str)
                    else:
                        logger.warning(f"Unexpected response for {date_str}: {documents}")

                except Exception as e:
                    logger.error(f"Error processing {date_str}: {e}")
                
                current_date += timedelta(days=1)
                time.sleep(2) # APIレートリミット
        else:
            logger.info("Skipping download phase.")

        # 2. ETLフェーズ
        logger.info(f"Starting ETL for {target_month}...")
        self.etl_runner.run(str(month_dir))
        logger.info("Monthly collection completed.")

    def _process_single_doc(self, doc, date_str):
        sec_code = doc.get('secCode')
        filer_name = doc.get('filerName')
        doc_id = doc.get('docID')
        
        if not doc_id:
            return

        save_path = self.drive_manager.get_save_path_if_not_exists(
            year_month=date_str[:7],
            sec_code=sec_code,
            company_name=filer_name,
            filing_date=date_str,
            doc_id=doc_id
        )
        
        if save_path is None:
            return

        try:
            content = self.api_client.get_document_file(doc_id)
            if content:
                with open(save_path, 'wb') as f:
                    f.write(content)
                logger.info(f"Downloaded {doc_id} -> {save_path}")
                time.sleep(1)
        except Exception as e:
            logger.error(f"Failed download {doc_id}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Monthly EDINET Collector')
    parser.add_argument('month', help='Target month (YYYY-MM)')
    parser.add_argument('--skip-download', action='store_true', help='Skip download phase')
    parser.add_argument('--prime', action='store_true', dest='prime_annual_only',
                        help='Filter for Annual Securities Reports (120)')
    
    args = parser.parse_args()
    
    collector = MonthlyCollector()
    collector.run(args.month, skip_download=args.skip_download, prime_annual_only=args.prime_annual_only)
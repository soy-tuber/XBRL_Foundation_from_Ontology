import sys
import os
import time
import argparse
import logging

# プロジェクトルートパスを明示的に追加
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.pipeline.monthly_collector import MonthlyCollector

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("YearBatch")

def main():
    parser = argparse.ArgumentParser(description='Run monthly collector for a full year')
    parser.add_argument('year', type=int, help='Target year (YYYY)')
    args = parser.parse_args()

    collector = MonthlyCollector()
    year = args.year

    logger.info(f"Starting batch collection for Year {year} (Annual Reports Only)")

    # 1月から12月までループ
    for month in range(1, 13):
        target_month = f"{year}-{month:02d}"
        logger.info(f"\n{'='*10} Processing {target_month} {'='*10}")
        
        try:
            # fetch_all_types=False なのでデフォルト設定（年次有価証券報告書のみ）で動作
            # エラーが出てもここでキャッチして、次の月に進むようにする
            collector.run(target_month, skip_download=False, fetch_all_types=False)
        except KeyboardInterrupt:
            logger.warning("Interrupted by user. Exiting batch process.")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Critical error occurred in {target_month}, skipping to next month: {e}")
            # エラーでも続行する

        logger.info(f"Completed {target_month}. Waiting 5 seconds before next month...")
        time.sleep(5)

    logger.info("All months processed.")

if __name__ == "__main__":
    main()

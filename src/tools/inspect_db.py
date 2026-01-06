import sys
import os
import sqlite3
import pandas as pd

# プロジェクトルートパスを明示的に追加（srcフォルダの2階層上）
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.config import load_config

def inspect():
    try:
        config = load_config()
        db_path = config['db_path']
        
        if not os.path.exists(db_path):
            print(f"Error: Database file not found at {db_path}")
            return

        print(f"=== Database Inspection: {db_path} ===")
        conn = sqlite3.connect(db_path)

        # 1. 全レコード数
        try:
            count = pd.read_sql("SELECT count(*) FROM financial_raw", conn).iloc[0, 0]
            print(f"\n[Total Records]: {count:,}")
        except Exception as e:
            print(f"Table 'financial_raw' check failed: {e}")
            conn.close()
            return

        if count == 0:
            print("Database is empty.")
            conn.close()
            return

        # 2. ユニークなドキュメントID一覧
        print(f"\n[Latest Documents by Data Size]")
        docs_df = pd.read_sql("""
            SELECT doc_id, count(*) as items_count 
            FROM financial_raw 
            GROUP BY doc_id 
            ORDER BY rowid DESC
            LIMIT 10
        """, conn)
        print(docs_df.to_string(index=False))

        # 3. データのサンプル表示
        print(f"\n[Sample Data (Last 5 records)]")
        # 列を指定せず(*)全て取得し、そのまま表示する（エラー回避）
        sample_df = pd.read_sql("SELECT * FROM financial_raw ORDER BY rowid DESC LIMIT 5", conn)
        print(sample_df.to_string(index=False))

        conn.close()

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    inspect()
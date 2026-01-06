from dotenv import load_dotenv
import os

# .envファイルを読み込む
load_dotenv()

def load_config():
    """
    環境設定をロードして検証する。
    """
    api_key = os.getenv("EDINET_API_KEY")
    drive_path = os.getenv("EDINET_DRIVE_PATH")
    
    if not api_key:
        print("Warning: EDINET_API_KEY is not set. API calls might fail.")
    
    if not drive_path:
        # デフォルトパスを設定（開発環境用）
        drive_path = os.path.join(os.getcwd(), "data", "edinet_downloads")
        os.makedirs(drive_path, exist_ok=True)
        print(f"Info: EDINET_DRIVE_PATH not set, using default: {drive_path}")
        
    return {
        "api_key": api_key,
        "drive_path": drive_path,
        "db_path": os.getenv("DB_PATH", "data/xbrl_financial.db")
    }

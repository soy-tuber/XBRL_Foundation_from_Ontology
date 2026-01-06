import os
import time
import requests
import logging
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

class EdinetApiClient:
    """
    EDINET API (v2) を利用して書類一覧の取得および書類（ZIP）のダウンロードを行うクライアント。
    APIキー（Subscription-Key）の認証に対応。
    """

    BASE_URL = "https://api.edinet-fsa.go.jp/api/v2"

    def __init__(self, api_key: Optional[str] = None):
        """
        Args:
            api_key (str, optional): EDINET APIのSubscription-Key。
                                     指定がない場合、環境変数 `EDINET_API_KEY` を参照する。
        """
        self.api_key = api_key or os.getenv("EDINET_API_KEY")
        if not self.api_key:
            logger.warning("EDINET_API_KEY is not set. API v2 requests may fail or be limited.")

    def _get_headers(self) -> Dict[str, str]:
        headers = {}
        if self.api_key:
            headers["Ocp-Apim-Subscription-Key"] = self.api_key
        return headers

    def get_document_list(self, date_str: str, type_code: int = 2) -> Dict[str, Any]:
        """
        指定された日付の書類一覧を取得する。

        Args:
            date_str (str): 取得対象日 (YYYY-MM-DD)
            type_code (int): 取得情報の種類 (1:メタデータのみ, 2:提出書類一覧及びメタデータ)。デフォルトは2。

        Returns:
            Dict: APIレスポンスのJSONデータ
        """
        url = f"{self.BASE_URL}/documents.json"
        params = {
            "date": date_str,
            "type": type_code
        }
        
        try:
            response = requests.get(url, params=params, headers=self._get_headers(), timeout=30)
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                # 休日などでデータがない場合は404が返ることがある仕様
                logger.info(f"No documents found for {date_str} (Status 404).")
                return {"results": []}
            else:
                logger.error(f"Failed to get document list for {date_str}. Status: {response.status_code}, Msg: {response.text}")
                response.raise_for_status()
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error getting document list: {e}")
            raise
        
        return {"results": []}

    def download_document(self, doc_id: str, type_code: int = 1) -> Optional[bytes]:
        """
        指定された書類IDのファイルをダウンロードする。

        Args:
            doc_id (str): 書類管理番号
            type_code (int): 1:提出本文書(ZIP), 2:PDF, etc. デフォルトは1(ZIP)。

        Returns:
            bytes: ダウンロードしたファイルの内容。失敗時はNone。
        """
        url = f"{self.BASE_URL}/documents/{doc_id}"
        params = {"type": type_code}
        
        try:
            # 大きなファイルを扱う可能性があるため stream=True を検討しても良いが、
            # 有報ZIPは数MB〜数十MB程度なので今回はオンメモリで扱う
            response = requests.get(url, params=params, headers=self._get_headers(), timeout=60)
            
            if response.status_code == 200:
                logger.info(f"Downloaded document {doc_id} successfully.")
                return response.content
            else:
                logger.error(f"Failed to download {doc_id}. Status: {response.status_code}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error downloading document {doc_id}: {e}")
            return None
        
        # リクエスト間隔の調整は呼び出し元で行う（ループ処理側でsleepを入れる）

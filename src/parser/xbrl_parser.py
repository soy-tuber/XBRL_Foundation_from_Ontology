import os
import re
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup
from src.parser.context_handler import ContextHandler
from src.parser.normalizer import ValueNormalizer
from src.parser.metadata_extractor import MetadataExtractor

class XbrlParser:
    """
    XBRLファイルをパースし、データベース格納用のフラットな辞書リストに変換するクラス。
    
    方針:
    1. 全勘定科目（数値）を取得。
    2. 短いテキスト情報（メタデータ等）を取得。
    3. 長文（テキストブロック）は除外して軽量化。
    """

    # 短いテキストとみなす最大文字数。これを超える、またはTextBlockと名のつくものは除外。
    MAX_TEXT_LENGTH = 500 

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.soup: Optional[BeautifulSoup] = None

    def parse(self) -> List[Dict[str, Any]]:
        """
        XBRLをパースしてデータのリストを返す。
        """
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"File not found: {self.file_path}")

        with open(self.file_path, 'r', encoding='utf-8') as f:
            # lxml-xmlパーサーを使用（高速かつXML対応）
            self.soup = BeautifulSoup(f, 'lxml-xml')

        # 書類全体のメタデータ（証券コードなど）を取得
        file_meta = MetadataExtractor.extract(self.file_path)
        
        # doc_id はファイル名から簡易的に取得（命名規則に依存: docID_....xbrl）
        # もしくは上位ロジックから渡されるべきだが、ここではファイル名ベースで生成
        filename = os.path.basename(self.file_path)
        doc_id = filename.split('_')[0] if '_' in filename else filename.replace('.xbrl', '')

        records = []
        
        # 名前空間の定義（必要なら使用するが、今回はタグ名末尾一致などの簡易手法をとる）
        # 全てのタグを走査
        # find_all(True) で全タグ取得し、フィルタリングする
        for tag in self.soup.find_all(True):
            # 1. 除外すべきシステム用タグ
            if tag.name in ['xbrl', 'link', 'schemaRef', 'context', 'unit', 'header', 'hidden', 'measure']:
                continue
            if ':' in tag.name and tag.name.split(':')[0] in ['link', 'xbrli', 'xlink']:
                continue
            
            context_id = tag.get('contextRef')
            if not context_id:
                # contextRefを持たないタグ（構造定義タグなど）はスキップ
                continue

            # 値の取得
            raw_value = tag.text.strip()
            if not raw_value:
                continue

            unit_ref = tag.get('unitRef')
            decimals = tag.get('decimals')

            # 2. フィルタリングロジック
            is_numeric = (unit_ref is not None) or (decimals is not None)
            
            if is_numeric:
                # 数値項目: 全て取得
                normalized_val = ValueNormalizer.normalize(raw_value, decimals, unit_ref)
                # 数値が0で、かつraw_valueも空に近い場合はスキップしても良いが、
                # "0"という事実は重要なので残す。
            else:
                # テキスト項目: フィルタリング適用
                
                # A. TextBlockタグ（HTML含む長文）は明示的に除外
                if 'TextBlock' in tag.name:
                    continue
                
                # B. 文字数制限
                if len(raw_value) > self.MAX_TEXT_LENGTH:
                    continue
                
                # 短いテキストのみ保存
                normalized_val = None # テキストなので数値カラムはNull

            # 3. Period (期間) の判定
            # contextタグを探して日時情報を取得するのは重いため、IDから推測するか、
            # あるいはContextHandlerで解析する。
            # ここではシンプルにIDを入れる。analyze時にはContextテーブルとのJOIN推奨だが、
            # 1次DBとしては denormalize して period 文字列を入れておくと便利。
            # ※ 本格実装では、別途 self.soup から context 定義をパースして辞書化しておくのがベスト。
            # 今回は簡易的に ContextHandler のロジックで Instant/Duration だけ入れる。
            period_type = ContextHandler.get_period_type(context_id)
            
            # レコード作成
            record = {
                "security_code": file_meta.get('security_code') or "Unknown",
                "doc_id": doc_id,
                "period": period_type, # 必要に応じて具体的な日付を入れるロジックに拡張可
                "tag_name": tag.name,
                "context_id": context_id,
                "raw_value": raw_value if not is_numeric else raw_value, # 数値でも元の文字列表現を残す
                "normalized_value": normalized_val,
                "unit": unit_ref,
                "decimals": decimals
            }
            records.append(record)

        return records

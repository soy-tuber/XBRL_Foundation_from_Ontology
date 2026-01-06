import os
import sys
import logging
from bs4 import BeautifulSoup

# srcモジュールをインポート可能にする
sys.path.append(os.path.join(os.getcwd()))

from src.parser.metadata_extractor import MetadataExtractor
from src.parser.context_handler import ContextHandler
from src.parser.normalizer import ValueNormalizer

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Verifier")

def verify_logic(file_path):
    print(f"=== Verifying with file: {file_path} ===")
    
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return

    # 1. メタデータ抽出の検証
    print("\n--- Testing MetadataExtractor ---")
    metadata = MetadataExtractor.extract(file_path)
    print(f"Extracted Metadata: {metadata}")
    
    # 2. XBRLパースとLogic検証 (ContextHandler, ValueNormalizer)
    print("\n--- Testing ContextHandler & ValueNormalizer (Sample Tags) ---")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f, 'lxml-xml')

    # コンテキスト定義の辞書を作成 (id -> contextタグ)
    contexts = {}
    for context in soup.find_all('context'):
        contexts[context.get('id')] = context

    # いくつかのアカウントタグ（数値データ）をサンプリングして検証
    # jppfs_corの名前空間を持つタグ（財務諸表項目）を探す
    # 注意: 名前空間プレフィックスはファイルによって異なる場合があるが、EDINETでは通常 jppfs_cor
    tags = soup.find_all(lambda tag: tag.name.endswith('NetSales') or tag.name.endswith('ProfitLoss') or tag.name.endswith('Assets'))
    
    # 最初の5件だけチェック
    count = 0
    for tag in tags:
        if count >= 5: break
        
        context_id = tag.get('contextRef')
        unit_ref = tag.get('unitRef')
        decimals = tag.get('decimals')
        raw_value = tag.text.strip()
        
        # コンテキストIDの判定
        is_consolidated_current = ContextHandler.is_consolidated_current(context_id)
        period_type = ContextHandler.get_period_type(context_id)
        
        # 値の正規化
        normalized_val = ValueNormalizer.normalize(raw_value, decimals, unit_ref)
        
        print(f"Tag: {tag.name}")
        print(f"  Context ID: {context_id}")
        print(f"  -> Consolidated & Current?: {is_consolidated_current}")
        print(f"  -> Period Type: {period_type}")
        print(f"  Raw Value: {raw_value} (decimals={decimals}, unit={unit_ref})")
        print(f"  -> Normalized: {normalized_val}")
        print("-" * 30)
        
        count += 1

if __name__ == "__main__":
    # ワークスペース内に存在するサンプルファイルを指定
    target_file = "./xbrl_file/Xbrl_Search_20240821_152355/S100T45G/XBRL/PublicDoc/jpcrp030000-asr-001_E00990-000_2023-12-31_01_2024-03-26.xbrl"
    verify_logic(target_file)

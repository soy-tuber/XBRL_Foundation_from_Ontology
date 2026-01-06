import re
import os
from bs4 import BeautifulSoup
from typing import Optional, Dict

class MetadataExtractor:
    """
    XBRLファイル（またはそのパス）から企業の基本情報（メタデータ）を抽出するクラス。
    主に文書情報のContext（DEI）から証券コード、提出日、年度情報を取得する。
    """

    @staticmethod
    def extract(file_path: str) -> Dict[str, Optional[str]]:
        """
        XBRLファイルをパースし、メタデータを抽出する。

        Args:
            file_path (str): XBRLファイルのパス

        Returns:
            Dict[str, Optional[str]]: 以下のキーを持つ辞書
                - security_code: 証券コード (str)
                - filing_date: 提出日 (str, YYYY-MM-DD)
                - fiscal_year_end: 当事業年度終了日 (str, YYYY-MM-DD)
                - company_name: 会社名 (str, option)
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f, 'lxml-xml') # XMLパーサーを使用
        except Exception as e:
            # lxmlがない場合などのフォールバックやエラーログ
            print(f"Error parsing XML {file_path}: {e}")
            return MetadataExtractor._empty_result()

        result = MetadataExtractor._empty_result()

        # タグ名のパターン (名前空間プレフィックスが変わる可能性があるため部分一致で探すのが安全だが、
        # EDINETでは jpdei_cor: が一般的。BeautifulSoupのfindは名前空間付きタグを扱うのが少し面倒なので
        # name=re.compile(...) を使う)
        
        # 1. 証券コード (SecurityCodeDEI)
        # 例: <jpdei_cor:SecurityCodeDEI>49110</jpdei_cor:SecurityCodeDEI>
        sec_code_tag = soup.find(re.compile(r'.*:SecurityCodeDEI$'))
        if sec_code_tag and sec_code_tag.text:
            # 4桁のみ抽出（EDINETでは5桁目に0が入ることがあるが、ユーザーの要望に合わせてそのまま返すか4桁にするか。
            # 今回はそのまま返すが、必要ならスライスする）
            result['security_code'] = sec_code_tag.text.strip()[:4] # 通常4桁の証券コードが必要

        # 2. 提出日 (FilingDateDEI)
        # 例: <jpdei_cor:FilingDateDEI>2024-03-26</jpdei_cor:FilingDateDEI>
        filing_date_tag = soup.find(re.compile(r'.*:FilingDateDEI$'))
        if filing_date_tag and filing_date_tag.text:
            result['filing_date'] = filing_date_tag.text.strip()
        else:
            # タグから取れない場合、ファイル名からの推測を試みる
            # ファイル名形式: ..._YYYY-MM-DD.xbrl (末尾の日付が提出日であることが多い)
            filename = os.path.basename(file_path)
            # YYYY-MM-DD パターンを探す
            dates = re.findall(r'\d{4}-\d{2}-\d{2}', filename)
            if dates:
                # 通常、最後の日付が提出日 (その前が決算日など)
                result['filing_date'] = dates[-1]

        # 3. 当事業年度終了日 (CurrentFiscalYearEndDateDEI)
        # 例: <jpdei_cor:CurrentFiscalYearEndDateDEI>2023-12-31</jpdei_cor:CurrentFiscalYearEndDateDEI>
        fiscal_end_tag = soup.find(re.compile(r'.*:CurrentFiscalYearEndDateDEI$'))
        if fiscal_end_tag and fiscal_end_tag.text:
            result['fiscal_year_end'] = fiscal_end_tag.text.strip()
        
        # 4. 会社名 (FilerNameInJapaneseDEI) - オプション
        company_name_tag = soup.find(re.compile(r'.*:FilerNameInJapaneseDEI$'))
        if company_name_tag and company_name_tag.text:
            result['company_name'] = company_name_tag.text.strip()

        return result

    @staticmethod
    def _empty_result() -> Dict[str, Optional[str]]:
        return {
            'security_code': None,
            'filing_date': None,
            'fiscal_year_end': None,
            'company_name': None
        }

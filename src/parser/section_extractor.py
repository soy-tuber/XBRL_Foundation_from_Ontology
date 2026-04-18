"""
有報 XBRL から TextBlock セクションを抽出するモジュール。

既存の XbrlParser は TextBlock を意図的に除外している (数値+短文の一次DB用途)。
IR 支援用途では TextBlock の本文こそが主役なので、本モジュールで別途抽出する。

出力は Section テーブル相当のフラット dict リスト。
HTML 残骸を除去したクリーンテキストと、元タグ名 (診断用) を保持する。
"""

from __future__ import annotations

import html
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

_TAXONOMY_PATH_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "config",
    "section_taxonomy.json",
)


@dataclass
class SectionMapping:
    section_code: str
    section_name_ja: str
    section_name_en: str
    patterns: List[str]
    order: int


class TaxonomyMapper:
    """XBRL 要素名 → 正規化 section_code へのマッピング。世代揺れを吸収。"""

    def __init__(self, taxonomy_path: Optional[str] = None):
        path = taxonomy_path or _TAXONOMY_PATH_DEFAULT
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._mappings: List[SectionMapping] = [
            SectionMapping(
                section_code=m["section_code"],
                section_name_ja=m["section_name_ja"],
                section_name_en=m.get("section_name_en", ""),
                patterns=m["patterns"],
                order=m.get("order", 999),
            )
            for m in data["mappings"]
        ]

    def resolve(self, tag_name: str) -> Optional[SectionMapping]:
        local = tag_name.split(":")[-1] if ":" in tag_name else tag_name
        # 全候補を集めて最長パターンマッチを採用 (longer = more specific)
        best: Optional[SectionMapping] = None
        best_len = 0
        for m in self._mappings:
            for pat in m.patterns:
                if (local.endswith(pat) or pat in local) and len(pat) > best_len:
                    best = m
                    best_len = len(pat)
        return best

    def all_codes(self) -> List[str]:
        return [m.section_code for m in self._mappings]


# ---------- HTML クリーニング ----------

_RE_TAG_RESIDUE = re.compile(r"<[^>]+>")
_RE_MULTI_SPACE = re.compile(r"[ \t\u3000]+")
_RE_MULTI_NEWLINE = re.compile(r"\n{3,}")
_RE_PAGE_NUMBER = re.compile(r"^\s*[-ー]?\s*\d{1,4}\s*[-ー]?\s*$", re.MULTILINE)


def clean_textblock_html(raw: str) -> str:
    """
    TextBlock の中身は通常 iXBRL の HTML 断片。
    BeautifulSoup でテキスト化 → エンティティ復号 → ノイズ除去。
    """
    if not raw:
        return ""

    # 1. XHTML エンティティの保護のため先にデコード
    decoded = html.unescape(raw)

    # 2. BeautifulSoup で構造化 → テキストのみ抽出
    #    表は改行区切りで残す
    soup = BeautifulSoup(decoded, "lxml")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tr in soup.find_all("tr"):
        tr.append("\n")
    for td in soup.find_all(["td", "th"]):
        td.append("\t")

    text = soup.get_text(separator="\n")

    # 3. 二次クリーニング (万一のタグ残骸)
    text = _RE_TAG_RESIDUE.sub("", text)

    # 4. ページ番号らしき単独行の除去
    text = _RE_PAGE_NUMBER.sub("", text)

    # 5. 空白・改行の正規化
    lines = [_RE_MULTI_SPACE.sub(" ", ln).strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    text = "\n".join(lines)
    text = _RE_MULTI_NEWLINE.sub("\n\n", text)

    return text.strip()


# ---------- 本体 ----------

class SectionExtractor:
    """
    単一の .xbrl ファイルから TextBlock セクションを抽出する。

    使い方:
        extractor = SectionExtractor(taxonomy_mapper)
        sections = extractor.extract(xbrl_path, doc_id)
    """

    def __init__(self, mapper: Optional[TaxonomyMapper] = None):
        self.mapper = mapper or TaxonomyMapper()

    def extract(self, xbrl_path: str, doc_id: str) -> List[Dict[str, Any]]:
        if not os.path.exists(xbrl_path):
            raise FileNotFoundError(xbrl_path)

        with open(xbrl_path, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f, "lxml-xml")

        results: List[Dict[str, Any]] = []
        seen_codes: Dict[str, int] = {}

        for tag in soup.find_all(True):
            name = tag.name or ""
            if "TextBlock" not in name:
                continue

            mapping = self.mapper.resolve(name)
            if not mapping:
                # マッピング外の TextBlock は一旦 other として保持する
                # (精度向上のヒントになる)
                mapping = SectionMapping(
                    section_code="other",
                    section_name_ja="その他TextBlock",
                    section_name_en="Other TextBlock",
                    patterns=[],
                    order=900,
                )

            raw = tag.decode_contents() if tag.contents else (tag.text or "")
            cleaned = clean_textblock_html(raw)
            if not cleaned or len(cleaned) < 30:
                # 実質空の TextBlock はスキップ
                continue

            # 同一 section_code が複数出現する場合 (連結+単体等) は order に添え字を振る
            count = seen_codes.get(mapping.section_code, 0)
            seen_codes[mapping.section_code] = count + 1

            results.append({
                "doc_id": doc_id,
                "section_code": mapping.section_code,
                "section_name_ja": mapping.section_name_ja,
                "section_name_en": mapping.section_name_en,
                "section_order": mapping.order + count,
                "raw_tag_name": name,
                "content_text": cleaned,
                "char_count": len(cleaned),
            })

        results.sort(key=lambda r: r["section_order"])
        return results

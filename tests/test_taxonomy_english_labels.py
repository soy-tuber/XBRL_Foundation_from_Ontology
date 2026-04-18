"""
公式英語ラベルが taxonomy.json に定義され、SectionExtractor から渡ってくることを検証。
"""

from __future__ import annotations

from src.parser.section_extractor import TaxonomyMapper


def test_taxonomy_has_official_english_labels():
    m = TaxonomyMapper()
    expected = {
        "business_risks": "Business Risks",
        "mdna": "Management Analysis of Financial Position, Operating Results and Cash Flows",
        "corporate_governance": "Overview of Corporate Governance",
        "segment_information": "Segment Information",
    }
    for code, en in expected.items():
        # patterns の代表を逆引きして mapping を取得
        found = None
        for mp in m._mappings:
            if mp.section_code == code:
                found = mp
                break
        assert found is not None, f"{code} not in taxonomy"
        assert found.section_name_en == en, f"{code}: expected '{en}', got '{found.section_name_en}'"


if __name__ == "__main__":
    test_taxonomy_has_official_english_labels()
    print("OK")

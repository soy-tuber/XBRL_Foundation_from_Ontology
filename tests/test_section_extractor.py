"""
section_extractor の単体 smoke test。
"""

from __future__ import annotations

from src.parser.section_extractor import TaxonomyMapper, clean_textblock_html


def test_taxonomy_resolve():
    m = TaxonomyMapper()
    r = m.resolve("jpcrp_cor:BusinessRisksTextBlock")
    assert r is not None
    assert r.section_code == "business_risks"

    r2 = m.resolve("jpcrp_cor:MajorShareholdersTextBlock")
    assert r2 is not None and r2.section_code == "major_shareholders"


def test_clean_textblock_html():
    html = (
        "<p>見出し<br/>本文です。&nbsp;<b>強調</b></p>"
        "<table><tr><td>A</td><td>B</td></tr></table>"
    )
    c = clean_textblock_html(html)
    assert "見出し" in c
    assert "本文です" in c
    assert "<" not in c


if __name__ == "__main__":
    test_taxonomy_resolve()
    test_clean_textblock_html()
    print("OK")

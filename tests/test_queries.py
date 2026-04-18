from src.ir.queries import _build_match, _safe_fts_expression


def test_safe_fts_expression_quotes_tokens():
    assert _safe_fts_expression("same-store sales") == '"same-store" "sales"'
    # OR/AND は温存
    assert "OR" in _safe_fts_expression("既存店 OR same-store")


def test_build_match_auto_uses_all_cols():
    expr = _build_match("supply chain", "auto",
                        ["content_text", "content_text_en", "keywords_ja", "keywords_en"])
    assert expr.startswith("{content_text content_text_en keywords_ja keywords_en}")
    assert '"supply"' in expr
    assert '"chain"' in expr


def test_build_match_en_only():
    expr = _build_match("risk", "en",
                        ["content_text", "content_text_en", "keywords_ja", "keywords_en"])
    assert expr.startswith("{content_text_en keywords_en}")


if __name__ == "__main__":
    test_safe_fts_expression_quotes_tokens()
    test_build_match_auto_uses_all_cols()
    test_build_match_en_only()
    print("OK")

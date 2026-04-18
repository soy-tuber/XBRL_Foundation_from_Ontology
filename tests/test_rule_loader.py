from src.ir.rule_loader import compliance_rules_text, disclosure_events_text


def test_compliance_rules_text_nonempty():
    t = compliance_rules_text()
    assert "金商法166" in t or "kinshouho_166" in t


def test_disclosure_events_text_nonempty():
    t = disclosure_events_text()
    assert "決定事実" in t


if __name__ == "__main__":
    test_compliance_rules_text_nonempty()
    test_disclosure_events_text_nonempty()
    print("OK")

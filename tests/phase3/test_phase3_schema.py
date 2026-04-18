from __future__ import annotations

import os
import tempfile

from src.db.phase3_schema import init_phase3_schema


def test_init_phase3_idempotent():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "p3.db")
        init_phase3_schema(db)
        init_phase3_schema(db)


if __name__ == "__main__":
    test_init_phase3_idempotent()
    print("OK")

"""
Gemini CLI 呼び出し部の単体テスト。subprocess は mock で差し替え、
実際には CLI を起動しない。
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from src.ir import gemini_cli_backend as GCLI
from src.ir.llm_client import LlmClient, LlmConfig


class _FakeCompleted:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_run_gemini_cli_happy_path():
    with patch.object(GCLI.shutil, "which", return_value="/usr/local/bin/gemini"), \
         patch.object(GCLI.subprocess, "run",
                      return_value=_FakeCompleted(stdout="hello from gemini\n")) as run:
        out = GCLI.run_gemini_cli("test prompt", model="gemini-2.5-pro")
        assert out == "hello from gemini"
        args, kwargs = run.call_args
        cmd = args[0]
        assert cmd[0] == "/usr/local/bin/gemini"
        assert "-p" in cmd
        assert "--model" in cmd


def test_run_gemini_cli_prepends_context_files():
    with patch.object(GCLI.shutil, "which", return_value="/usr/local/bin/gemini"), \
         patch.object(GCLI.subprocess, "run",
                      return_value=_FakeCompleted(stdout="ok")) as run:
        GCLI.run_gemini_cli("ask this", context_files=["data/a.md", "data/b.md"])
        cmd = run.call_args[0][0]
        prompt_idx = cmd.index("-p") + 1
        prompt = cmd[prompt_idx]
        assert prompt.startswith("@data/a.md\n@data/b.md")
        assert "ask this" in prompt


def test_run_gemini_cli_raises_when_not_installed():
    with patch.object(GCLI.shutil, "which", return_value=None):
        with pytest.raises(GCLI.GeminiCliNotFound):
            GCLI.run_gemini_cli("hi")


def test_run_gemini_cli_raises_on_nonzero_exit():
    with patch.object(GCLI.shutil, "which", return_value="/usr/local/bin/gemini"), \
         patch.object(GCLI.subprocess, "run",
                      return_value=_FakeCompleted(returncode=2, stderr="auth error")):
        with pytest.raises(GCLI.GeminiCliError, match="auth error"):
            GCLI.run_gemini_cli("hi")


def test_llm_client_routes_to_cli_when_backend_is_gemini_cli():
    cfg = LlmConfig(backend="gemini_cli", model="gemini-2.5-pro",
                    api_key=None, endpoint=None)
    client = LlmClient(cfg)
    with patch("src.ir.gemini_cli_backend.run_gemini_cli",
               return_value="routed!") as rc:
        got = client.generate("sys", "user")
        assert got == "routed!"
        args, kwargs = rc.call_args
        prompt = args[0]
        assert "[SYSTEM]" in prompt and "[USER]" in prompt


if __name__ == "__main__":
    test_run_gemini_cli_happy_path()
    test_run_gemini_cli_prepends_context_files()
    test_run_gemini_cli_raises_when_not_installed()
    test_run_gemini_cli_raises_on_nonzero_exit()
    test_llm_client_routes_to_cli_when_backend_is_gemini_cli()
    print("OK")

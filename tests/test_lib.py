"""Tests for lib/__init__.py and shared utilities."""

import json
import os
import re
import sys
from unittest.mock import MagicMock, patch

os.environ.setdefault("SKILLKIT_HOME", os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.environ["SKILLKIT_HOME"])

from lib import _build_chain, _model_available, _resolve_budget, build_payload, call_model, resolve_model


def _clean_path(raw: str) -> str:
    raw = re.sub(r"^['`\s]+|['`\s]+$", "", raw)
    return re.sub(r':\d+(?:[-,]\d+)*', '', raw).rstrip(',;. ')


SAMPLE_CATALOG = {
    "config": {"mode": "low", "fallback_chain": ["medium", "high", "low"]},
    "providers": {
        "ollama": {"base_url": "http://localhost:11434/v1", "api_key": ""},
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "{env:DEEPSEEK_API_KEY}",
        },
    },
    "models": [
        {
            "id": "gemma4:26b",
            "provider": "ollama",
            "description": "General",
            "speed": "medium",
            "token_cost": 0,
        },
        {
            "id": "deepseek-r1:32b",
            "provider": "ollama",
            "description": "Deep reasoning",
            "speed": "slow",
            "token_cost": 0,
        },
        {
            "id": "deepseek-v4-flash",
            "provider": "deepseek",
            "description": "Fast",
            "speed": "fast",
            "token_cost": "low",
        },
    ],
    "skill_mapping": {
        "prespec": {
            "task": "Analysis",
            "low": "gemma4:26b",
            "medium": "deepseek-v4-flash",
            "high": "deepseek-v4-flash",
        },
        "pr-review": {
            "task": "PR review",
            "low": "deepseek-r1:32b",
            "medium": "deepseek-v4-flash",
            "high": "deepseek-v4-flash",
        },
    },
}


def clean_env():
    for var in [
        "SKILLKIT_MODEL",
        "SKILLKIT_PROVIDER",
        "SKILLKIT_API_URL",
        "SKILLKIT_API_KEY",
        "SKILLKIT_MODE",
        "TOKEN_BUDGET",
    ]:
        os.environ.pop(var, None)


# ── _resolve_budget ────────────────────────────────────────────


class TestResolveBudget:
    def test_default_low(self):
        clean_env()
        assert _resolve_budget(None) == "low"

    def test_env_var(self):
        clean_env()
        os.environ["TOKEN_BUDGET"] = "high"
        assert _resolve_budget(None) == "high"

    def test_explicit_budget(self):
        clean_env()
        assert _resolve_budget("medium") == "medium"

    def test_explicit_overrides_env(self):
        clean_env()
        os.environ["TOKEN_BUDGET"] = "high"
        assert _resolve_budget("low") == "low"


# ── _build_chain ───────────────────────────────────────────────


class TestBuildChain:
    def test_basic(self):
        entry = {"low": "m1", "medium": "m2", "high": "m3"}
        chain = _build_chain("low", entry, ["medium", "high", "low"])
        assert chain == [("low", "m1"), ("medium", "m2"), ("high", "m3")]

    def test_starts_with_budget(self):
        entry = {"low": "m1", "medium": "m2", "high": "m3"}
        chain = _build_chain("high", entry, ["medium", "low", "high"])
        assert chain[0] == ("high", "m3")

    def test_skips_duplicate(self):
        entry = {"low": "m1", "medium": "m2", "high": "m3"}
        chain = _build_chain("low", entry, ["low", "medium", "high"])
        assert chain == [("low", "m1"), ("medium", "m2"), ("high", "m3")]


# ── _model_available ──────────────────────────────────────────


class TestModelAvailable:
    @patch("lib._ollama_models_available", return_value=["gemma4:26b"])
    def test_ollama_available(self, _mock):
        info = {"provider": "ollama"}
        assert _model_available("gemma4:26b", info, SAMPLE_CATALOG, {})

    @patch("lib._ollama_models_available", return_value=["deepseek-r1:32b"])
    def test_ollama_not_available(self, _mock):
        info = {"provider": "ollama"}
        assert not _model_available("gemma4:26b", info, SAMPLE_CATALOG, {})

    def test_remote_no_key(self):
        clean_env()
        info = {"provider": "deepseek"}
        with patch("lib._resolve_api_key", return_value=""):
            assert not _model_available("deepseek-v4-flash", info, SAMPLE_CATALOG, {})

    def test_remote_with_key(self):
        clean_env()
        info = {"provider": "deepseek"}
        with patch("lib._resolve_api_key", return_value="sk-test"):
            assert _model_available("deepseek-v4-flash", info, SAMPLE_CATALOG, {})


# ── resolve_model ─────────────────────────────────────────────


class TestResolveModel:
    @patch("lib._model_available", return_value=True)
    def test_basic_resolve(self, _mock):
        clean_env()
        with patch("lib._load_models", return_value=SAMPLE_CATALOG):
            model = resolve_model("prespec", budget="low")
        assert model == "gemma4:26b"
        assert os.environ["SKILLKIT_MODEL"] == "gemma4:26b"
        assert os.environ["SKILLKIT_PROVIDER"] == "ollama"
        assert os.environ["SKILLKIT_MODE"] == "low"

    def test_unknown_skill(self):
        clean_env()
        os.environ["SKILLKIT_MODEL"] = "keep-model"
        with patch("lib._load_models", return_value=SAMPLE_CATALOG):
            model = resolve_model("nonexistent", budget="low")
        assert model == "keep-model"

    def test_invalid_budget(self):
        clean_env()
        os.environ["SKILLKIT_MODEL"] = "keep-model"
        model = resolve_model("prespec", budget="invalid")
        assert model == "keep-model"

    @patch("lib._model_available", side_effect=lambda m, i, c, u: m == "deepseek-v4-flash")
    def test_fallback(self, _mock):
        clean_env()
        with patch("lib._load_models", return_value=SAMPLE_CATALOG):
            model = resolve_model("prespec", budget="low")
        assert model == "deepseek-v4-flash"

    @patch("lib._model_available", return_value=False)
    def test_all_unavailable(self, _mock):
        clean_env()
        os.environ["SKILLKIT_MODEL"] = "fallback-model"
        with patch("lib._load_models", return_value=SAMPLE_CATALOG):
            model = resolve_model("prespec", budget="low")
        assert model == "fallback-model"

    def test_override_dict(self):
        clean_env()
        user_config = {
            "skill_model_overrides": {
                "prespec": {"low": "deepseek-r1:32b", "medium": "deepseek-v4-flash"}
            }
        }
        with patch("lib._load_models", return_value=SAMPLE_CATALOG), \
             patch("lib._load_user_config", return_value=user_config), \
             patch("lib._model_available", return_value=True):
            model = resolve_model("prespec", budget="low")
        assert model == "deepseek-r1:32b"

    def test_override_str(self):
        clean_env()
        user_config = {"skill_model_overrides": {"prespec": "deepseek-r1:32b"}}
        with patch("lib._load_models", return_value=SAMPLE_CATALOG), \
             patch("lib._load_user_config", return_value=user_config), \
             patch("lib._model_available", return_value=True):
            model = resolve_model("prespec", budget="low")
        assert model == "deepseek-r1:32b"

    def test_override_does_not_mutate_catalog(self):
        clean_env()
        user_config = {"skill_model_overrides": {"prespec": {"low": "deepseek-r1:32b"}}}
        with patch("lib._load_models", return_value=SAMPLE_CATALOG), \
             patch("lib._load_user_config", return_value=user_config), \
             patch("lib._model_available", return_value=True):
            resolve_model("prespec", budget="low")
        original_low = SAMPLE_CATALOG["skill_mapping"]["prespec"]["low"]
        assert original_low == "gemma4:26b", f"Catalog mutated to {original_low}"


# ── build_payload ─────────────────────────────────────────────


class TestBuildPayload:
    def _build(self, provider, model):
        clean_env()
        os.environ["SKILLKIT_PROVIDER"] = provider
        return build_payload(model, "SYS", "USR", num_predict=2048)

    def test_ollama_uses_options(self):
        p = self._build("ollama", "gemma4:26b")
        assert p["options"] == {"num_predict": 2048}
        assert "max_tokens" not in p

    def test_remote_reasoning_model_gets_larger_budget(self):
        p = self._build("opencode-go", "deepseek-v4-flash")
        assert p["max_tokens"] == 65536
        assert "options" not in p

    def test_remote_non_reasoning_model_keeps_caller_cap(self):
        p = self._build("opencode-go", "mimo-v2.5")
        assert p["max_tokens"] == 2048
        assert "options" not in p

    def test_kimi_gets_larger_budget(self):
        p = self._build("opencode-go", "kimi-k2.7-code")
        assert p["max_tokens"] == 65536
        assert "options" not in p

    def test_remote_json_response_format(self):
        clean_env()
        os.environ["SKILLKIT_PROVIDER"] = "opencode-go"
        p = build_payload("mimo-v2.5", "SYS", "USR", num_predict=2048, response_format="json")
        assert p["response_format"] == {"type": "json_object"}

    def test_ollama_json_format(self):
        clean_env()
        os.environ["SKILLKIT_PROVIDER"] = "ollama"
        p = build_payload("gemma4:26b", "SYS", "USR", num_predict=2048, response_format="json")
        assert p["format"] == "json"

    def test_no_response_format_by_default(self):
        clean_env()
        os.environ["SKILLKIT_PROVIDER"] = "opencode-go"
        p = build_payload("mimo-v2.5", "SYS", "USR")
        assert "response_format" not in p


# ── _clean_path ───────────────────────────────────────────────


class TestCleanPath:
    def test_strips_whitespace(self):
        assert _clean_path("  src/main.py  ") == "src/main.py"

    def test_strips_backticks(self):
        assert _clean_path("`src/main.py`") == "src/main.py"

    def test_strips_single_quotes(self):
        assert _clean_path("'src/main.py'") == "src/main.py"

    def test_removes_line_numbers(self):
        assert _clean_path("src/main.py:42") == "src/main.py"

    def test_removes_line_ranges(self):
        assert _clean_path("src/main.py:42-45") == "src/main.py"

    def test_removes_line_list(self):
        assert _clean_path("src/main.py:42,45-50") == "src/main.py"

    def test_removes_trailing_punctuation(self):
        assert _clean_path("src/main.py.") == "src/main.py"
        assert _clean_path("src/main.py;") == "src/main.py"

    def test_mixed_delimiters(self):
        assert _clean_path(" `'src/main.py:42'` ") == "src/main.py"

    def test_empty_string(self):
        assert _clean_path("") == ""

    def test_only_punctuation(self):
        assert _clean_path("''") == ""
        assert _clean_path("```") == ""


# ── call_model ─────────────────────────────────────────────────


class TestCallModel:
    @patch("lib.subprocess.run")
    def test_parses_content_and_usage(self, mock_run):
        clean_env()
        os.environ["SKILLKIT_PROVIDER"] = "opencode-go"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            }),
            stderr="",
        )
        result = call_model("mimo-v2.5", "SYS", "USR")
        assert result["content"] == "hello"
        assert result["usage"]["completion_tokens"] == 2
        assert result["error"] is None
        assert not result["truncated"]
        assert not result["empty"]

    @patch("lib.subprocess.run")
    def test_strips_thinking_tags(self, mock_run):
        clean_env()
        os.environ["SKILLKIT_PROVIDER"] = "opencode-go"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "choices": [{"message": {"content": "<think>reasoning</think>answer"}, "finish_reason": "stop"}],
            }),
            stderr="",
        )
        result = call_model("mimo-v2.5", "SYS", "USR")
        assert result["content"] == "answer"

    @patch("lib.subprocess.run")
    def test_detects_truncation(self, mock_run, capsys):
        clean_env()
        os.environ["SKILLKIT_PROVIDER"] = "opencode-go"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "choices": [{"message": {"content": "partial"}, "finish_reason": "length"}],
            }),
            stderr="",
        )
        result = call_model("mimo-v2.5", "SYS", "USR")
        assert result["truncated"]
        captured = capsys.readouterr()
        assert "truncated" in captured.err

    @patch("lib.subprocess.run")
    def test_detects_empty_content(self, mock_run, capsys):
        clean_env()
        os.environ["SKILLKIT_PROVIDER"] = "opencode-go"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "choices": [{"message": {"content": "   "}, "finish_reason": "stop"}],
            }),
            stderr="",
        )
        result = call_model("mimo-v2.5", "SYS", "USR")
        assert result["empty"]
        captured = capsys.readouterr()
        assert "empty" in captured.err

    @patch("lib.subprocess.run")
    def test_curl_error(self, mock_run):
        clean_env()
        os.environ["SKILLKIT_PROVIDER"] = "opencode-go"
        mock_run.return_value = MagicMock(returncode=7, stdout="", stderr="connection refused")
        result = call_model("mimo-v2.5", "SYS", "USR")
        assert result["error"] == "curl_error"
        assert result["content"].startswith("ERROR curl:")

    @patch("lib.subprocess.run")
    def test_api_error(self, mock_run):
        clean_env()
        os.environ["SKILLKIT_PROVIDER"] = "opencode-go"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"error": {"message": "bad request"}}),
            stderr="",
        )
        result = call_model("mimo-v2.5", "SYS", "USR")
        assert result["error"] == "api_error"
        assert "bad request" in result["content"]

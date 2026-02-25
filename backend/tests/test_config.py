"""
Tests for config.py — RAG mode persistence via config.json.
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestConfig:
    """Each test patches the config file path to an isolated tmp file."""

    def test_default_rag_mode_is_false(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            assert config.get_rag_mode() is False

    def test_set_rag_mode_true(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            config.set_rag_mode(True)
            assert config.get_rag_mode() is True

    def test_set_rag_mode_false(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            config.set_rag_mode(True)
            config.set_rag_mode(False)
            assert config.get_rag_mode() is False

    def test_config_file_written_on_set(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            config.set_rag_mode(True)
            assert cfg_file.exists()
            data = json.loads(cfg_file.read_text())
            assert data["rag_mode"] is True

    def test_persists_across_loads(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            config.set_rag_mode(True)
        # Re-read fresh
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            assert config.get_rag_mode() is True

    def test_corrupt_config_falls_back_to_default(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text("not valid json!!!}", encoding="utf-8")
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            assert config.get_rag_mode() is False

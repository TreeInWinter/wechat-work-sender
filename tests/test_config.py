# tests/test_config.py
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import config as cfg


class LoadConfigTests(unittest.TestCase):
    def test_returns_defaults_when_file_missing(self):
        with patch.object(cfg, "CONFIG_FILE", "/nonexistent/path/config.json"):
            result = cfg.load_config()
        self.assertFalse(result["kb_enabled"])
        self.assertEqual(result["kb_vault_path"], "")

    def test_loads_saved_values(self):
        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False, encoding="utf-8"
        ) as f:
            json.dump({"kb_enabled": True, "kb_vault_path": "/tmp/vault"}, f)
            fname = f.name
        try:
            with patch.object(cfg, "CONFIG_FILE", fname):
                result = cfg.load_config()
            self.assertTrue(result["kb_enabled"])
            self.assertEqual(result["kb_vault_path"], "/tmp/vault")
        finally:
            os.unlink(fname)

    def test_returns_defaults_on_corrupt_json(self):
        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write("not json {{{")
            fname = f.name
        try:
            with patch.object(cfg, "CONFIG_FILE", fname):
                result = cfg.load_config()
            self.assertFalse(result["kb_enabled"])
        finally:
            os.unlink(fname)

    def test_missing_keys_filled_with_defaults(self):
        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False, encoding="utf-8"
        ) as f:
            json.dump({"kb_enabled": True}, f)   # kb_vault_path missing
            fname = f.name
        try:
            with patch.object(cfg, "CONFIG_FILE", fname):
                result = cfg.load_config()
            self.assertEqual(result["kb_vault_path"], "")
        finally:
            os.unlink(fname)


class SaveConfigTests(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            fpath = os.path.join(d, "config.json")
            with patch.object(cfg, "CONFIG_FILE", fpath):
                cfg.save_config({"kb_enabled": True, "kb_vault_path": "/my/vault"})
                result = cfg.load_config()
            self.assertTrue(result["kb_enabled"])
            self.assertEqual(result["kb_vault_path"], "/my/vault")

    def test_partial_update_preserves_other_keys(self):
        with tempfile.TemporaryDirectory() as d:
            fpath = os.path.join(d, "config.json")
            with patch.object(cfg, "CONFIG_FILE", fpath):
                cfg.save_config({"kb_vault_path": "/v"})
                cfg.save_config({"kb_enabled": True})
                result = cfg.load_config()
            self.assertEqual(result["kb_vault_path"], "/v")
            self.assertTrue(result["kb_enabled"])

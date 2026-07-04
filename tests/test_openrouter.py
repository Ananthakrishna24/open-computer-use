from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from ocu.integrations import openai, openrouter


class FakeObservation:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeEnv:
    def __init__(self) -> None:
        self.calls = []

    def observe(self, mode="auto", region=None):
        self.calls.append(("observe", mode, region))
        return FakeObservation("observed")

    def act_batch(self, actions, guard="abort_on_unexpected_change"):
        self.calls.append(("act", actions, guard))
        return FakeObservation("acted")


class OpenRouterTests(unittest.TestCase):
    def test_model_table_shape(self) -> None:
        self.assertEqual(set(openrouter.MODELS), {"fast", "balanced", "capable"})
        for tier, models in openrouter.MODELS.items():
            self.assertTrue(models, tier)
            for model in models:
                self.assertRegex(model, r"^[a-z0-9-]+/[a-z0-9.-]+$")
        self.assertEqual(openrouter.DEFAULT_MODEL, "google/gemma-4-26b-a4b-it")
        self.assertEqual(openrouter.DEFAULT_MODEL, openrouter.MODELS["fast"][0])
        self.assertEqual(openrouter.ESCALATION_MODEL, "google/gemma-4-31b-it")

    def test_pick_model(self) -> None:
        self.assertEqual(openrouter.pick_model(), openrouter.DEFAULT_MODEL)
        self.assertEqual(openrouter.pick_model("balanced"), openrouter.MODELS["balanced"][0])
        with self.assertRaises(ValueError):
            openrouter.pick_model("galactic")

    def test_tools_and_dispatch_reuse_openai_wire_format(self) -> None:
        self.assertIs(openrouter.TOOLS, openai.FUNCTIONS)
        self.assertIs(openrouter.dispatch, openai.dispatch)
        env = FakeEnv()
        tool_call = {
            "function": {
                "name": "act",
                "arguments": json.dumps({"actions": [{"verb": "click", "target": 3}]}),
            }
        }
        self.assertEqual(openrouter.dispatch(env, tool_call), "acted")

    def test_create_client_requires_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch.object(openrouter, "_load_env", lambda: None):
            with self.assertRaises(RuntimeError):
                openrouter.create_client()

    def test_load_env_fills_missing_key_only(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("# comment\nOPENROUTER_API_KEY='sk-test'\nEMPTY=\n")
            with patch.dict(os.environ, {}, clear=True), patch.object(Path, "cwd", staticmethod(lambda: Path(tmp))):
                openrouter._load_env()
                self.assertEqual(os.environ.get("OPENROUTER_API_KEY"), "sk-test")
                self.assertNotIn("EMPTY", os.environ)


if __name__ == "__main__":
    unittest.main()

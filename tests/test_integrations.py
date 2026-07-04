from __future__ import annotations

import json
import unittest
from importlib.util import find_spec
from types import SimpleNamespace

from ocu.integrations import anthropic, openai


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


class IntegrationTests(unittest.TestCase):
    def test_anthropic_dispatch_observe(self) -> None:
        env = FakeEnv()
        result = anthropic.dispatch(env, {"name": "observe", "input": {"mode": "region", "region": [0, 0, 50, 50]}})
        self.assertEqual(result, "observed")
        self.assertEqual(env.calls, [("observe", "region", (0, 0, 50, 50))])

    def test_openai_dispatch_act(self) -> None:
        env = FakeEnv()
        tool_call = {
            "function": {
                "name": "act",
                "arguments": json.dumps({"actions": [{"verb": "click", "target": 1}], "guard": "none"}),
            }
        }
        result = openai.dispatch(env, tool_call)
        self.assertEqual(result, "acted")
        self.assertEqual(env.calls, [("act", [{"verb": "click", "target": 1}], "none")])

    def test_object_style_anthropic_block(self) -> None:
        env = FakeEnv()
        block = SimpleNamespace(name="act", input={"actions": [{"verb": "wait", "ms": 10}]})
        result = anthropic.dispatch(env, block)
        self.assertEqual(result, "acted")

    @unittest.skipIf(find_spec("mcp") is None, "mcp optional dependency is not installed")
    def test_mcp_server_can_be_created(self) -> None:
        from ocu.integrations.mcp_server import create_server

        server = create_server(FakeEnv())
        self.assertEqual(type(server).__name__, "FastMCP")


if __name__ == "__main__":
    unittest.main()

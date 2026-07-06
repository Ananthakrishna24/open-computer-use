from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ocu.env import _default_desktop_executor
from ocu.executors import XdotoolExecutor, YdotoolExecutor
from ocu.resolve import ResolvedTarget
from ocu.schema import Action


class FakeRunner:
    def __init__(self, returncode=0, stderr=""):
        self.commands = []
        self.returncode = returncode
        self.stderr = stderr

    def __call__(self, command):
        self.commands.append(command)
        return SimpleNamespace(returncode=self.returncode, stderr=self.stderr)


def resolved(action, coordinate=None):
    return ResolvedTarget(action=action, element=None, coordinate=coordinate)


class YdotoolExecutorTests(unittest.TestCase):
    def setUp(self):
        self.runner = FakeRunner()
        self.executor = YdotoolExecutor(runner=self.runner)

    def test_click(self):
        action = Action(verb="click", coordinate=(30, 40))
        self.executor.execute(action, resolved(action, (30, 40)))
        self.assertEqual(
            self.runner.commands,
            [
                ["ydotool", "mousemove", "-a", "-x", "30", "-y", "40"],
                ["ydotool", "click", "0xC0"],
            ],
        )

    def test_click_applies_scale(self):
        runner = FakeRunner()
        action = Action(verb="click", coordinate=(100, 50))
        YdotoolExecutor(runner=runner, scale=2.0).execute(action, resolved(action, (100, 50)))
        self.assertEqual(runner.commands[0], ["ydotool", "mousemove", "-a", "-x", "200", "-y", "100"])

    def test_type_clicks_selects_all_then_types(self):
        action = Action(verb="type", target=1, text="wireless mouse")
        self.executor.execute(action, resolved(action, (60, 74)))
        self.assertEqual(
            self.runner.commands,
            [
                ["ydotool", "mousemove", "-a", "-x", "60", "-y", "74"],
                ["ydotool", "click", "0xC0"],
                ["ydotool", "key", "29:1", "30:1", "30:0", "29:0"],
                ["ydotool", "type", "-d", "12", "--", "wireless mouse"],
            ],
        )

    def test_type_empty_text_clears_field(self):
        action = Action(verb="type", text="")
        self.executor.execute(action, resolved(action))
        self.assertEqual(
            self.runner.commands,
            [
                ["ydotool", "key", "29:1", "30:1", "30:0", "29:0"],
                ["ydotool", "key", "111:1", "111:0"],
            ],
        )

    def test_press_maps_key_names(self):
        cases = [
            ("Enter", ["28:1", "28:0"]),
            ("ArrowLeft", ["105:1", "105:0"]),
            ("Control+A", ["29:1", "30:1", "30:0", "29:0"]),
            ("F5", ["63:1", "63:0"]),
        ]
        for name, codes in cases:
            runner = FakeRunner()
            action = Action(verb="press", text=name)
            YdotoolExecutor(runner=runner).execute(action, resolved(action))
            self.assertEqual(runner.commands, [["ydotool", "key", *codes]])

    def test_press_unknown_key_raises(self):
        action = Action(verb="press", text="Hyper")
        with self.assertRaisesRegex(ValueError, "unknown key"):
            self.executor.execute(action, resolved(action))

    def test_scroll_down_default(self):
        action = Action(verb="scroll")
        self.executor.execute(action, resolved(action))
        self.assertEqual(
            self.runner.commands,
            [["ydotool", "mousemove", "-w", "-x", "0", "-y", "-4"]],
        )

    def test_scroll_up_at_coordinate(self):
        action = Action(verb="scroll", coordinate=(100, 200), metadata={"dy": -240})
        self.executor.execute(action, resolved(action, (100, 200)))
        self.assertEqual(
            self.runner.commands,
            [
                ["ydotool", "mousemove", "-a", "-x", "100", "-y", "200"],
                ["ydotool", "mousemove", "-w", "-x", "0", "-y", "2"],
            ],
        )

    def test_drag(self):
        action = Action(verb="drag", coordinate=(10, 10), metadata={"to": [50, 60]})
        self.executor.execute(action, resolved(action, (10, 10)))
        self.assertEqual(
            self.runner.commands,
            [
                ["ydotool", "mousemove", "-a", "-x", "10", "-y", "10"],
                ["ydotool", "click", "0x40"],
                ["ydotool", "mousemove", "-a", "-x", "50", "-y", "60"],
                ["ydotool", "click", "0x80"],
            ],
        )

    def test_missing_ydotool_raises_clear_error(self):
        def runner(command):
            raise FileNotFoundError(command[0])

        action = Action(verb="click", coordinate=(1, 2))
        with self.assertRaisesRegex(RuntimeError, "ydotool not found"):
            YdotoolExecutor(runner=runner).execute(action, resolved(action, (1, 2)))

    def test_nonzero_exit_raises_with_stderr(self):
        runner = FakeRunner(returncode=1, stderr="failed to open uinput")
        action = Action(verb="click", coordinate=(1, 2))
        with self.assertRaisesRegex(RuntimeError, "failed to open uinput"):
            YdotoolExecutor(runner=runner).execute(action, resolved(action, (1, 2)))


class DesktopExecutorPickTests(unittest.TestCase):
    def test_wayland_session_picks_ydotool(self):
        with patch.dict("os.environ", {"WAYLAND_DISPLAY": "wayland-0"}):
            self.assertIsInstance(_default_desktop_executor(), YdotoolExecutor)

    def test_x11_session_picks_xdotool(self):
        with patch.dict("os.environ", {"DISPLAY": ":0"}, clear=True):
            self.assertIsInstance(_default_desktop_executor(), XdotoolExecutor)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from types import SimpleNamespace

from ocu.executors import XdotoolExecutor
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


class XdotoolExecutorTests(unittest.TestCase):
    def setUp(self):
        self.runner = FakeRunner()
        self.executor = XdotoolExecutor(runner=self.runner)

    def test_click(self):
        action = Action(verb="click", coordinate=(30, 40))
        self.executor.execute(action, resolved(action, (30, 40)))
        self.assertEqual(
            self.runner.commands,
            [["xdotool", "mousemove", "--sync", "30", "40", "click", "1"]],
        )

    def test_type_clicks_selects_all_then_types(self):
        action = Action(verb="type", target=1, text="wireless mouse")
        self.executor.execute(action, resolved(action, (60, 74)))
        self.assertEqual(
            self.runner.commands,
            [
                ["xdotool", "mousemove", "--sync", "60", "74", "click", "1"],
                ["xdotool", "key", "--clearmodifiers", "ctrl+a"],
                ["xdotool", "type", "--clearmodifiers", "--delay", "12", "--", "wireless mouse"],
            ],
        )

    def test_type_empty_text_clears_field(self):
        action = Action(verb="type", text="")
        self.executor.execute(action, resolved(action))
        self.assertEqual(
            self.runner.commands,
            [
                ["xdotool", "key", "--clearmodifiers", "ctrl+a"],
                ["xdotool", "key", "--clearmodifiers", "Delete"],
            ],
        )

    def test_press_maps_key_names(self):
        for name, keysym in [("Enter", "Return"), ("ArrowLeft", "Left"), ("Control+A", "ctrl+A"), ("F5", "F5")]:
            runner = FakeRunner()
            action = Action(verb="press", text=name)
            XdotoolExecutor(runner=runner).execute(action, resolved(action))
            self.assertEqual(runner.commands, [["xdotool", "key", "--clearmodifiers", keysym]])

    def test_press_without_key_raises(self):
        action = Action(verb="press")
        with self.assertRaises(ValueError):
            self.executor.execute(action, resolved(action))

    def test_scroll_down_default(self):
        action = Action(verb="scroll")
        self.executor.execute(action, resolved(action))
        self.assertEqual(self.runner.commands, [["xdotool", "click", "--repeat", "4", "5"]])

    def test_scroll_up_at_coordinate(self):
        action = Action(verb="scroll", coordinate=(100, 200), metadata={"dy": -240})
        self.executor.execute(action, resolved(action, (100, 200)))
        self.assertEqual(
            self.runner.commands,
            [
                ["xdotool", "mousemove", "--sync", "100", "200"],
                ["xdotool", "click", "--repeat", "2", "4"],
            ],
        )

    def test_drag(self):
        action = Action(verb="drag", coordinate=(10, 10), metadata={"to": [50, 60]})
        self.executor.execute(action, resolved(action, (10, 10)))
        self.assertEqual(
            self.runner.commands,
            [[
                "xdotool", "mousemove", "--sync", "10", "10",
                "mousedown", "1",
                "mousemove", "--sync", "50", "60",
                "mouseup", "1",
            ]],
        )

    def test_drag_without_end_raises(self):
        action = Action(verb="drag", coordinate=(10, 10))
        with self.assertRaises(ValueError):
            self.executor.execute(action, resolved(action, (10, 10)))

    def test_wait_does_not_shell_out(self):
        action = Action(verb="wait", metadata={"ms": 0})
        self.executor.execute(action, resolved(action))
        self.assertEqual(self.runner.commands, [])

    def test_missing_xdotool_raises_clear_error(self):
        def runner(command):
            raise FileNotFoundError(command[0])

        action = Action(verb="click", coordinate=(1, 2))
        with self.assertRaisesRegex(RuntimeError, "xdotool not found"):
            XdotoolExecutor(runner=runner).execute(action, resolved(action, (1, 2)))

    def test_nonzero_exit_raises_with_stderr(self):
        runner = FakeRunner(returncode=1, stderr="cannot open display")
        action = Action(verb="click", coordinate=(1, 2))
        with self.assertRaisesRegex(RuntimeError, "cannot open display"):
            XdotoolExecutor(runner=runner).execute(action, resolved(action, (1, 2)))


if __name__ == "__main__":
    unittest.main()

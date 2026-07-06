from __future__ import annotations

import unittest

from ocu import Desktop, Element
from ocu.sensors.base import SensorFrame


class FakeSensor:
    def __init__(self, frames):
        self.frames = list(frames)
        self.captures = 0

    def capture(self, region=None):
        self.captures += 1
        if len(self.frames) > 1:
            return self.frames.pop(0)
        return self.frames[0]

    def screenshot(self, region=None):
        return b"png"


class FakeExecutor:
    def __init__(self):
        self.calls = []

    def execute(self, action, target):
        self.calls.append((action.verb, target.coordinate, action.text))


def button(text, bbox=(10, 20, 100, 32), path="ax>app[1]>frame[1]>button[1]"):
    return Element(
        0, "button", text, bbox, "ax",
        {"visible": True, "interactive": True, "structural_path": path},
    )


def label(text, bbox=(10, 80, 160, 20), path="ax>app[1]>frame[1]>label[1]"):
    return Element(0, "text", text, bbox, "ax", {"visible": True, "structural_path": path})


class DesktopFacadeTests(unittest.TestCase):
    def test_observe_then_act_returns_delta(self):
        sensor = FakeSensor(
            [
                SensorFrame(elements=[button("Save")]),
                SensorFrame(elements=[button("Save"), label("Saved")]),
            ]
        )
        executor = FakeExecutor()
        env = Desktop(sensor=sensor, executor=executor, settle_ms=0, change_threshold=1.0)
        first = env.observe()
        second = env.act("click", target=1)
        self.assertEqual(first.kind, "key")
        self.assertEqual(second.kind, "delta")
        self.assertIn("did: click [1] -> ok", second.text)
        self.assertIn("Saved", second.text)
        self.assertEqual(executor.calls, [("click", (60, 36), None)])

    def test_batch_aborts_when_next_target_disappears(self):
        two = [button("Save"), button("Quit", (10, 60, 80, 30), "ax>app[1]>frame[1]>button[2]")]
        sensor = FakeSensor(
            [
                SensorFrame(elements=two),
                SensorFrame(elements=[button("Save")]),
                SensorFrame(elements=[button("Save")]),
            ]
        )
        executor = FakeExecutor()
        env = Desktop(sensor=sensor, executor=executor, settle_ms=0, change_threshold=1.0)
        env.observe()
        result = env.act_batch([{"verb": "click", "target": 1}, {"verb": "click", "target": 2}])
        self.assertIn("aborted at step 2", result.text)
        self.assertIn("target [2] disappeared", result.text)
        self.assertEqual([call[0] for call in executor.calls], ["click"])

    def test_batch_uses_relocated_coordinate(self):
        moved = button("Quit", (10, 200, 80, 30), "ax>app[1]>frame[1]>button[2]")
        sensor = FakeSensor(
            [
                SensorFrame(elements=[button("Save"), button("Quit", (10, 60, 80, 30), "ax>app[1]>frame[1]>button[2]")]),
                SensorFrame(elements=[button("Save"), moved]),
                SensorFrame(elements=[button("Save"), moved]),
            ]
        )
        executor = FakeExecutor()
        env = Desktop(sensor=sensor, executor=executor, settle_ms=0, change_threshold=1.0)
        env.observe()
        result = env.act_batch([{"verb": "click", "target": 1}, {"verb": "click", "target": 2}])
        self.assertIn("did: click [1]; click [2] -> ok", result.text)
        self.assertEqual(executor.calls[-1][1], (50, 215))

    def test_screenshot_delegates_to_sensor(self):
        env = Desktop(
            sensor=FakeSensor([SensorFrame(elements=[button("Save")])]),
            executor=FakeExecutor(),
            settle_ms=0,
        )
        self.assertEqual(env.screenshot(), b"png")


if __name__ == "__main__":
    unittest.main()

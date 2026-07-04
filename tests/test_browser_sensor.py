from __future__ import annotations

import unittest

from ocu.sensors.browser_cdp import BrowserSensor, merge_dom_and_ax
from ocu import Element


class FakeAccessibility:
    def __init__(self, snapshot):
        self.snapshot_payload = snapshot

    def snapshot(self, interesting_only=True):
        return self.snapshot_payload


class FakePage:
    def __init__(self, dom_payload, ax_payload=None):
        self.dom_payload = dom_payload
        if ax_payload is not None:
            self.accessibility = FakeAccessibility(ax_payload)

    def evaluate(self, script, region):
        return self.dom_payload

    def screenshot(self, **kwargs):
        return b"png"


class BrowserSensorTests(unittest.TestCase):
    def test_ax_snapshot_augments_matching_dom_element(self) -> None:
        sensor = BrowserSensor(
            FakePage(
                {
                    "url": "https://example.test",
                    "viewport_size": [800, 600],
                    "device_scale_factor": 1,
                    "elements": [
                        {
                            "role": "button",
                            "text": "Submit",
                            "bbox": [10, 20, 100, 32],
                            "source": "dom",
                            "state": {"visible": True, "interactive": True, "structural_path": "button"},
                        }
                    ],
                },
                {
                    "role": "WebArea",
                    "name": "",
                    "children": [
                        {
                            "role": "button",
                            "name": "Submit",
                            "disabled": True,
                            "bbox": [12, 21, 100, 32],
                        }
                    ],
                },
            )
        )
        frame = sensor.capture()
        self.assertEqual(len(frame.elements), 1)
        element = frame.elements[0]
        self.assertEqual(element.source, "dom")
        self.assertTrue(element.state["disabled"])
        self.assertEqual(element.state["ax_role"], "button")
        self.assertEqual(element.state["ax_name"], "Submit")

    def test_ax_only_element_with_bounds_is_kept(self) -> None:
        merged = merge_dom_and_ax(
            [],
            [Element(0, "button", "AX only", (5, 5, 80, 24), "ax", {"visible": True, "interactive": True})],
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].source, "ax")

    def test_ax_only_element_without_bounds_is_not_exposed(self) -> None:
        merged = merge_dom_and_ax(
            [],
            [Element(0, "button", "No bounds", (0, 0, 0, 0), "ax", {"visible": True, "interactive": True})],
        )
        self.assertEqual(merged, [])


if __name__ == "__main__":
    unittest.main()

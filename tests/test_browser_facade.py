from __future__ import annotations

import unittest

from ocu import Browser


class FakeClient:
    def __init__(self) -> None:
        self.events = []

    def send(self, method, payload):
        self.events.append((method, payload))


class FakeContext:
    def __init__(self, client: FakeClient) -> None:
        self.client = client

    def new_cdp_session(self, page):
        return self.client


class FakePage:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.client = FakeClient()
        self.context = FakeContext(self.client)
        self.keyboard = self
        self.mouse = self

    def evaluate(self, script, region):
        if not self.payloads:
            raise AssertionError("no fake payloads left")
        return self.payloads.pop(0)

    def screenshot(self, **kwargs):
        return b"png"

    def insert_text(self, text):
        self.client.events.append(("keyboard.insert_text", {"text": text}))

    def press(self, key):
        self.client.events.append(("keyboard.press", {"key": key}))

    def click(self, x, y):
        self.client.events.append(("mouse.click", {"x": x, "y": y}))

    def move(self, x, y):
        self.client.events.append(("mouse.move", {"x": x, "y": y}))

    def wheel(self, dx, dy):
        self.client.events.append(("mouse.wheel", {"dx": dx, "dy": dy}))

    def wait_for_timeout(self, milliseconds):
        self.client.events.append(("wait", {"ms": milliseconds}))


def payload(elements):
    return {
        "url": "https://shop.test/cart",
        "viewport_size": [800, 600],
        "device_scale_factor": 1,
        "elements": elements,
    }


class BrowserFacadeTests(unittest.TestCase):
    def test_observe_then_act_returns_delta(self) -> None:
        page = FakePage(
            [
                payload(
                    [
                        {
                            "role": "button",
                            "text": "Add to cart",
                            "bbox": [10, 20, 100, 40],
                            "source": "dom",
                            "state": {"visible": True, "interactive": True, "structural_path": "button:nth-of-type(1)"},
                        }
                    ]
                ),
                payload(
                    [
                        {
                            "role": "button",
                            "text": "Add to cart",
                            "bbox": [10, 20, 100, 40],
                            "source": "dom",
                            "state": {"visible": True, "interactive": True, "structural_path": "button:nth-of-type(1)"},
                        },
                        {
                            "role": "text",
                            "text": "Added to cart",
                            "bbox": [10, 80, 160, 24],
                            "source": "dom",
                            "state": {"visible": True, "structural_path": "p:nth-of-type(1)"},
                        },
                    ]
                ),
            ]
        )
        env = Browser(page=page, max_obs_tokens=1500, change_threshold=1.0)
        first = env.observe()
        second = env.act("click", target=1)
        self.assertEqual(first.kind, "key")
        self.assertEqual(second.kind, "delta")
        self.assertIn("did: click [1] -> ok", second.text)
        self.assertIn("Added to cart", second.text)
        self.assertEqual(page.client.events[0][0], "Input.dispatchMouseEvent")


if __name__ == "__main__":
    unittest.main()

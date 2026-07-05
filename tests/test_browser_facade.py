from __future__ import annotations

import unittest

from ocu import Browser
from ocu.env import BLOCKED_URL_PATTERNS, PROBE_SCRIPT, TEXT_SCRIPT
from ocu.executors.cdp import FOCUS_SCRIPT, SELECT_ALL_SCRIPT


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
    def __init__(self, payloads, probes=None):
        self.payloads = list(payloads)
        self.probes = list(probes or [])
        self.probe_calls = []
        self.settle_calls = 0
        self.snapshot_calls = 0
        self.client = FakeClient()
        self.context = FakeContext(self.client)
        self.keyboard = self
        self.mouse = self

    def evaluate(self, script, arg=None):
        if script is TEXT_SCRIPT:
            return "Latest release:\n  Python 3.99.0"
        if script is FOCUS_SCRIPT:
            return True
        if script is SELECT_ALL_SCRIPT:
            self.client.events.append(("select_all", {}))
            return True
        if script is PROBE_SCRIPT:
            self.probe_calls.append(arg)
            if self.probes:
                return self.probes.pop(0)
            return {"url": "https://shop.test/cart", "dialogs": 0, "rect": None}
        self.snapshot_calls += 1
        if arg and arg.get("settle"):
            self.settle_calls += 1
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

    def goto(self, url, wait_until=None):
        self.client.events.append(("goto", {"url": url}))

    def go_back(self, wait_until=None):
        self.client.events.append(("back", {}))


def payload(elements, url="https://shop.test/cart"):
    return {
        "url": url,
        "viewport_size": [800, 600],
        "device_scale_factor": 1,
        "elements": elements,
    }


def button(text="Add to cart", path="button:nth-of-type(1)", bbox=(10, 20, 100, 40)):
    return {
        "role": "button",
        "text": text,
        "bbox": list(bbox),
        "source": "dom",
        "state": {"visible": True, "interactive": True, "structural_path": path},
    }


class BrowserFacadeTests(unittest.TestCase):
    def test_observe_then_act_returns_delta(self) -> None:
        page = FakePage(
            [
                payload([button()]),
                payload(
                    [
                        button(),
                        {
                            "role": "text",
                            "text": "Added to cart",
                            "bbox": [10, 80, 160, 24],
                            "source": "dom",
                            "state": {"visible": True, "structural_path": "p:nth-of-type(1)"},
                        },
                    ]
                ),
            ],
            probes=[{"url": "https://shop.test/cart", "dialogs": 0, "rect": [10, 20, 100, 40]}],
        )
        env = Browser(page=page, max_obs_tokens=1500, change_threshold=1.0, block_resources=False)
        first = env.observe()
        second = env.act("click", target=1)
        self.assertEqual(first.kind, "key")
        self.assertEqual(second.kind, "delta")
        self.assertIn("did: click [1] -> ok", second.text)
        self.assertIn("Added to cart", second.text)
        self.assertEqual(page.client.events[0][0], "Input.dispatchMouseEvent")
        self.assertEqual(page.settle_calls, 1)

    def test_batch_captures_once_and_uses_fresh_probe_rect(self) -> None:
        search = {
            "role": "input",
            "text": "Search",
            "bbox": [10, 10, 200, 30],
            "source": "dom",
            "state": {"visible": True, "interactive": True, "structural_path": "input:nth-of-type(1)"},
        }
        page = FakePage(
            [payload([search, button("Go", "button:nth-of-type(1)", (220, 10, 60, 30))]), payload([search])],
            probes=[
                {"url": "https://shop.test/cart", "dialogs": 0, "rect": None},
                {"url": "https://shop.test/cart", "dialogs": 0, "rect": [10, 10, 200, 30]},
                {"url": "https://shop.test/cart", "dialogs": 0, "rect": [300, 10, 60, 30]},
            ],
        )
        env = Browser(page=page, max_obs_tokens=1500, change_threshold=1.0)
        env.observe()
        result = env.act_batch(
            [
                {"verb": "type", "target": 1, "text": "wireless mouse"},
                {"verb": "click", "target": 2},
            ]
        )
        self.assertEqual(page.snapshot_calls, 2)
        self.assertIn("did: type [1] 'wireless mouse'; click [2] -> ok", result.text)
        presses = [event for event in page.client.events if event[1].get("type") == "mousePressed"]
        self.assertEqual(presses[-1][1]["x"], 330)
        self.assertEqual(presses[-1][1]["y"], 25)

    def test_batch_aborts_when_next_target_disappears(self) -> None:
        page = FakePage(
            [
                payload([button(), button("Checkout", "button:nth-of-type(2)", (10, 80, 100, 40))]),
                payload([button()]),
                payload([button()]),
            ],
            probes=[
                {"url": "https://shop.test/cart", "dialogs": 0, "rect": None},
                {"url": "https://shop.test/cart", "dialogs": 0, "rect": [10, 20, 100, 40]},
                {"url": "https://shop.test/cart", "dialogs": 0, "rect": None},
            ],
        )
        env = Browser(page=page, max_obs_tokens=1500, change_threshold=1.0)
        env.observe()
        result = env.act_batch(
            [
                {"verb": "click", "target": 1},
                {"verb": "click", "target": 2},
            ]
        )
        self.assertIn("aborted at step 2", result.text)
        self.assertIn("target [2] disappeared", result.text)
        self.assertEqual(page.snapshot_calls, 3)

    def test_batch_relocates_target_after_dom_shift(self) -> None:
        moved = button("Checkout", "div:nth-of-type(2)>button:nth-of-type(1)", (10, 200, 100, 40))
        page = FakePage(
            [
                payload([button(), button("Checkout", "button:nth-of-type(2)", (10, 80, 100, 40))]),
                payload([button(), moved]),
                payload([button(), moved]),
            ],
            probes=[
                {"url": "https://shop.test/cart", "dialogs": 0, "rect": None},
                {"url": "https://shop.test/cart", "dialogs": 0, "rect": [10, 20, 100, 40]},
                {"url": "https://shop.test/cart", "dialogs": 0, "rect": None},
            ],
        )
        env = Browser(page=page, max_obs_tokens=1500, change_threshold=1.0)
        env.observe()
        result = env.act_batch(
            [
                {"verb": "click", "target": 1},
                {"verb": "click", "target": 2},
            ]
        )
        self.assertIn("did: click [1]; click [2] -> ok", result.text)
        presses = [event for event in page.client.events if event[1].get("type") == "mousePressed"]
        self.assertEqual(presses[-1][1]["x"], 60)
        self.assertEqual(presses[-1][1]["y"], 220)

    def test_batch_aborts_when_dialog_appears(self) -> None:
        page = FakePage(
            [payload([button(), button("Checkout", "button:nth-of-type(2)", (10, 80, 100, 40))]), payload([button()])],
            probes=[
                {"url": "https://shop.test/cart", "dialogs": 0, "rect": None},
                {"url": "https://shop.test/cart", "dialogs": 0, "rect": [10, 20, 100, 40]},
                {"url": "https://shop.test/cart", "dialogs": 1, "rect": [10, 80, 100, 40]},
            ],
        )
        env = Browser(page=page, max_obs_tokens=1500, change_threshold=1.0)
        env.observe()
        result = env.act_batch(
            [
                {"verb": "click", "target": 1},
                {"verb": "click", "target": 2},
            ]
        )
        self.assertIn("aborted at step 2", result.text)
        self.assertIn("dialog_or_alert_appeared", result.text)

    def test_guard_none_skips_probes_for_untargeted_steps(self) -> None:
        page = FakePage(
            [payload([button()]), payload([button()])],
            probes=[{"url": "https://shop.test/cart", "dialogs": 0, "rect": [10, 20, 100, 40]}],
        )
        env = Browser(page=page, max_obs_tokens=1500, change_threshold=1.0)
        env.observe()
        env.act_batch(
            [
                {"verb": "click", "target": 1},
                {"verb": "press", "text": "Enter"},
            ],
            guard="none",
        )
        self.assertEqual(page.probe_calls, [{"path": "button:nth-of-type(1)"}])
        self.assertEqual(page.snapshot_calls, 2)

    def test_goto_navigates_and_prefixes_scheme(self) -> None:
        page = FakePage([payload([button()]), payload([button()], url="https://other.test/")])
        env = Browser(page=page, max_obs_tokens=1500, block_resources=False)
        env.observe()
        result = env.act("goto", text="other.test")
        self.assertIn(("goto", {"url": "https://other.test"}), page.client.events)
        self.assertIn("url: https://other.test/", result.text)
        self.assertIn("url_changed", result.text)

    def test_observe_text_returns_page_text_without_new_frame(self) -> None:
        page = FakePage([payload([button()])])
        env = Browser(page=page, max_obs_tokens=1500, block_resources=False)
        env.observe()
        result = env.observe(mode="text")
        self.assertIn("## page text", result.text)
        self.assertIn("Latest release: Python 3.99.0", result.text)
        self.assertEqual(result.frame, 1)
        self.assertEqual(page.snapshot_calls, 1)

    def test_resource_blocking_enabled_by_default(self) -> None:
        page = FakePage([payload([button()])])
        Browser(page=page, max_obs_tokens=1500)
        self.assertEqual(page.client.events[0], ("Network.enable", {}))
        self.assertEqual(page.client.events[1], ("Network.setBlockedURLs", {"urls": BLOCKED_URL_PATTERNS}))


if __name__ == "__main__":
    unittest.main()

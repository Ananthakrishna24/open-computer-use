from __future__ import annotations

import unittest

from ocu import Element, StateStore
from ocu.serialize import estimate_tokens, observation_from_update


class SerializerTests(unittest.TestCase):
    def test_keyframe_text_contains_header_and_elements(self) -> None:
        store = StateStore()
        update = store.ingest([Element(0, "button", "Checkout", (10, 10, 100, 30), "dom")])
        obs = observation_from_update(update, max_tokens=1500)
        self.assertIn("## screen (frame 1, full)", obs.text)
        self.assertIn('[1]  button', obs.text)
        self.assertLessEqual(obs.tokens, 1500)

    def test_delta_text_contains_action_feedback(self) -> None:
        store = StateStore(change_threshold=1.0)
        store.ingest([Element(0, "button", "Checkout", (10, 10, 100, 30), "dom", {"disabled": True})])
        update = store.ingest(
            [Element(0, "button", "Checkout", (10, 10, 100, 30), "dom", {"disabled": False})],
            last_action="click [1]",
        )
        obs = observation_from_update(update, max_tokens=1500)
        self.assertIn("did: click [1] -> ok", obs.text)
        self.assertIn("now enabled", obs.text)
        self.assertIn("unchanged:", obs.text)

    def test_delta_reports_value_change_with_stable_id(self) -> None:
        store = StateStore(change_threshold=1.0)
        state = {"interactive": True, "visible": True, "structural_path": "input:nth-of-type(1)", "value": ""}
        store.ingest([Element(0, "input", "Search products", (10, 10, 200, 30), "dom", state)])
        update = store.ingest(
            [Element(0, "input", "Search products", (10, 10, 200, 30), "dom", {**state, "value": "wireless mouse"})],
            last_action="type [1] 'wireless mouse'",
        )
        obs = observation_from_update(update, max_tokens=1500)
        self.assertIn('~ [1]  input', obs.text)
        self.assertIn('value now "wireless mouse"', obs.text)
        self.assertNotIn("- [1]", obs.text)

    def test_budget_is_enforced_with_explicit_omission(self) -> None:
        store = StateStore()
        elements = [
            Element(0, "button", f"Long visible button label number {index}", (0, index * 10, 200, 20), "dom")
            for index in range(30)
        ]
        update = store.ingest(elements)
        obs = observation_from_update(update, max_tokens=45)
        self.assertLessEqual(obs.tokens, 45)
        self.assertIn("omitted", obs.text)
        self.assertLessEqual(estimate_tokens(obs.text), 45)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import unittest
from pathlib import Path

from ocu import Element, StateStore

FIXTURES = Path(__file__).parent / "fixtures"


def load_frame(name: str) -> list[Element]:
    data = json.loads((FIXTURES / name).read_text())
    return [Element(**item) for item in data]


class StateStoreTests(unittest.TestCase):
    def test_first_ingest_is_keyframe_and_assigns_ids(self) -> None:
        store = StateStore()
        update = store.ingest(load_frame("cart_frame_1.json"), url="https://shop.test/cart")
        self.assertEqual(update.kind, "key")
        self.assertEqual(update.reason, "first_observation")
        self.assertEqual(sorted(update.elements), [1, 2, 3, 4, 5, 6])

    def test_ids_are_stable_across_small_layout_shift(self) -> None:
        store = StateStore(change_threshold=1.0)
        first = store.ingest(load_frame("cart_frame_1.json"))
        second = store.ingest(load_frame("cart_frame_2.json"))
        first_by_text = {(element.role, element.text): element.id for element in first.elements.values()}
        second_by_text = {(element.role, element.text): element.id for element in second.elements.values()}
        self.assertEqual(first_by_text[("button", "Checkout")], second_by_text[("button", "Checkout")])
        self.assertEqual(first_by_text[("button", "Add to cart")], second_by_text[("button", "Add to cart")])

    def test_delta_reports_added_removed_and_changed(self) -> None:
        store = StateStore(change_threshold=1.0)
        store.ingest(load_frame("cart_frame_1.json"))
        update = store.ingest(load_frame("cart_frame_2.json"), last_action="click [4]")
        self.assertEqual(update.kind, "delta")
        added_text = {element.text for element in update.diff.added}
        removed_text = {element.text for element in update.diff.removed}
        changed_text = {new.text for _, new in update.diff.changed}
        self.assertIn("Added to cart", added_text)
        self.assertIn("Your cart is empty", removed_text)
        self.assertIn("Checkout", changed_text)

    def test_tiny_bbox_shift_does_not_create_noise(self) -> None:
        store = StateStore(change_threshold=1.0)
        store.ingest([Element(0, "button", "Checkout", (10, 10, 100, 30), "dom")])
        update = store.ingest([Element(0, "button", "Checkout", (12, 11, 100, 30), "dom")])
        self.assertEqual(update.diff.changed_count, 0)

    def test_interval_forces_keyframe(self) -> None:
        store = StateStore(keyframe_interval=2, change_threshold=1.0)
        store.ingest(load_frame("cart_frame_1.json"))
        update = store.ingest(load_frame("cart_frame_1.json"))
        self.assertEqual(update.kind, "key")
        self.assertEqual(update.reason, "interval")

    def test_small_local_change_stays_delta(self) -> None:
        store = StateStore(change_threshold=0.4)
        store.ingest(
            [
                Element(0, "button", "Add to cart", (0, 0, 100, 30), "dom"),
                Element(0, "button", "Checkout", (0, 40, 100, 30), "dom", {"disabled": True}),
                Element(0, "text", "Your cart is empty", (0, 80, 160, 24), "dom"),
            ]
        )
        update = store.ingest(
            [
                Element(0, "button", "Add to cart", (0, 0, 100, 30), "dom"),
                Element(0, "button", "Checkout", (0, 40, 100, 30), "dom", {"disabled": False}),
                Element(0, "text", "Added to cart", (0, 80, 160, 24), "dom"),
            ]
        )
        self.assertEqual(update.kind, "delta")

    def test_large_change_crossing_threshold_forces_keyframe(self) -> None:
        store = StateStore(change_threshold=0.4)
        store.ingest([Element(0, "button", f"Old {index}", (0, index * 20, 100, 18), "dom") for index in range(10)])
        update = store.ingest(
            [Element(0, "button", f"New {index}", (0, index * 20, 100, 18), "dom") for index in range(10)]
        )
        self.assertEqual(update.kind, "key")
        self.assertEqual(update.reason, "change_threshold")


if __name__ == "__main__":
    unittest.main()

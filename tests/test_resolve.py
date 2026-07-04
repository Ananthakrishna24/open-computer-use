from __future__ import annotations

import unittest

from ocu import Action, Element
from ocu.resolve import ResolutionError, Resolver


class ResolverTests(unittest.TestCase):
    def test_resolves_id_to_center_coordinate(self) -> None:
        resolver = Resolver({7: Element(7, "button", "Buy", (10, 20, 100, 40), "dom")})
        target = resolver.resolve(Action("click", target=7))
        self.assertEqual(target.coordinate, (60, 40))
        self.assertEqual(target.element.id, 7)

    def test_scales_raw_coordinate_escape_hatch(self) -> None:
        resolver = Resolver({}, observation_size=(800, 600), device_size=(1600, 1200))
        target = resolver.resolve(Action("click", coordinate=(100, 50)))
        self.assertEqual(target.coordinate, (200, 100))
        self.assertIn("coordinate", target.note)

    def test_ambiguous_text_target_raises(self) -> None:
        resolver = Resolver(
            {
                1: Element(1, "button", "Add to cart", (0, 0, 100, 30), "dom"),
                2: Element(2, "button", "Add to cart", (0, 40, 100, 30), "dom"),
            }
        )
        with self.assertRaises(ResolutionError):
            resolver.resolve(Action("click", text="Add to cart"))


if __name__ == "__main__":
    unittest.main()

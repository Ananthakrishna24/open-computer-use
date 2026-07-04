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


class ActionCoerceTests(unittest.TestCase):
    def test_target_aliases(self) -> None:
        for key in ("target", "id", "element", "element_id"):
            self.assertEqual(Action.coerce({"verb": "click", key: 3}).target, 3)

    def test_verb_and_text_aliases(self) -> None:
        action = Action.coerce({"action": "type", "id": 2, "value": "mouse"})
        self.assertEqual(action.verb, "type")
        self.assertEqual(action.target, 2)
        self.assertEqual(action.text, "mouse")
        self.assertEqual(action.metadata, {})

    def test_extra_keys_stay_in_metadata(self) -> None:
        action = Action.coerce({"verb": "scroll", "dy": 300})
        self.assertEqual(action.metadata, {"dy": 300})

    def test_coordinate_in_target_field_moves_to_coordinate(self) -> None:
        action = Action.coerce({"verb": "click", "target": [579, 220]})
        self.assertIsNone(action.target)
        self.assertEqual(action.coordinate, (579, 220))

    def test_verb_as_key_infers_verb_and_payload(self) -> None:
        action = Action.coerce({"goto": "https://excalidraw.com/"})
        self.assertEqual(action.verb, "goto")
        self.assertEqual(action.text, "https://excalidraw.com/")
        action = Action.coerce({"press": "Escape"})
        self.assertEqual(action.verb, "press")
        self.assertEqual(action.text, "Escape")
        action = Action.coerce({"click": 7})
        self.assertEqual(action.verb, "click")
        self.assertEqual(action.target, 7)
        action = Action.coerce({"click": [100, 200]})
        self.assertEqual(action.coordinate, (100, 200))
        action = Action.coerce({"coordinate": [10, 20], "drag": [30, 40]})
        self.assertEqual(action.verb, "drag")
        self.assertEqual(action.coordinate, (10, 20))
        self.assertEqual(action.metadata["to"], [30, 40])
        action = Action.coerce({"wait": 250})
        self.assertEqual(action.verb, "wait")
        self.assertEqual(action.metadata["ms"], 250)

    def test_verb_as_key_with_nested_params(self) -> None:
        action = Action.coerce({"click": {"target": 141}})
        self.assertEqual(action.verb, "click")
        self.assertEqual(action.target, 141)
        action = Action.coerce({"click": {"coordinate": [141, 141]}})
        self.assertEqual(action.coordinate, (141, 141))
        action = Action.coerce({"drag": {"coordinate": [400, 300], "to": [700, 600]}})
        self.assertEqual(action.verb, "drag")
        self.assertEqual(action.coordinate, (400, 300))
        self.assertEqual(action.metadata["to"], [700, 600])
        action = Action.coerce({"type": {"target": 3, "text": "hello"}})
        self.assertEqual(action.verb, "type")
        self.assertEqual(action.target, 3)
        self.assertEqual(action.text, "hello")

    def test_goto_url_alias_and_untargeted_resolution(self) -> None:
        action = Action.coerce({"verb": "goto", "url": "https://example.test"})
        self.assertEqual(action.text, "https://example.test")
        resolved = Resolver({}).resolve(action)
        self.assertIsNone(resolved.coordinate)
        self.assertIsNone(Resolver({}).resolve(Action("back")).coordinate)


if __name__ == "__main__":
    unittest.main()

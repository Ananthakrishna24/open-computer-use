from __future__ import annotations

import unittest
from types import SimpleNamespace

from ocu.sensors.ax_linux import AxLinuxSensor


class FakeStateSet:
    def __init__(self, names):
        self.names = list(names)

    def getStates(self):
        return self.names


class FakeComponent:
    def __init__(self, bbox):
        self.bbox = bbox

    def getExtents(self, coord_type):
        x, y, width, height = self.bbox
        return SimpleNamespace(x=x, y=y, width=width, height=height)


class FakeText:
    def __init__(self, content):
        self.content = content
        self.characterCount = len(content)

    def getText(self, start, end):
        return self.content[start:end]


class FakeNode:
    def __init__(self, role, name="", states=(), bbox=None, children=(), text=None, description=""):
        self.role = role
        self.name = name
        self.description = description
        self.states = states
        self.bbox = bbox
        self.children = list(children)
        self.text = text

    def getRoleName(self):
        return self.role

    def getState(self):
        return FakeStateSet(self.states)

    def queryComponent(self):
        if self.bbox is None:
            raise NotImplementedError
        return FakeComponent(self.bbox)

    def queryText(self):
        if self.text is None:
            raise NotImplementedError
        return FakeText(self.text)

    @property
    def childCount(self):
        return len(self.children)

    def getChildAtIndex(self, index):
        return self.children[index]


VISIBLE = ("visible", "showing")


def desktop(*apps):
    return FakeNode("desktop frame", children=apps)


class AxLinuxSensorTests(unittest.TestCase):
    def build(self):
        save = FakeNode(
            "push button", "Save", (*VISIBLE, "sensitive", "focused"), (10, 20, 100, 32)
        )
        entry = FakeNode(
            "text", "Search", (*VISIBLE, "sensitive", "editable"), (10, 60, 200, 28),
            text="wireless mouse",
        )
        check = FakeNode("check box", "Remember me", (*VISIBLE, "sensitive"), (10, 100, 20, 20))
        label = FakeNode("label", "Your cart is empty", VISIBLE, (10, 140, 180, 18))
        hidden = FakeNode("push button", "Ghost", ("visible",), (10, 180, 80, 24))
        flat = FakeNode("push button", "Flat", (*VISIBLE, "sensitive"), (10, 220, 0, 0))
        disabled = FakeNode("push button", "Checkout", VISIBLE, (10, 260, 100, 32))
        panel = FakeNode(
            "panel", "Container", VISIBLE, (0, 0, 400, 400),
            children=(save, entry, check, label, hidden, flat, disabled),
        )
        frame = FakeNode("frame", "App Window", VISIBLE, (0, 0, 400, 400), children=(panel,))
        app = FakeNode("application", "app", children=(frame,))
        return AxLinuxSensor(desktop=desktop(app))

    def test_capture_produces_normalized_elements(self):
        frame = self.build().capture()
        by_text = {element.text: element for element in frame.elements}
        self.assertEqual(
            set(by_text), {"Save", "Search", "Remember me", "Your cart is empty", "Checkout"}
        )

        save = by_text["Save"]
        self.assertEqual(save.role, "button")
        self.assertEqual(save.bbox, (10, 20, 100, 32))
        self.assertEqual(save.source, "ax")
        self.assertTrue(save.state["interactive"])
        self.assertTrue(save.state["focused"])
        self.assertTrue(save.state["structural_path"].startswith("ax>app[1]>"))

        entry = by_text["Search"]
        self.assertEqual(entry.role, "input")
        self.assertEqual(entry.state["value"], "wireless mouse")

        check = by_text["Remember me"]
        self.assertEqual(check.role, "checkbox")
        self.assertFalse(check.state["checked"])

        label = by_text["Your cart is empty"]
        self.assertEqual(label.role, "text")
        self.assertFalse(label.state["interactive"])

        self.assertTrue(by_text["Checkout"].state["disabled"])

    def test_invisible_and_zero_area_nodes_are_skipped(self):
        texts = {element.text for element in self.build().capture().elements}
        self.assertNotIn("Ghost", texts)
        self.assertNotIn("Flat", texts)

    def test_containers_without_interactivity_are_skipped(self):
        texts = {element.text for element in self.build().capture().elements}
        self.assertNotIn("Container", texts)
        self.assertNotIn("App Window", texts)

    def test_region_filter(self):
        frame = self.build().capture(region=(0, 0, 300, 50))
        self.assertEqual([element.text for element in frame.elements], ["Save"])


if __name__ == "__main__":
    unittest.main()

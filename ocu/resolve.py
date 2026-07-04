from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, Mapping

from .schema import Action, Coordinate, Element, normalize_text


class ResolutionError(ValueError):
    ...


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    action: Action
    element: Element | None
    coordinate: Coordinate | None
    note: str = ""


class Resolver:
    def __init__(
        self,
        elements: Mapping[int, Element] | Iterable[Element],
        *,
        observation_size: tuple[int, int] | None = None,
        device_size: tuple[int, int] | None = None,
    ) -> None:
        if isinstance(elements, Mapping):
            self.elements = dict(elements)
        else:
            self.elements = {element.id: element for element in elements}
        self.observation_size = observation_size
        self.device_size = device_size

    def resolve(self, action: Action | Mapping[str, object]) -> ResolvedTarget:
        action = Action.coerce(action)
        if action.verb in {"wait", "observe", "done", "press", "goto", "back"} and action.target is None and action.coordinate is None:
            return ResolvedTarget(action=action, element=None, coordinate=None)

        if action.target is not None:
            element = self.elements.get(action.target)
            if element is None:
                raise ResolutionError(f"target [{action.target}] is not in the current element table")
            return ResolvedTarget(action=action, element=element, coordinate=element.center)

        if action.coordinate is not None:
            return ResolvedTarget(
                action=action,
                element=None,
                coordinate=self._scale_coordinate(action.coordinate),
                note="coordinate action; prefer element ids",
            )

        if action.text:
            element = self._resolve_text(action.text)
            return ResolvedTarget(action=action, element=element, coordinate=element.center)

        raise ResolutionError(f"{action.verb} requires target, coordinate, or text")

    def _resolve_text(self, text: str) -> Element:
        query = normalize_text(text).casefold()
        if not query:
            raise ResolutionError("cannot resolve an empty text target")

        candidates: list[tuple[float, Element]] = []
        for element in self.elements.values():
            label = normalize_text(element.text).casefold()
            if not label:
                continue
            if label == query:
                score = 1.0
            elif query in label or label in query:
                score = 0.92
            else:
                score = SequenceMatcher(a=query, b=label).ratio()
            if score >= 0.62:
                candidates.append((score, element))

        if not candidates:
            raise ResolutionError(f'no element text matches "{text}"')
        candidates.sort(key=lambda item: (-item[0], item[1].id))
        best_score = candidates[0][0]
        best = [element for score, element in candidates if abs(score - best_score) < 0.03]
        if len(best) > 1:
            listing = ", ".join(f'[{element.id}] "{element.text}"' for element in best[:8])
            raise ResolutionError(f'ambiguous text target "{text}"; candidates: {listing}')
        return candidates[0][1]

    def _scale_coordinate(self, coordinate: Coordinate) -> Coordinate:
        if not self.observation_size or not self.device_size:
            return coordinate
        obs_width, obs_height = self.observation_size
        dev_width, dev_height = self.device_size
        if obs_width <= 0 or obs_height <= 0:
            return coordinate
        x, y = coordinate
        return (int(round(x * dev_width / obs_width)), int(round(y * dev_height / obs_height)))

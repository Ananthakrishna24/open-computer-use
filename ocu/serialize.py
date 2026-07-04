from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .schema import Element, INTERACTIVE_ROLES, Observation
from .state import FrameUpdate

DEFAULT_MAX_TEXT = 60


@dataclass(frozen=True, slots=True)
class SerializedText:
    text: str
    tokens: int


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int((len(text) / 4) * 1.15) + 1)


def observation_from_update(update: FrameUpdate, max_tokens: int) -> Observation:
    serialized = serialize_update(update, max_tokens=max_tokens)
    return Observation(
        frame=update.frame,
        kind=update.kind,
        text=serialized.text,
        elements=update.elements,
        tokens=serialized.tokens,
    )


def serialize_update(update: FrameUpdate, *, max_tokens: int) -> SerializedText:
    if update.kind == "key":
        return serialize_keyframe(update, max_tokens=max_tokens)
    return serialize_delta(update, max_tokens=max_tokens)


def serialize_keyframe(update: FrameUpdate, *, max_tokens: int) -> SerializedText:
    header = [f"## screen (frame {update.frame}, full)"]
    if update.url:
        header.append(f"url: {update.url}")
    if update.reason and update.reason != "first_observation":
        header.append(f"reason: {update.reason}")

    elements = list(update.elements.values())
    visible = [element for element in elements if element.is_visible]
    interactive = [element for element in visible if element.is_interactive]
    focused = [element for element in visible if element.state.get("focused") or element.state.get("selected")]
    static_text = [element for element in visible if element.role == "text" and element not in interactive]
    offscreen_interactive = [element for element in elements if element.is_interactive and not element.is_visible]

    ordered = _dedupe([*interactive, *_neighbors(visible, focused), *static_text])

    lines = [format_element(element) for element in ordered]
    summary_lines = []
    if offscreen_interactive:
        summary_lines.append(f"... {len(offscreen_interactive)} offscreen interactive elements omitted")
    remaining = len(elements) - len(set(element.id for element in ordered)) - len(offscreen_interactive)
    if remaining > 0:
        summary_lines.append(f"... {remaining} more elements omitted")

    return _fit_lines(header, lines, summary_lines, max_tokens=max_tokens, omitted_label="elements")


def serialize_delta(update: FrameUpdate, *, max_tokens: int) -> SerializedText:
    previous_frame = max(update.frame - 1, 0)
    header = [f"## screen (frame {update.frame}, changes since frame {previous_frame})"]
    if update.last_action:
        action_line = f"did: {update.last_action} -> ok"
        if update.aborted_step is not None:
            action_line = f"did: {update.last_action} -> aborted at step {update.aborted_step}"
        header.append(action_line)
    if update.url and update.previous_url and update.url != update.previous_url:
        header.append(f"url: {update.url}")
    if update.reason != "delta":
        header.append(f"reason: {update.reason}")

    change_lines: list[str] = []
    for element in update.diff.added:
        change_lines.append(f"+ {format_element(element)}")
    for old, new in update.diff.changed:
        change_lines.append(f"~ {format_element(new)}{format_change_suffix(old, new)}")
    for element in update.diff.removed:
        change_lines.append(f"- {format_element(element)}")

    summary_lines = [f"unchanged: {len(update.diff.unchanged)} elements"]
    return _fit_lines(header, change_lines, summary_lines, max_tokens=max_tokens, omitted_label="changes")


def format_element(element: Element, *, max_text: int = DEFAULT_MAX_TEXT) -> str:
    text = _truncate(element.text, max_text)
    state = format_state(element)
    if text:
        body = f'[{element.id}]  {element.role:<8} "{text}"'
    else:
        body = f"[{element.id}]  {element.role:<8}"
    if element.role == "canvas":
        x, y, width, height = element.bbox
        body = f"{body} area x={x} y={y} w={width} h={height}"
    if state:
        return f"{body}  ({state})"
    return body


def format_state(element: Element) -> str:
    parts: list[str] = []
    state = element.state
    if state.get("disabled"):
        parts.append("disabled")
    if state.get("focused"):
        parts.append("focused")
    if state.get("checked") is True:
        parts.append("checked")
    if state.get("checked") is False and element.role in {"checkbox", "radio", "switch"}:
        parts.append("unchecked")
    if state.get("selected"):
        parts.append("selected")
    if "value" in state and state["value"] not in {None, "", element.text}:
        parts.append(f'value="{_truncate(str(state["value"]), 40)}"')
    return ", ".join(parts)


def format_change_suffix(old: Element, new: Element) -> str:
    changes: list[str] = []
    if old.text != new.text:
        changes.append(f'was "{_truncate(old.text, 40)}"')
    if old.state.get("disabled") != new.state.get("disabled"):
        changes.append("now disabled" if new.state.get("disabled") else "now enabled")
    if old.state.get("checked") != new.state.get("checked") and new.state.get("checked") is not None:
        changes.append("now checked" if new.state.get("checked") else "now unchecked")
    if old.state.get("value") != new.state.get("value"):
        changes.append(f'value now "{_truncate(str(new.state.get("value") or ""), 40)}"')
    if old.state.get("focused") != new.state.get("focused") and new.state.get("focused"):
        changes.append("now focused")
    if old.bbox != new.bbox:
        changes.append("moved")
    if not changes:
        return "  (changed)"
    return f"  ({', '.join(changes)})"


def _fit_lines(
    header: list[str],
    candidate_lines: list[str],
    summary_lines: list[str],
    *,
    max_tokens: int,
    omitted_label: str,
) -> SerializedText:
    max_tokens = max(1, int(max_tokens))
    accepted: list[str] = []
    omitted = 0

    for line in candidate_lines:
        trial = "\n".join(header + accepted + [line] + summary_lines)
        if estimate_tokens(trial) <= max_tokens:
            accepted.append(line)
        else:
            omitted += 1

    remaining_summary = list(summary_lines)
    while True:
        budget_summary = [f"... {omitted} {omitted_label} omitted by token budget"] if omitted else []
        lines = header + accepted + budget_summary + remaining_summary
        if estimate_tokens("\n".join(lines)) <= max_tokens:
            break
        if accepted:
            accepted.pop()
            omitted += 1
            continue
        if remaining_summary:
            remaining_summary.pop()
            continue
        break

    text = "\n".join(lines)
    if estimate_tokens(text) > max_tokens:
        text = _truncate_to_token_budget(text, max_tokens)
    return SerializedText(text=text, tokens=estimate_tokens(text))


def _truncate_to_token_budget(text: str, max_tokens: int) -> str:
    max_chars = max(1, int(max_tokens / 1.15 * 4) - 1)
    if len(text) <= max_chars:
        return text
    if max_chars <= 1:
        return text[:max_chars]
    return text[: max_chars - 1].rstrip() + "…"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _dedupe(elements: Iterable[Element]) -> list[Element]:
    seen: set[int] = set()
    result: list[Element] = []
    for element in elements:
        if element.id in seen:
            continue
        seen.add(element.id)
        result.append(element)
    return result


def _neighbors(elements: list[Element], anchors: list[Element], radius: int = 1) -> list[Element]:
    if not anchors:
        return []
    by_id = {element.id: index for index, element in enumerate(elements)}
    result: list[Element] = []
    for anchor in anchors:
        index = by_id.get(anchor.id)
        if index is None:
            continue
        start = max(0, index - radius)
        end = min(len(elements), index + radius + 1)
        result.extend(elements[start:end])
    return result

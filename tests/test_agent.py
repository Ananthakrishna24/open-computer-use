import pytest

from agent.browser import looks_blocked, read_page
from agent.core import act_signature
from agent.skills import SKILL_TOOL, SKILLS, build_elements, layout_warnings
from agent.ui import preview_result, summarize_call


def test_read_page_chunks():
    body = " ".join(f"w{i}" for i in range(3000))
    first = read_page(body, chunk_chars=1000)
    assert first.startswith("## page text (part 1/")
    second = read_page(body, page=1, chunk_chars=1000)
    assert "(part 2/" in second
    assert first.splitlines()[1] != second.splitlines()[1]


def test_read_page_query_jumps():
    body = "a" * 5000 + " needle here " + "b" * 5000
    result = read_page(body, query="needle", chunk_chars=1000)
    assert "needle" in result
    assert "(part 1/" not in result


def test_read_page_query_missing():
    assert "not found" in read_page("some text", query="absent")


def test_read_page_empty():
    assert read_page("") == "page has no readable text"


def test_act_signature_canonical():
    a = act_signature("act", '{"actions": [{"verb": "click", "target": 3}]}')
    b = act_signature("act", '{"actions":[{"target":3,"verb":"click"}]}')
    assert a == b
    assert a != act_signature("act", '{"actions": [{"verb": "click", "target": 4}]}')


def test_act_signature_invalid_json():
    assert act_signature("act", "{broken") == act_signature("act", "{broken")


def test_looks_blocked():
    assert looks_blocked("## screen\nPlease verify you are human")
    assert looks_blocked("Just a moment... Checking your browser")
    assert not looks_blocked("## screen\n[1] button 'Search'")


def test_summarize_call_act_labels():
    args = '{"actions": [{"verb": "click", "target": 3}, {"verb": "type", "text": "cats"}]}'
    summary = summarize_call("act", args)
    assert summary.startswith("act(")
    assert "click [3]" in summary
    assert "type 'cats'" in summary


def test_summarize_call_truncates_and_survives_bad_json():
    long_args = '{"query": "' + "x" * 300 + '"}'
    assert len(summarize_call("read", long_args)) < 120
    assert summarize_call("act", "{broken") == "act(…)"


def test_preview_result_picks_did_line():
    result = "## screen (frame 4, changes since frame 3)\ndid: click [3] -> ok\n+ [9] link 'Next'"
    lines = preview_result(result)
    assert lines == ["did: click [3] -> ok"]
    assert preview_result("") == []


def test_preview_result_falls_back_to_first_lines():
    lines = preview_result("plain first\nplain second\nplain third")
    assert lines == ["plain first", "plain second"]


def test_build_elements_box_binds_label():
    shape, text = build_elements([{"kind": "box", "label": "LLM", "x": 10, "y": 20}])
    assert shape["type"] == "rectangle"
    assert text["type"] == "text"
    assert text["containerId"] == shape["id"]
    assert shape["boundElements"] == [{"id": text["id"], "type": "text"}]
    assert (shape["width"], shape["height"]) == (200.0, 80.0)


def test_build_elements_arrow_points():
    (arrow,) = build_elements([{"kind": "arrow", "from": [100, 200], "to": [100, 300]}])
    assert arrow["type"] == "arrow"
    assert arrow["points"] == [[0, 0], [0.0, 100.0]]
    assert arrow["endArrowhead"] == "arrow"


def test_build_elements_rejects_bad_spec():
    with pytest.raises(ValueError, match="element 0"):
        build_elements([{"kind": "hexagon"}])
    with pytest.raises(ValueError, match="element 1"):
        build_elements([{"kind": "text", "label": "ok", "x": 0, "y": 0}, {"kind": "box"}])


def test_layout_warnings_flag_overlap_and_overflow():
    elements = build_elements([
        {"kind": "box", "label": "a very long label that truly cannot ever fit in here", "x": 0, "y": 0, "w": 100, "h": 40},
        {"kind": "box", "label": "second", "x": 50, "y": 20, "w": 100, "h": 60},
        {"kind": "text", "label": "floating title", "x": 60, "y": 30, "size": 20},
    ])
    warnings = layout_warnings(elements)
    assert any("does not fit" in w for w in warnings)
    assert any("'floating title'" in w and "overlap" in w for w in warnings)


def test_labels_autofit_and_unescape():
    shape, text = build_elements([
        {"kind": "box", "label": "Load Balancers & API Gateway\\n(Routing, Auth, Rate Limiting)", "x": 0, "y": 0, "w": 240, "h": 80},
    ])
    assert "\\n" not in text["text"]
    assert text["fontSize"] < 20
    assert text["width"] <= shape["width"] - 16
    assert text["height"] <= shape["height"] - 8
    assert layout_warnings([shape, text]) == []


def test_layout_warnings_clean_diagram():
    elements = build_elements([
        {"kind": "box", "label": "ok", "x": 0, "y": 0, "w": 200, "h": 80},
        {"kind": "box", "label": "fine", "x": 0, "y": 160, "w": 200, "h": 80},
        {"kind": "arrow", "from": [100, 80], "to": [100, 160]},
    ])
    assert layout_warnings(elements) == []


def test_skill_tool_lists_registry():
    description = SKILL_TOOL["function"]["description"]
    for name in SKILLS:
        assert name in description
    assert SKILL_TOOL["function"]["parameters"]["properties"]["name"]["enum"] == list(SKILLS)


def test_load_skill_registers_tools_and_handlers():
    from agent.core import Agent

    agent = Agent.__new__(Agent)
    agent.tools = [SKILL_TOOL]
    agent.skill_handlers = {}
    agent.on_event = None
    result = agent._load_skill('{"name": "excalidraw"}')
    assert "draw tool" in result
    assert any(tool["function"]["name"] == "draw" for tool in agent.tools if tool is not SKILL_TOOL)
    assert "draw" in agent.skill_handlers
    assert "unknown skill" in agent._load_skill('{"name": "nope"}')

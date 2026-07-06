from agent.core import act_signature, looks_blocked, read_page


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

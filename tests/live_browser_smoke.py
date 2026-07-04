from __future__ import annotations

from urllib.parse import quote

from ocu import Browser


def main() -> int:
    html = """<!doctype html><html><body>
<button id="add" onclick="document.getElementById('status').textContent='Added to cart'; document.getElementById('checkout').disabled=false">Add to cart</button>
<button id="checkout" disabled>Checkout</button>
<p id="status">Your cart is empty</p>
</body></html>"""
    browser = Browser(start_url="data:text/html," + quote(html), max_obs_tokens=1500, headless=True)
    try:
        first = browser.observe(mode="full")
        add_id = next(element.id for element in first.elements.values() if element.role == "button" and element.text == "Add to cart")
        second = browser.act("click", target=add_id)
        assert second.kind == "delta", second.text
        assert "did: click" in second.text, second.text
        assert "Added to cart" in second.text, second.text
        print(second.text)
    finally:
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

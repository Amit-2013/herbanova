"""The page wiring must survive a marker element going missing.

app.js binds a fixed set of controls at load. A bare $("#id").addEventListener
threw when an id was absent, which aborted the block before boot() ran. The
load-time bindings now go through a null-safe helper; these tests keep it that
way and catch a typo against the markup.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")


def test_every_load_time_binding_target_exists_in_the_markup():
    bound = set(re.findall(r'bind\("#([\w-]+)"', JS))
    # Ids bound from a literal list: ["pq", ...].forEach(id => bind("#" + id, ...))
    for listed in re.findall(r'\[([^\]]*)\]\.forEach\(id => bind\("#" \+ id', JS):
        bound |= set(re.findall(r'"([\w-]+)"', listed))
    bound.add("salesChart")            # bound through chartEl under `if (chartEl)`
    assert len(bound) >= 26
    missing = sorted(i for i in bound if f'id="{i}"' not in HTML)
    assert missing == []


def test_the_binding_helper_is_null_safe():
    helper = ('const bind = (sel, event, fn) => { const el = typeof sel === "string" '
              '? $(sel) : sel; if (el) el.addEventListener(event, fn); return el; };')
    assert helper in JS
    # From the helper onward no load-time binding may go back to the bare form.
    block = JS[JS.index("const bind = "):]
    assert not re.search(r'^\$\("#[^"]+"\)\.addEventListener', block, re.M)

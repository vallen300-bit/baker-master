"""COCKPIT_HEADER_BLOCK_STICKY_1 — keep the roster header attached to its rows."""
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "scripts" / "cockpit_static"
HTML = (ROOT / "index.html").read_text()
CSS_RAW = (ROOT / "cockpit.css").read_text()
CSS = re.sub(r"/\*.*?\*/", "", CSS_RAW, flags=re.S)
JS = (ROOT / "cockpit.js").read_text()


def test_one_sticky_block_contains_title_status_meta_and_columns():
    block = re.search(
        r'<div class="cockpit-sticky" id="cockpit-sticky">(.*?)</div>\s*<div id="grid">',
        HTML,
        flags=re.S,
    )
    assert block, "sticky cockpit header must directly precede the roster grid"
    body = block.group(1)
    for marker in (
        'id="cockpit-title"',
        'id="sync-note"',
        'class="cockpit-sticky-meta"',
        'class="fleet-columns"',
    ):
        assert marker in body, f"sticky block missing {marker}"
    assert HTML.count('class="fleet-columns"') == 1


def test_sticky_block_is_opaque_and_compact():
    m = re.search(r"\.cockpit-sticky\s*\{([^}]*)\}", CSS)
    assert m, ".cockpit-sticky rule missing"
    body = m.group(1)
    assert "position: sticky" in body
    assert re.search(r"\btop:\s*0", body)
    assert "z-index:" in body
    assert "background: var(--bg)" in body
    assert "grid-template-areas" in body
    assert "title" in body and "status" in body and "meta" in body and "columns" in body
    assert "padding: 9px 8px 0" in body

    title = re.search(r"\.cockpit-sticky-title\s*\{([^}]*)\}", CSS)
    assert title, ".cockpit-sticky-title rule missing"
    title_body = title.group(1)
    assert 'font: 600 16px/24px -apple-system, "system-ui", monospace' in title_body
    assert "letter-spacing: 0" in title_body
    assert "white-space: nowrap" in title_body


def test_shadow_is_stateful_not_always_on():
    m = re.search(r"\.cockpit-sticky\.is-stuck\s*\{([^}]*)\}", CSS)
    assert m, "stuck-state shadow rule missing"
    assert "box-shadow:" in m.group(1)
    assert "box-shadow:" not in re.search(r"\.cockpit-sticky\s*\{([^}]*)\}", CSS).group(1)
    assert 'classList.toggle("is-stuck", window.scrollY > 0)' in JS
    assert 'addEventListener("scroll", syncStickyShadow' in JS


def test_group_labels_remain_outside_sticky_block():
    block = re.search(
        r'<div class="cockpit-sticky" id="cockpit-sticky">(.*?)</div>\s*<div id="grid">',
        HTML,
        flags=re.S,
    )
    assert block
    assert "class=\"plate\"" not in block.group(1)
    assert "CONTROL TOWER" not in block.group(1)


def test_390px_mobile_keeps_reference_title_single_line_and_compact():
    mobile = re.search(
        r"@media\s*\(max-width:\s*640px\)\s*\{(.*?)\n\}",
        CSS,
        flags=re.S,
    )
    assert mobile, "mobile cockpit rules missing"
    body = mobile.group(1)
    assert "cockpit-sticky-title" not in body
    assert "font-size: 23px" not in body
    assert 'font: 600 16px/24px -apple-system, "system-ui", monospace' in CSS
    assert 'grid-template-areas: "title" "status" "meta"' in body
    assert "padding: 8px 5px 0" in body
    assert "overflow: hidden" in body


def test_mobile_status_wraps_inside_sticky_content_width():
    mobile = re.search(
        r"@media\s*\(max-width:\s*640px\)\s*\{(.*?)\n\}",
        CSS,
        flags=re.S,
    )
    assert mobile, "mobile cockpit rules missing"
    status = re.search(
        r"\.cockpit-sticky\s*>\s*\.summary-status\s*\{([^}]*)\}",
        mobile.group(1),
        flags=re.S,
    )
    assert status, "mobile sticky status override missing"
    body = status.group(1)
    assert "min-width: 0" in body
    assert "max-width: 100%" in body
    assert "white-space: normal" in body
    assert "overflow-wrap: anywhere" in body

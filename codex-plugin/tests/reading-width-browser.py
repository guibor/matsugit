"""Exercise the exported reading grid, not a standalone stylesheet."""
import os
from pathlib import Path
import subprocess
import tempfile

from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
    source = Path(tmp) / "brief.md"
    source.write_text("## Results\n\nShort paragraph.\n\n| Unit | Status | Detail | Owner | Next | Due |\n"
                      "|---|---|---|---|---|---|\n"
                      "| A | `READY_FOR_INSPECTION` | `LONG_FIELD_IDENTIFIER` | "
                      "Several ordinary words that can wrap | `REQUIRES_FOLLOW_UP` | D |\n")
    output = Path(tmp) / "render"
    subprocess.run([root / "bin/matsugit", "render", source, "--only", "document",
                    "--theme", "default", "--output", output], check=True)
    browser = pw.chromium.launch(executable_path=os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE"))
    page = browser.new_page()
    widths = []
    for width in (390, 1440, 1920):
        page.set_viewport_size({"width": width, "height": 900})
        page.goto((output / "index.html").as_uri())
        if width == 390:
            box = page.locator(".matsugit-table-scroll")
            assert box.evaluate("b => {b.scrollLeft = 80; return b.scrollLeft > 0 && b.tabIndex === 0}")
            assert page.locator("td code").first.evaluate("e=>getComputedStyle(e).whiteSpace") == "nowrap"
            page.locator(".matsugit-pocket-outline summary").click()
            page.locator(".matsugit-pocket-outline a").first.click()
            assert page.url.endswith("#results")
        else:
            assert page.locator("#TOC").is_visible()
            table = page.locator("table")
            before = table.bounding_box()["width"]
            toggle = page.locator(".matsugit-desktop-outline summary")
            toggle.click()
            page.wait_for_selector("main > .matsugit-desktop-outline:not([open])")
            after = table.bounding_box()["width"]
            assert after > before + 120, (width, before, after)
            toggle.click()
            page.wait_for_selector("#quarto-margin-sidebar .matsugit-desktop-outline[open]")
            assert abs(table.bounding_box()["width"] - before) <= 1
            print(f"{width}px viewport: table {before:.0f} -> {after:.0f} -> {before:.0f}px")
        assert page.locator("td code").first.evaluate("e=>getComputedStyle(e).backgroundColor") == "rgba(0, 0, 0, 0)"
        assert page.evaluate("document.documentElement.scrollWidth") <= width
        assert 13 <= page.locator("main p").first.evaluate("p=>parseFloat(getComputedStyle(p).fontSize)") <= 15
        widths.append(page.locator("table").evaluate("t=>t.offsetWidth"))
    assert widths[1] > 900 and widths[2] - widths[1] > 300, widths
    source.write_text("---\ndocument-toc: false\n---\n\n" + source.read_text())
    output = Path(tmp) / "no-outline"
    subprocess.run([root / "bin/matsugit", "render", source, "--only", "document",
                    "--theme", "default", "--output", output], check=True)
    page.goto((output / "index.html").as_uri())
    assert not page.locator("#TOC, .matsugit-pocket-outline").count()
    assert page.locator(".matsugit-table-scroll").count() == 1
    browser.close()

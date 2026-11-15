"""Disclosure mechanics, nested sections, navigation, print and no slide changes."""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
    page = browser.new_page(viewport={'width': 390, 'height': 844})
    page.set_content('''<main class="content"><section id="one" class="level1"><h1>First section</h1><p>First body</p>
      <section id="two" class="level2"><h2>Nested section</h2><p id="evidence">Evidence remains</p></section></section>
      <section id="three" class="level1"><h1>Next section</h1><p>Next body</p></section></main>
      <a href="#evidence">Evidence link</a>''')
    page.add_style_tag(path=str(ROOT/'matsugit/runtime/document-fold.css'))
    page.add_script_tag(path=str(ROOT/'matsugit/runtime/document-fold.js'))
    assert page.locator('.ff-fold-toggle').count() == 3
    first = page.locator('#one > h1 button')
    second = page.locator('#two > h2 button')
    second.click()
    first.click()
    assert page.locator('#three p').is_visible()
    assert page.locator('#evidence').is_hidden()
    page.emulate_media(media='print')
    assert page.locator('#evidence').is_visible()
    assert first.is_hidden()
    page.emulate_media(media='screen')
    first.focus()
    page.keyboard.press('Enter')
    assert second.get_attribute('aria-expanded') == 'false'
    assert page.locator('#evidence').is_hidden()
    page.get_by_role('link', name='Evidence link').click()
    assert page.locator('#evidence').is_visible()
    assert second.get_attribute('aria-expanded') == 'true'
    first.click()
    page.locator('#evidence').evaluate("el=>el.dispatchEvent(new Event('matsugit-reveal',{bubbles:true}))")
    assert page.locator('#evidence').is_visible()
    first.click()
    page.keyboard.press('Control+f')
    assert page.locator('#evidence').is_visible()
    assert page.locator('#evidence').text_content() == 'Evidence remains'
    page.set_content('<div class="reveal"><main class="content"><section class="level2"><h2>Slide</h2><p>Body</p></section></main></div>')
    page.add_script_tag(path=str(ROOT/'matsugit/runtime/document-fold.js'))
    assert page.locator('.ff-fold-toggle').count() == 0
    browser.close()
print('PASS: nested folds, keyboard, anchors, source following, print and slides unchanged')

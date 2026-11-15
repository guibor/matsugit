"""Disclosure mechanics, nested sections, navigation, print and no slide changes."""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
    page = browser.new_page(viewport={'width': 390, 'height': 844})
    page.set_content('''<main class="content"><section id="one" class="level1 collapsible"><h1>First section</h1><p>First body</p>
      <section id="two" class="level2"><h2>Nested section</h2><p id="evidence">Evidence remains</p>
        <section id="deep" class="level3"><h3>Deeper section</h3><p>Deep evidence</p></section></section></section>
      <section id="three" class="level1"><h1>Next section</h1><p>Next body</p></section></main>
      <a href="#evidence">Evidence link</a>''')
    page.add_style_tag(path=str(ROOT/'matsugit/runtime/document-fold.css'))
    page.add_script_tag(path=str(ROOT/'matsugit/runtime/document-fold.js'))
    assert page.locator('.ff-fold-toggle').count() == 3
    assert page.locator('#deep > h3 button').get_attribute('aria-expanded') == 'false'
    assert page.locator('#three button').count() == 0
    first = page.locator('#one > h1 button')
    second = page.locator('#two > h2 button')
    assert first.get_attribute('aria-expanded') == 'false'
    assert second.get_attribute('aria-expanded') == 'false'
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
    assert page.locator('#deep p').is_hidden()
    first.click()
    page.locator('#evidence').evaluate("el=>el.dispatchEvent(new Event('matsugit-reveal',{bubbles:true}))")
    assert page.locator('#evidence').is_visible()
    first.click()
    page.keyboard.press('Control+f')
    assert page.locator('#evidence').is_visible()
    assert page.locator('#evidence').text_content() == 'Evidence remains'
    page.set_content('<main><section class="level2"><h2>Ordinary</h2><p>Always visible</p></section>'
                     '<div class="collapsible" title="Supporting detail"><p id="details">Detailed evidence</p></div></main>')
    page.add_style_tag(path=str(ROOT/'matsugit/runtime/document-fold.css'))
    page.add_script_tag(path=str(ROOT/'matsugit/runtime/document-fold.js'))
    assert page.locator('.ff-fold-toggle').count() == 1
    assert page.locator('#details').is_hidden()
    assert page.get_by_text('Always visible').is_visible()
    page.get_by_role('button', name='Section: Supporting detail').click()
    assert page.locator('#details').is_visible()
    page.get_by_role('button', name='Section: Supporting detail').click()
    page.emulate_media(media='print')
    assert page.locator('#details').is_visible()
    assert page.get_by_text('Supporting detail', exact=True).is_visible()
    page.emulate_media(media='screen')
    page.set_content('<main><section id="parent"><h2 class="collapsible">Parent</h2>'
                     '<section id="child"><h3>Child</h3><p>Child body</p></section></section>'
                     '<section id="sibling"><h2>Sibling</h2><p>Sibling body</p></section></main>')
    page.add_style_tag(path=str(ROOT/'matsugit/runtime/document-fold.css'))
    page.add_script_tag(path=str(ROOT/'matsugit/runtime/document-fold.js'))
    assert page.locator('.ff-fold-toggle').count() == 2
    page.locator('#parent > h2 button').click()
    assert page.locator('#child > h3 button').get_attribute('aria-expanded') == 'false'
    assert page.locator('#child p').is_hidden()
    assert page.locator('#sibling p').is_visible()
    assert page.locator('#sibling button').count() == 0
    page.set_content('<div class="reveal"><main class="content"><section class="level2"><h2>Slide</h2><p>Body</p></section></main></div>')
    page.add_script_tag(path=str(ROOT/'matsugit/runtime/document-fold.js'))
    assert page.locator('.ff-fold-toggle').count() == 0
    browser.close()
print('PASS: opt-in sections and blocks, collapsed defaults, nesting, keyboard, anchors, source following, print and slides unchanged')

"""Clipboard and narrow-layout checks inside the real Share modal."""


def check_share_links(page, frame, site, shots, wait):
    button = frame.locator('.share-copy-link[data-link="document"]')
    expected = site + '/deck/index.html'
    before = frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
    frame.evaluate('''() => {
      window.originalCopy = document.execCommand.bind(document);
      window.originalClipboard = navigator.clipboard;
    }''')
    # Real browser clipboard readback, not a mocked success receipt.
    page.context.grant_permissions(['clipboard-read', 'clipboard-write'])
    button.click()
    wait(frame, 'document.getElementById("share-copy-status").textContent === "Document link copied."')
    assert frame.evaluate('navigator.clipboard.readText()') == expected
    assert button.get_attribute('aria-label') == 'Document link copied'
    assert frame.evaluate('document.activeElement.dataset.link') == 'document'
    frame.evaluate('Object.defineProperty(navigator, "clipboard", {configurable:true, value:undefined})')
    button.click()
    wait(frame, 'document.getElementById("share-copy-status").textContent === "Document link copied."')
    assert frame.evaluate('window.originalClipboard.readText()') == expected
    frame.evaluate('''() => { document.execCommand = () => false;
      Object.defineProperty(navigator, 'clipboard', {configurable:true, value:window.originalClipboard}); }''')
    button.click()
    wait(frame, 'document.getElementById("share-copy-status").textContent === "Document link copied."')
    assert frame.evaluate('navigator.clipboard.readText()') == expected
    # Both blocked: select the complete URL, never report success.
    frame.evaluate('''() => { document.execCommand = () => {throw Error('blocked')};
      Object.defineProperty(navigator, 'clipboard', {configurable:true,
        value:{writeText:async()=>{throw Error('blocked')}}}); }''')
    button.click()
    wait(frame, '!document.getElementById("share-copy-fallback").hidden')
    assert frame.locator('#share-copy-url').input_value() == expected
    assert frame.evaluate('''() => { const i=document.getElementById('share-copy-url');
      return document.activeElement===i && i.selectionStart===0 && i.selectionEnd===i.value.length; }''')
    assert 'copied' not in frame.locator('#share-copy-status').inner_text()
    opened = page.evaluate('window.openedLinks')
    for key, suffix in [('slides', 'slides.html'), ('document', 'index.html')]:
        frame.locator(f'.share-open[data-link="{key}"]').click()
        page.wait_for_function('(url) => window.openedLinks.at(-1) === url', arg=site+'/deck/'+suffix)
    page.evaluate('(links) => {window.openedLinks=links}', opened)
    for width in (320, 390, 1300):
        page.set_viewport_size({'width': width, 'height': 850})
        button.scroll_into_view_if_needed()
        assert frame.evaluate('''() => [...document.querySelectorAll('#share-links button')].every(b=>{
          const r=b.getBoundingClientRect(); return r.width>=44 && r.height>=44 && r.left>=0 && r.right<=innerWidth;
        })''')
        page.screenshot(path=str(shots / f'share-links-{width}.png'))
    assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()') == before
    frame.evaluate('''() => {Object.defineProperty(navigator,'clipboard',{configurable:true,
      value:{writeText:()=>new Promise(resolve=>{window.finishCopy=resolve})}})}''')
    button.click()
    assert button.get_attribute('aria-busy') == 'true'
    frame.locator('#share-close').click()
    frame.evaluate('window.finishCopy()')
    wait(frame, '!document.querySelector(".share-copy-link[data-link=document]").hasAttribute("aria-busy")')
    wait(frame, 'document.getElementById("share-copy-status").textContent === ""')
    frame.evaluate('''() => {document.execCommand=window.originalCopy;
      Object.defineProperty(navigator,'clipboard',{configurable:true,value:window.originalClipboard});}''')
    frame.locator('#share').click()
    wait(frame, 'document.getElementById("share-title").textContent.startsWith("Sent")')

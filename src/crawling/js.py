# JavaScript injected into Playwright pages during crawling.
# Inspired by Skyvern's domUtils.js element-marking approach.

MARK_ELEMENTS = """
() => {
    document.querySelectorAll('[data-signals-overlay]').forEach(e => e.remove());
    document.querySelectorAll('[data-signals-id]').forEach(e => e.removeAttribute('data-signals-id'));
    const sx = window.pageXOffset, sy = window.pageYOffset;
    const vw = window.innerWidth, vh = window.innerHeight;
    const tags = 'div,section,article,main,aside,p,h1,h2,h3,h4,h5,h6,span,td,th,li,header,footer,nav';

    // Collect all visible elements with meaningful text
    const all = [];
    for (const el of document.querySelectorAll(tags)) {
        const r = el.getBoundingClientRect();
        if (r.bottom <= 0 || r.top >= vh || r.right <= 0 || r.left >= vw) continue;
        if (r.width < 30 || r.height < 12) continue;
        const text = (el.innerText || '').trim().replace(/\\s+/g, ' ');
        if (text.length < 3) continue;
        all.push({el, r, text});
    }

    // Mark which candidates have a visible candidate descendant (i.e. are containers)
    const candidateEls = new Set(all.map(c => c.el));
    const hasVisibleDescendant = new Set();
    for (const {el} of all) {
        let p = el.parentElement;
        while (p) {
            if (candidateEls.has(p)) hasVisibleDescendant.add(p);
            p = p.parentElement;
        }
    }

    // Label only leaf elements (no visible candidate descendants)
    const results = [];
    let n = 1;
    for (const {el, r, text} of all) {
        if (hasVisibleDescendant.has(el)) continue;
        el.setAttribute('data-signals-id', n);
        const box = document.createElement('div');
        box.setAttribute('data-signals-overlay', '');
        box.style.cssText = 'position:absolute;left:' + (r.left+sx) + 'px;top:' + (r.top+sy) +
            'px;width:' + r.width + 'px;height:' + r.height +
            'px;border:2px solid #0057FF;pointer-events:none;z-index:2147483646';
        document.body.appendChild(box);
        const lbl = document.createElement('div');
        lbl.setAttribute('data-signals-overlay', '');
        lbl.textContent = n;
        lbl.style.cssText = 'position:absolute;left:' + (r.left+sx) + 'px;top:' + (r.top+sy) +
            'px;background:#0057FF;color:#fff;font:bold 11px/16px monospace;' +
            'padding:0 3px;pointer-events:none;z-index:2147483647';
        document.body.appendChild(lbl);
        results.push({id: n, tag: el.tagName.toLowerCase(), text: text.slice(0, 80)});
        if (++n > 50) break;
    }
    return results;
}
"""

REMOVE_OVERLAYS = "() => { document.querySelectorAll('[data-signals-overlay]').forEach(e => e.remove()); }"

CLEAN_ALL = """
() => {
    document.querySelectorAll('[data-signals-overlay]').forEach(e => e.remove());
    document.querySelectorAll('[data-signals-id]').forEach(e => e.removeAttribute('data-signals-id'));
}
"""

ACCEPT_COOKIES = """
() => {
    const terms = [
        'accept all cookies', 'accept all', 'accept cookies', 'allow all cookies',
        'allow all', 'agree to all', 'i agree', 'got it', 'ok, got it',
        'accept', 'agree', 'allow', 'consent'
    ];
    const candidates = document.querySelectorAll('button, a, [role="button"], input[type="submit"]');
    for (const el of candidates) {
        const text = (el.innerText || el.value || el.textContent || '').trim().toLowerCase();
        if (terms.some(t => text === t || text.startsWith(t + ' '))) {
            el.click();
            return true;
        }
    }
    const attrSelectors = [
        '[id*="cookie-accept"]', '[id*="accept-cookie"]', '[id*="consent-accept"]',
        '[class*="cookie-accept"]', '[class*="accept-cookie"]', '[class*="consent-accept"]',
        '[data-testid*="accept"]', '[aria-label*="Accept all"]', '[aria-label*="accept all"]'
    ];
    for (const sel of attrSelectors) {
        const el = document.querySelector(sel);
        if (el) { el.click(); return true; }
    }
    return false;
}
"""

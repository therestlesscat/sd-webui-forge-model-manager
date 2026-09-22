// Load _mm_common.js against a minimal DOM stub and compare its output with the
// original implementations taken from git HEAD.
const fs = require('fs');
const vm = require('vm');
const { execSync } = require('child_process');

const path = require('path');

// The extension, found from this file rather than from a drive letter, so the
// suite runs wherever the repository happens to be checked out.
const REPO = path.resolve(__dirname, '..', '..').replace(/\\/g, '/');

function makeElement() {
    const el = {
        _text: '',
        set textContent(v) { this._text = String(v); },
        get textContent() { return this._text; },
        get innerHTML() {
            return this._text
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');
        },
    };
    return el;
}

const sandbox = {
    console,
    document: { createElement: makeElement, readyState: 'complete' },
    setTimeout,
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(REPO + '/javascript/shared/common.mjs', 'utf8')
    .replace(/^export /gm, ''), sandbox);
const C = sandbox;
sandbox.IMAGE_PAGE_SIZE = 100;  // the originals read this from their own closure

// Original implementations, pulled straight out of the pre-refactor model_manager.js.
const orig = execSync('git -C "' + REPO + '" show 8299a83:javascript/model_manager.js', {
    encoding: 'utf8', maxBuffer: 64 * 1024 * 1024,
});

function lift(name) {
    const m = orig.match(new RegExp('^[ \\t]*(?:async )?function ' + name + '\\s*\\(', 'm'));
    let i = orig.indexOf('(', m.index + m[0].length - 1);
    let depth = 0;
    for (;; i++) {
        if (orig[i] === '(') depth++;
        else if (orig[i] === ')' && --depth === 0) break;
    }
    i = orig.indexOf('{', i);
    const start = i;
    depth = 0;
    for (;; i++) {
        if (orig[i] === '{') depth++;
        else if (orig[i] === '}' && --depth === 0) break;
    }
    const body = orig.slice(start, i + 1);
    const params = orig.slice(orig.indexOf('(', m.index), start);
    return vm.runInContext('(function' + params + body + ')', sandbox);
}

let failures = 0;

// Dropping the IIFE moved every line four spaces left, which also moved the
// literal whitespace inside multi-line template strings. That whitespace only
// ever sits between tags, where HTML collapses it - the one pre-wrap cell in
// the stylesheet holds interpolated data, not source indentation. So markup is
// compared with runs of whitespace normalised.
function normalise(v) {
    return typeof v === 'string' && v.includes('<')
        ? v.replace(/\s+/g, ' ').trim()
        : v;
}

function check(label, got, want) {
    got = normalise(got); want = normalise(want);
    const ok = JSON.stringify(got) === JSON.stringify(want);
    if (!ok) { failures++; console.log('FAIL ' + label + '\n  got  ' + JSON.stringify(got) + '\n  want ' + JSON.stringify(want)); }
    return ok;
}

// escapeHtml / formatNumber / isVideoUrl / getImagePageCount / renderResource
const escapeHtmlOrig = lift('escapeHtml');
sandbox.escapeHtml = escapeHtmlOrig;  // renderResource calls it from its own closure
for (const s of ['', 'plain', '<b>x</b>', 'a & b', null, 'quote "x"']) {
    check('escapeHtml ' + JSON.stringify(s), C.escapeHtml(s), escapeHtmlOrig(s));
}

const formatNumberOrig = lift('formatNumber');
for (const n of [0, 1, 999, 1000, 1500, 999999, 1000000, 2500000, null, undefined]) {
    check('formatNumber ' + n, C.formatNumber(n), formatNumberOrig(n));
}

const isVideoUrlOrig = lift('isVideoUrl');
const urls = [['', undefined], ['a.mp4', undefined], ['a.png', 'video'], ['a.WEBM', undefined],
              ['x/a.mp4?width=9', undefined], ['a.jpg', undefined], [null, undefined]];
for (const [u, t] of urls) check('isVideoUrl ' + u + '/' + t, C.isVideoUrl({ url: u, type: t }), isVideoUrlOrig(u, t));

const pageCountOrig = lift('getImagePageCount');
for (const n of [0, 1, 99, 100, 101, 250, 1000]) {
    check('getImagePageCount ' + n, C.getImagePageCount(n), pageCountOrig(n));
}

const renderResourceOrig = lift('renderResource');
const resources = [
    { type: 'lora', name: 'Foo', weight: 0.8 },
    { type: 'LORA', name: '<bad>' },
    { type: 'vae', name: 'V' },
    { type: 'embedding', name: 'E', weight: 0 },
    { type: 'ti', name: 'T' },
    { type: 'checkpoint', name: 'C' },
    {},
];
for (const r of resources) {
    check('renderResource ' + JSON.stringify(r), C.renderResource(r), renderResourceOrig(r));
}

// renderImagePagination: the shared version with prefix 'mm' must equal the original,
// which read currentImagePage from its closure.
const paginationOrig = (() => {
    const src = orig.slice(orig.indexOf('    function renderImagePagination'));
    const wrapper = 'var currentImagePage; (function(){ ' +
        src.slice(0, matchEnd(src)) +
        ' ; window.__pag = function(p, t, pos){ currentImagePage = p; return renderImagePagination(t, pos); }; })()';
    vm.runInContext(wrapper, sandbox);
    return sandbox.__pag;

    function matchEnd(s) {
        let i = s.indexOf('{', s.indexOf(')')), depth = 0;
        for (;; i++) {
            if (s[i] === '{') depth++;
            else if (s[i] === '}' && --depth === 0) return i + 1;
        }
    }
})();

for (const total of [0, 1, 2, 5, 6, 12, 40]) {
    for (const cur of [1, 2, 3, 7, 40]) {
        for (const pos of ['top', 'bottom']) {
            check(`pagination cur=${cur} total=${total} ${pos}`,
                  C.renderImagePagination({ currentPage: cur, totalPages: total, position: pos, prefix: 'mm' }),
                  paginationOrig(cur, total, pos));
        }
    }
}

// The 'cb' prefix must differ from 'mm' only in the handler names.
const mm = C.renderImagePagination({ currentPage: 3, totalPages: 12, position: 'bottom', prefix: 'mm' });
const cb = C.renderImagePagination({ currentPage: 3, totalPages: 12, position: 'bottom', prefix: 'cb' });
check('cb prefix rewrite', cb, mm.replace(/window\.mm/g, 'window.cb'));

console.log(failures === 0 ? '\nAll checks passed.' : `\n${failures} check(s) failed.`);
process.exit(failures === 0 ? 0 : 1);

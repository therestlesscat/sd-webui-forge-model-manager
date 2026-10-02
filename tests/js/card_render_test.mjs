// The model card, the page strip and the grid, drawn once for both tabs and
// the settings window's previews (renderModelCard, renderGridPagination,
// renderModelGrid in shared/grid.mjs). They take what to show and read no
// setting; the tabs' adapters are exercised by the tab suites.
//
// Each tab drew its own before, and the copies had drifted: the Civitai
// Browser wrote a model's type into the page unescaped, and both cut a name
// to 30 characters after escaping it, so "&amp;" could be cut to "&am".
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, done } = checker();
const shared = await import(`file:///${ROOT}/javascript/shared/grid.mjs`);
const { renderModelCard, renderGridPagination, renderModelGrid, CARD_PLACEHOLDER } = shared;

function parse(html) {
    const box = document.createElement('div');
    box.innerHTML = html;
    return box.firstElementChild;
}

// ------------------------------------------------------------------ a card
const card = parse(renderModelCard({
    index: 3,
    onclick: 'window.mmSelectModel(3)',
    name: 'A Model',
    media: { src: 'https://example.invalid/a.jpeg', video: false },
    classes: ['has-civitai', '', 'nsfw-x'],
    data: { 'model-id': 77 },
    overlays: [{ cls: 'mm-bookmark-indicator', text: '★', title: 'Bookmarked' },
               { cls: 'mm-pin-btn', text: '📌', title: 'Pin', onclick: 'window.mmTogglePin(3)' }],
    badges: [{ cls: 'type-badge', text: 'LORA' }, { cls: 'versions-badge', text: 'v2', title: '2 local versions' }],
    stats: [{ text: '1.2 GB' }, { html: '<span class="thumbs">+5</span>' }, { text: '↓ 3K', title: 'Downloads' }],
}));
check('a card, with its classes and no empty one',
      card.getAttribute('class'), 'model-card has-civitai nsfw-x');
check('its place, its data and its click',
      [card.getAttribute('data-index'), card.getAttribute('data-model-id'), card.getAttribute('onclick')],
      ['3', '77', 'window.mmSelectModel(3)']);
const img = card.querySelector('.model-card-image img');
check('its image, lazily, falling back to the placeholder',
      [img.getAttribute('src'), img.getAttribute('loading'), img.getAttribute('data-placeholder'),
       img.getAttribute('onerror')],
      ['https://example.invalid/a.jpeg', 'lazy', CARD_PLACEHOLDER, 'window.mmMediaFallback(this)']);
check('overlays on the image',
      Array.from(card.querySelectorAll('.model-card-image > div')).map((o) => [o.className, o.textContent, o.getAttribute('title')]),
      [['mm-bookmark-indicator', '★', 'Bookmarked']]);
const pin = card.querySelector('.model-card-image > button');
check('one with a click is a button, whose click is not the card\'s',
      [pin?.className, pin?.textContent, pin?.getAttribute('type'), pin?.getAttribute('onclick')],
      ['mm-pin-btn', '📌', 'button', 'event.stopPropagation(); window.mmTogglePin(3)']);
check('badges under the name',
      Array.from(card.querySelectorAll('.model-card-meta .badge')).map((b) => [b.className, b.textContent, b.getAttribute('title')]),
      [['badge type-badge', 'LORA', null], ['badge versions-badge', 'v2', '2 local versions']]);
check('the stats row, with a helper\'s own markup kept',
      [Array.from(card.querySelectorAll('.model-card-stats > span')).map((s) => s.textContent),
       card.querySelector('.model-card-stats > span[title]')?.getAttribute('title')],
      [['1.2 GB', '+5', '↓ 3K'], 'Downloads']);
check('the name, and in full on hover',
      [card.querySelector('.model-card-name').textContent, card.querySelector('.model-card-name').getAttribute('title')],
      ['A Model', 'A Model']);

const video = parse(renderModelCard({ index: 0, onclick: 'x()', name: 'V',
                                      media: { src: 'https://example.invalid/v.mp4', video: true } }));
check('a video plays, muted, in a loop', ['loop', 'muted', 'autoplay', 'playsinline']
    .map((a) => video.querySelector('video')?.hasAttribute(a)), [true, true, true, true]);
const bare = parse(renderModelCard({ index: 0, onclick: 'x()', name: '' }));
check('no image shows the placeholder, and no name is Unknown',
      [bare.querySelector('img').getAttribute('src'), bare.querySelector('.model-card-name').textContent],
      [CARD_PLACEHOLDER, 'Unknown']);

// ------------------------------------------------------------- escaping
const HOSTILE = '<img src=x onerror="alert(1)">';
const hostile = parse(renderModelCard({
    index: 1, onclick: 'window.cbOpenModel(1)', name: HOSTILE,
    media: { src: 'https://example.invalid/"><script>', video: false },
    data: { 'model-id': '"><b>' },
    overlays: [{ cls: 'cb-paid-badge', text: HOSTILE, title: '" onmouseover="alert(1)' }],
    badges: [{ cls: 'type-badge', text: HOSTILE }],
    stats: [{ text: HOSTILE, title: '"><i>' }],
}));
check('nothing a model is called or labelled becomes markup',
      hostile.querySelectorAll('script, b, i, img[onerror="alert(1)"], [onmouseover]').length, 0);
check('it is shown as written instead',
      [hostile.querySelector('.type-badge').textContent, hostile.querySelector('.cb-paid-badge').textContent,
       hostile.querySelector('.model-card-stats span').textContent],
      [HOSTILE, HOSTILE, HOSTILE]);

// A name is cut to 30 characters, then escaped - not escaped, then cut.
const long = 'A'.repeat(28) + '& B, and more';
const cut = parse(renderModelCard({ index: 0, onclick: 'x()', name: long }));
check('a long name is cut at 30 characters, and an entity never in half',
      [cut.querySelector('.model-card-name').textContent, cut.querySelector('.model-card-name').getAttribute('title')],
      ['A'.repeat(28) + '& ...', long]);

// ------------------------------------------------------------ the page strip
function strip(p) {
    const el = parse(renderGridPagination({ goTo: 'goTo', prev: 'prev', next: 'next', ...p }));
    const [prev, next] = el.querySelectorAll('.mm-page-btn');
    return {
        pages: Array.from(el.querySelectorAll('.mm-page-numbers > *')).map((x) => x.textContent.trim()),
        active: el.querySelector('.mm-page-num.active')?.textContent,
        prev: !prev.hasAttribute('disabled'),
        next: !next.hasAttribute('disabled'),
        calls: [el.querySelector('.mm-page-num')?.getAttribute('onclick'), prev.getAttribute('onclick'),
                next.getAttribute('onclick')],
    };
}
// The Model Manager knows its last page.
check('a known last page: five around the current, the first and last beyond',
      strip({ current: 10, last: 42, hasNext: true }),
      { pages: ['1', '...', '8', '9', '10', '11', '12', '...', '42'], active: '10', prev: true, next: true,
        calls: ['window.goTo(1)', 'window.prev()', 'window.next()'] });
check('on page 1, Prev is disabled', strip({ current: 1, last: 42, hasNext: true }).prev, false);
check('on the last page, Next is disabled',
      strip({ current: 42, last: 42, hasNext: false }).pages.concat(String(strip({ current: 42, last: 42, hasNext: false }).next)),
      ['1', '...', '38', '39', '40', '41', '42', 'false']);
// The Civitai Browser knows only how far it has been, and whether there is more.
check('an unknown last page: only the pages there are, Next while there is more',
      strip({ current: 4, last: 4, hasNext: true }),
      { pages: ['1', '2', '3', '4'], active: '4', prev: true, next: true,
        calls: ['window.goTo(1)', 'window.prev()', 'window.next()'] });
check('and Next disabled once there is no more', strip({ current: 4, last: 4, hasNext: false }).next, false);
check('back on an earlier page, the pages already been to stay',
      strip({ current: 2, last: 9, hasNext: true }).pages, ['1', '2', '3', '4', '5', '...', '9']);

// ------------------------------------------------------------------- a grid
const grid = document.createElement('div');
grid.id = 'test_grid';
document.body.appendChild(grid);
renderModelGrid({ gridId: 'test_grid', cards: [], empty: 'No <models> found.' });
check('no cards: a line saying so, escaped', grid.querySelector('.model-grid-empty')?.textContent, 'No <models> found.');
renderModelGrid({ gridId: 'test_grid', cards: [renderModelCard({ index: 0, onclick: 'x()', name: 'One' })],
                  empty: 'none', pagination: '<div class="mm-pagination"></div>' });
check('cards: the list, then the page strip',
      Array.from(grid.children).map((c) => c.className), ['model-grid-inner', 'mm-pagination']);

done();

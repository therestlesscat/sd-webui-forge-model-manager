// A gallery's pages, one way for both tabs (#115). The Model Manager and the
// Civitai Browser each kept their gallery's pages - the images, the pages, a
// page's error, a Load More under way - and drew them, added the next page,
// and redrew the banner and the foot, each in its own code. The copies had
// drifted: one left out an empty card, the other did not.
//
// Here: the paging markup is written in one place, and the one object both
// tabs page with keeps its pages, draws them, adds one without drawing the
// others again, and runs Load More once at a time, saying why a page did not
// come.
import { readdirSync, readFileSync } from 'node:fs';
import { ROOT, checker, mountTab } from './harness.mjs';

const { document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

// ------------------------------------------------- written in one place
const files = [...readdirSync(`${ROOT}/javascript`).filter((f) => f.endsWith('.mjs')),
               ...readdirSync(`${ROOT}/javascript/shared`).filter((f) => f.endsWith('.mjs')).map((f) => `shared/${f}`)];
const writing = (pattern) => files.filter((f) => pattern.test(readFileSync(`${ROOT}/javascript/${f}`, 'utf8'))).sort();
check('the Load More button is written once', writing(/Load More Images/), ['shared/gallery.mjs']);
check('and a page - its separator, its cards, its note - once',
      writing(/pageSeparator\(page\.number\) : ''\) \+ cards \+ pageNoteHtml\(page\)/),
      ['shared/gallery.mjs']);

// The tabs keep no pages of their own any more: their old names, anywhere
// but a comment - a spread of one was missed once, and only ran at runtime.
const code = (f) => readFileSync(`${ROOT}/javascript/${f}`, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1');
check('the tabs keep no pages of their own',
      ['model_manager.mjs', 'civitai_browser.mjs'].filter((f) =>
          /(?<![\w$.])(currentImages|imagePages|pageRequestError|loadingImagePage)\b|\.\.\.(currentImages|imagePages)\b/.test(code(f))),
      []);

// ---------------------------------------------------------- the object
const { createPagedGallery } = await import(`file:///${ROOT}/javascript/shared/gallery.mjs`);
document.body.insertAdjacentHTML('beforeend', '<div id="paging_test"></div>');
const box = document.getElementById('paging_test');
const drawnAfter = [];
let redraws = 0;
const banner = () => `<div class="test-banner">${gallery.images.length} loaded</div>`;
const gallery = createPagedGallery({
    containerId: 'paging_test', bannerClass: 'test-banner', loadMoreId: 'test_more', loadMoreCall: 'testMore',
    card: (img, index) => `<div class="test-card" data-index="${index}">${img.id}</div>`,
    bannerHtml: banner,
    redraw: () => { redraws += 1; draw(); },
    afterDraw: (images) => drawnAfter.push(images.map((img) => img.id)),
});
const draw = () => { box.innerHTML = banner() + gallery.pagesHtml(); };

gallery.take({ images: [{ id: 1 }, { id: 2 }], page: { number: 1, shown: 2, more: true } }, { append: false });
draw();
const cards = () => Array.from(box.querySelectorAll('.test-card')).map((c) => c.textContent);
check('a page is drawn: its cards and its note', [cards(), !!box.querySelector('.mm-page-note')], [['1', '2'], true]);
check('with Load More while there is a next page',
      box.querySelector('#test_more')?.getAttribute('onclick'), 'window.testMore()');

// Load More: the next page, added at the end; the first page's cards stay.
const firstCard = box.querySelector('.test-card');
let asked = 0;
const loadPage = async (number) => {
    asked += 1;
    await new Promise((resolve) => setTimeout(resolve, 20));
    const { page, images } = gallery.take({ images: [{ id: 3 }], page: { number, shown: 1, more: false } },
                                          { append: true });
    gallery.append(page, images);
};
const first = gallery.more(loadPage);
const again = gallery.more(loadPage);                  // a second click while the first loads
check('while it loads the button says so, and takes no clicks',
      [box.querySelector('#test_more')?.textContent.trim(), box.querySelector('#test_more')?.hasAttribute('disabled')],
      ['Loading...', true]);
await Promise.all([first, again]);
check('one click, one page', asked, 1);
check('the page is added at the end, the cards above left as they were',
      [cards(), box.querySelector('.test-card') === firstCard, redraws], [['1', '2', '3'], true, 0]);
check('a separator before it, and the banner and foot drawn again: no Load More after the last',
      [!!box.querySelector('.mm-page-separator'), box.querySelector('.test-banner')?.textContent,
       !!box.querySelector('#test_more')], [true, '3 loaded', false]);
check('what was drawn is told, page by page', drawnAfter, [[3]]);

// A page that does not come says why, in the foot.
gallery.pages[gallery.pages.length - 1].more = true;
gallery.refreshChrome();
await gallery.more(async () => { throw new Error('Civitai timed out'); });
check('a page that did not come says why, and Load More stays',
      [box.querySelector('.mm-images-footer .mm-page-note')?.textContent.trim(), !!box.querySelector('#test_more')],
      ['Page 3 could not be loaded: Civitai timed out', true]);

done();

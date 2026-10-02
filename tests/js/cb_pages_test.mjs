// The Civitai Browser's page numbers: only pages this search has been to.
//
// Reaching page 2 or later used to save that filter set's cursors, for a
// Resume button to go back there, and Search loaded them too: after an
// earlier visit had reached page 6, a new search offered pages 1 to 6 while
// having been to page 2. Resume is gone, and nothing is saved: every search
// starts fresh.
import { ROOT, act, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();

// Civitai: every page has one model and a cursor to the next.
globalThis.fetch = async (url) => {
    const href = String(url);
    if (!href.includes('/model-manager/civitai/models')) {
        return { ok: true, json: async () => ({ success: true }) };
    }
    const cursor = new URL(href, 'http://webui').searchParams.get('cursor') || 'c0';
    const n = Number(cursor.slice(1)) + 1;
    return { ok: true, json: async () => ({ success: true, nextCursor: `c${n}`, pageSize: 20,
        models: [{ id: n, name: `M${n}`, type: 'Checkpoint', stats: {}, creator: {},
                   modelVersions: [{ id: n * 10, images: [], files: [] }] }] }) };
};

await import(`file:///${ROOT}/javascript/civitai_browser.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => document.getElementById(id);
const pageNumbers = () => Array.from(document.querySelectorAll('#cb_grid .mm-page-num'))
    .map((b) => b.textContent.trim());
const onPage = async (n) => waitFor(`page ${n}`, () => $('cb_status').textContent.includes(`(page ${n})`));

// An earlier visit, to page 5.
$('cb_search').value = 'cats';
act('civitaiBrowser.search');
await onPage(1);
for (let page = 2; page <= 5; page++) {
    act('civitaiBrowser.nextPage');
    await onPage(page);
}
check('the earlier visit offers the pages it went to', pageNumbers(), ['1', '2', '3', '4', '5', '6']);

// The same search again, later.
act('civitaiBrowser.search');
await onPage(1);
check('a new search offers only the pages it has been to', pageNumbers(), ['1', '2']);
act('civitaiBrowser.nextPage');
await onPage(2);
check('and grows as it goes, not to where the last visit got', pageNumbers(), ['1', '2', '3']);

// There is no going back to where an earlier visit got, and nothing kept for it.
check('there is no Resume button', $('cb_resume_btn'), null);
check('and no saved position in the browser\'s storage',
      Object.keys(localStorage._d).filter((k) => k.startsWith('civitai_cursors_')), []);
check('Search is only a search: no right-click to clear a saved position',
      $('cb_search_btn').hasAttribute('oncontextmenu'), false);

done();

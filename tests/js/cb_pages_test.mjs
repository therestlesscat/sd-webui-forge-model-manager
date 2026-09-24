// The Civitai Browser's page numbers: only pages this search has been to.
//
// Reaching page 2 or later saves that filter set's cursors, so Resume can go
// back there. Search used to load them too, so after an earlier visit had
// reached page 6, a new search offered pages 1 to 6 while having been to
// page 2 - and a filtered page's saved cursor holds what the filters found
// that day, not what they find now. Search now starts fresh; the saved
// position is Resume's to offer.
import { ROOT, checker, mountTab } from './harness.mjs';

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
window.cbSearch();
await onPage(1);
for (let page = 2; page <= 5; page++) {
    window.cbNextPage();
    await onPage(page);
}
check('the earlier visit offers the pages it went to', pageNumbers(), ['1', '2', '3', '4', '5', '6']);

// The same search again, later.
window.cbSearch();
await onPage(1);
check('a new search offers only the pages it has been to', pageNumbers(), ['1', '2']);
window.cbNextPage();
await onPage(2);
check('and grows as it goes, not to where the last visit got', pageNumbers(), ['1', '2', '3']);

// Going back to where the earlier visit was is Resume's job.
window.cbSearch();
await onPage(1);
check('Resume offers the saved position', $('cb_resume_btn').textContent, 'Resume (page 2)');
window.cbResumePage();
await onPage(2);
check('and goes there', $('cb_status').textContent.includes('(page 2)'), true);

done();

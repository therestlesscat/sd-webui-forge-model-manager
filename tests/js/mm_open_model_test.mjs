// The details panel acts on the model it opened, whatever the grid loads
// after (#388).
//
// The panel remembered the open model as a place in the grid. After Next
// page, or a sync's end loading the grid again, the panel still showed model
// X while the card at its place was Y: Delete asked about Y and deleted Y's
// file, Sync synced Y, the pin pinned Y, Bookmark flipped Y's state. The
// panel now keeps the copy it opened with, and a grid load never replaces
// it: a fresh card can name a newer version than the one on screen. The
// model's key - its Civitai id, else its file - only finds its card: to mark
// it, and to keep the card's pin and star in step with the panel's.
import { ROOT, act, checker, mountTab, press, startTab, tabEntries } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
// The page first: the registry listens to it when it loads.
await import(`file:///${ROOT}/javascript/shared/calls.mjs`);
const { check, waitFor, done } = checker();

const record = (id, modelId, name, over = {}) => ({
    id, model_id: modelId, name, display_name: name, version_name: 'v1', base_model: 'SDXL 1.0',
    model_type: 'LORA', file_path: `C:/models/${name}.safetensors`, file_name: `${name}.safetensors`,
    file_size: 1, nsfw_level: 1, has_civitai_data: true, local_version_count: 1, trained_words: [], tags: [],
    is_pinned: false, is_bookmarked: false, ...over,
});
const X = () => record(101, 11, 'Model X');
const Y = () => record(201, 12, 'Model Y');
const Z = () => record(301, 13, 'Model Z');
const W = () => record(401, 14, 'Model W');

// What the server holds, per section: the grid's pages, each model's local
// versions and the versions Civitai lists, in the answer's own shape.
let pages = {};
let versionsOf = {};
let listedOf = {};
let afterSync = null;       // the pages the grid answers once a sync has been posted
let holdNextGrid = false;   // the next grid answer waits for release()
let release = null;
const gridAsked = [];
const deleted = [];
const pins = [];
const bookmarks = [];
const syncs = [];
const progress = [];
let syncAnswer = { success: true, synced_count: 1, total_versions: 1 };

const gridAnswer = (href) => {
    const params = new URL(href, 'http://webui').searchParams;
    gridAsked.push(params);
    const search = params.get('search') || '';
    const all = Object.values(pages).flat();
    if (search) {
        const id = Number(search.replace(/^model:/, ''));
        const found = all.filter((m) => m.model_id === id);
        return { success: true, total: found.length, page: 1, page_size: 2, models: found };
    }
    const page = Number(params.get('page') || 1);
    return { success: true, total: all.length, page, page_size: 2, models: pages[page] || [] };
};

globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    // A copy, as an answer off the network is: the page changes what it is given.
    const reply = (body) => ({ ok: true, json: async () => structuredClone(body) });
    const form = () => Object.fromEntries(new URLSearchParams(String(init.body || '')));
    if (href.includes('/models/delete')) {
        deleted.push(form().path);
        return reply({ success: true, deleted: [form().path] });
    }
    if (href.includes('/model-manager/pin')) { pins.push(form()); return reply({ success: true }); }
    if (href.includes('/model-manager/bookmark')) { bookmarks.push(form()); return reply({ success: true }); }
    if (href.includes('/models/force-sync')) {
        syncs.push(form());
        if (afterSync) pages = afterSync;
        return reply(syncAnswer);
    }
    if (href.includes('/sync/estimate')) {
        return reply({ success: true, estimate: { versions: 1, image_options: {
            page: 100, first: { requests: 1, prompts: 4, images: 100 },
            kept: { requests: 4, prompts: 12, images: 350 }, deletes: { images: 250, versions: 1 } } } });
    }
    if (href.includes('/civitai/download/progress')) return reply({ success: true, downloads: progress });
    if (href.includes('/civitai/download')) {
        progress.push({ model_id: 11, version_id: 102, file_id: 9102, file_name: 'Model X v2.safetensors',
                        status: 'downloading', percent: 40, downloaded_bytes: 400, total_bytes: 1000, synced: false });
        return reply({ success: true, progress: progress[0] });
    }
    if (href.includes('/models/versions')) {
        const id = Number(new URL(href, 'http://webui').searchParams.get('model_id'));
        return reply({ success: true, versions: versionsOf[id] || [], civitai_versions: listedOf[id] || [] });
    }
    if (href.includes('/models/details')) return reply({ success: true, model: { images: [] } });
    if (href.includes('/model-manager/models')) {
        if (holdNextGrid) {
            holdNextGrid = false;
            await new Promise((resolve) => { release = resolve; });
        }
        return reply(gridAnswer(href));
    }
    return reply({ success: true });
};

// The Delete question, answered Delete as soon as it opens, its words kept.
let confirmText = '';
const elementProto = Object.getPrototypeOf(Object.getPrototypeOf(document.createElement('div')));
const showModal = elementProto.showModal;
elementProto.showModal = function answerDelete() {
    showModal.call(this);
    if (!this.classList.contains('mm-model-delete-dialog')) return;
    confirmText = this.textContent.replace(/\s+/g, ' ');
    setTimeout(() => this.querySelector('[data-value="true"]')
        ?.dispatchEvent(new window.Event('click', { bubbles: true })), 0);
};

await startTab('modelManager');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const cards = () => Array.from(document.querySelectorAll('#mm_grid .model-card'));
const header = () => document.querySelector('#mm_details .detail-header');
const title = () => header()?.querySelector('h3')?.textContent.trim();
const status = () => document.getElementById('mm_status')?.textContent.trim();
const panelPin = () => document.querySelector('#mm_details .mm-pin-toggle');
const star = () => header()?.querySelector('[data-action="modelManager.toggleBookmark"]');
const marked = () => cards().filter((c) => c.classList.contains('selected')).map((c) => c.dataset.index);
// A header button by its label, pressed. A Delete starts from nothing sent
// and nothing asked, so a press that deletes nothing fails its check rather
// than reading the last one's; a button not drawn fails a check rather than
// ending the suite.
async function pressLabelled(label) {
    const button = Array.from(header()?.querySelectorAll('button') || []).find((b) => b.textContent.trim() === label);
    if (!button) {
        check(`the header draws ${label}`, false, true);
        return;
    }
    deleted.length = 0;
    confirmText = '';
    await press(button);
}

/** A promise waited for as a check: a break that leaves it pending fails, and the suite goes on. */
async function settled(label, promise) {
    let ended = false;
    promise.then(() => { ended = true; }, () => { ended = true; });
    await waitFor(label, () => ended, 200);
}

/** The grid loaded afresh, as Load Models does, and settled. */
async function load() {
    const asked = gridAsked.length;
    document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
    await waitFor('the grid', () => gridAsked.length > asked && cards().length > 0);
    await new Promise((resolve) => setTimeout(resolve, 0));
}

/** Next page, and the grid settled on it. */
async function nextPage() {
    const asked = gridAsked.length;
    act('modelManager.nextPage');
    await waitFor('page 2', () => gridAsked.length > asked && cards()[0]?.textContent.includes('Model Z'));
}

/** A fresh start: page 1 of X and Y, page 2 of Z and W, and the first card opened. */
async function openFirst(over = {}) {
    // A jump from another tab leaves its query in the search box.
    document.getElementById('mm_search').value = '';
    pages = { 1: [X(), Y()], 2: [Z(), W()], ...over.pages };
    versionsOf = { 11: [X()], 12: [Y()], 13: [Z()], 14: [W()], ...over.versions };
    listedOf = over.listed || {};
    await load();
    await act('modelManager.selectModel', { index: Number(over.index || 0) });
    await waitFor('the panel', () => !!header());
}

/** A model's Sync, its image-count question answered Sync. */
async function syncNow() {
    const question = () => document.querySelector('.mm-image-count-dialog');
    const syncing = act('modelManager.syncModel');
    await waitFor('the question', () => !!question());
    question().querySelector('[data-value="true"]').dispatchEvent(new window.Event('click', { bubbles: true }));
    await settled('the sync to end', syncing);
}

// ------------------------------------------------- after a page change
await openFirst();
await nextPage();
check('the panel still shows X on page 2', title(), 'Model X');
await pressLabelled('Delete Model');
check('Delete on page 2 asks about X, not the card now at its place',
      confirmText.includes('"Model X"'), true);
check('and sends X\'s file', deleted.at(-1), 'C:/models/Model X.safetensors');

const two = { 11: [X(), record(102, 11, 'Model X', { version_name: 'v2', file_path: 'C:/models/x2.safetensors',
                                                    file_name: 'x2.safetensors' })] };
await openFirst({ versions: two });
await nextPage();
await pressLabelled('Delete Current Model Version');
check('with two versions here, it names X and its version shown',
      [confirmText.includes('version "v1" of "Model X"'), deleted.at(-1)], [true, 'C:/models/Model X.safetensors']);

await openFirst();
await nextPage();
await press(panelPin());
check('the panel\'s pin pins X, by its id, and shows it', [pins.at(-1), panelPin()?.classList.contains('pinned')],
      [{ pinned: 'true', model_id: '11' }, true]);

await openFirst({ pages: { 1: [X(), Y()].map((m, i) => (i === 0 ? { ...m, is_bookmarked: true } : m)) } });
await nextPage();
await press(star());
check('the star sends X\'s own state flipped, not the card\'s now at its place',
      [bookmarks.at(-1), star()?.textContent.trim()], [{ model_id: '11', bookmarked: 'false' }, '☆']);

await openFirst();
await nextPage();
await syncNow();
check('Sync syncs X, and the panel stays on X', [syncs.at(-1)?.model_id, title()], ['11', 'Model X']);

// ------------------------------------------------- a reload of the same page
await openFirst({ index: 1 });
pages = { 1: [Y(), X()], 2: [Z(), W()] };
await load();
await pressLabelled('Delete Model');
check('X and Y swapped by a reload: Delete still asks about Y, the model open, and sends its file',
      [confirmText.includes('"Model Y"'), deleted.at(-1)], [true, 'C:/models/Model Y.safetensors']);

// A newer version of X reached the library from elsewhere - a sync, the
// other WebUI - and the reload's card names its file. The panel, not
// redrawn, still shows the one it opened.
await openFirst();
pages = { 1: [record(102, 11, 'Model X', { file_path: 'C:/models/x2.safetensors', local_version_count: 2 }), Y()] };
await load();
await pressLabelled('Delete Model');
check('a fresh card naming a newer file: Delete sends the file the panel shows',
      deleted.at(-1), 'C:/models/Model X.safetensors');

await openFirst();
pages = { 1: [Y(), X()], 2: [Z(), W()] };
await load();
check('the open model\'s card is marked again after a reload, at its new place', marked(), ['1']);
await act('modelManager.togglePin', { index: 1 });
check('and its card\'s pin, pressed there, shows in the panel too',
      [pins.at(-1), panelPin()?.classList.contains('pinned')], [{ pinned: 'true', model_id: '11' }, true]);

// ------------------------------------------------- the other tab's cards
// The Civitai Browser marks its open card the same way: a card of its own
// before this grid stands in for it.
document.body.insertAdjacentHTML('afterbegin', '<div class="model-card selected" data-index="0" id="other-tab-card"></div>');
const other = () => document.getElementById('other-tab-card');
await openFirst();
check('opening a model leaves the other tab\'s marked card alone, and marks its own',
      [other().classList.contains('selected'), marked()], [true, ['0']]);
act('modelManager.closeDetails');
check('and closing the panel too, clearing only its own', [other().classList.contains('selected'), marked()], [true, []]);
other().remove();

// ------------------------------------------------- the card's star (#399)
await openFirst();
const cardStar = () => cards()[0]?.querySelector('.mm-bookmark-indicator');
await press(star());
check('Bookmark puts the star on the model\'s card at once', [bookmarks.at(-1)?.bookmarked, !!cardStar()], ['true', true]);
await press(star());
check('and takes it off again', [bookmarks.at(-1)?.bookmarked, !!cardStar()], ['false', false]);

// ------------------------------------------------- after a model's Sync
await openFirst();
afterSync = { 1: [record(101, 11, 'Model X renamed'), Y()], 2: [Z(), W()] };
await syncNow();
afterSync = null;
await waitFor('the reopen', () => title() === 'Model X renamed');
check('after its Sync the panel shows the synced record', title(), 'Model X renamed');

await openFirst();
syncAnswer = { success: true, synced_count: 1, total_versions: 2, errors: ['b.safetensors: Server error: 503'] };
await syncNow();
check('the Sync\'s line, failures and all, is what the status says after the reload',
      status(), 'Synced 1 of 2 files from Civitai; 1 failed: b.safetensors: Server error: 503');
syncAnswer = { success: true, synced_count: 1, total_versions: 1 };

await openFirst();
holdNextGrid = true;
document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the held load', () => release !== null);
afterSync = { 1: [record(101, 11, 'Model X renamed again'), Y()], 2: [Z(), W()] };
const question = () => document.querySelector('.mm-image-count-dialog');
const syncsBefore = syncs.length;
const syncing = act('modelManager.syncModel');
await waitFor('the question', () => !!question());
question().querySelector('[data-value="true"]').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the sync', () => syncs.length > syncsBefore);
// The held load is counted once released; the Sync's own reload after it.
const asked = gridAsked.length;
release();
release = null;
await settled('the sync to end', syncing);
afterSync = null;
await waitFor('the reopen', () => title() === 'Model X renamed again', 100);
check('a Sync ending while another load runs waits for it, then loads the page again',
      [gridAsked.length - asked, title()], [2, 'Model X renamed again']);

// ------------------------------------------------- a download landing
// X's other version, started from the panel, lands after a page change.
const listed = [
    { id: 102, name: 'v2', baseModel: 'SDXL 1.0', publishedAt: '2026-02-01', local: false, paid_access: null,
      files: [{ id: 9102, name: 'Model X v2.safetensors', sizeKB: 1024, type: 'Model', primary: true }] },
    { id: 101, name: 'v1', baseModel: 'SDXL 1.0', publishedAt: '2026-01-01', local: true, paid_access: null, files: [] },
];
await openFirst({ listed: { 11: listed } });
const pill = (name) => Array.from(document.querySelectorAll('#mm_details .mm-version-pill'))
    .find((p) => p.textContent.trim().startsWith(name));
await press(pill('v2'));
await press(document.getElementById('mm_download_btn'));
await nextPage();
versionsOf[11] = [X(), record(102, 11, 'Model X', { version_name: 'v2', file_path: 'C:/models/x2.safetensors',
                                                   file_name: 'x2.safetensors', local_version_count: 2 })];
listedOf[11] = listed.map((v) => ({ ...v, local: true }));
Object.assign(progress[0], { status: 'complete', percent: 100, downloaded_bytes: 1000, synced: true });
// Both versions on disk now: the pills drop their ticks, which mark the
// downloaded ones only while some are not.
const heading = () => document.querySelector('#mm_details .mm-version-selector h4')?.textContent.trim();
await waitFor('the landing', () => heading() === 'Local Versions (2)', 200);
check('a download of X\'s other version, landing after a page change, shows in X\'s panel',
      [title(), heading()], ['Model X', 'Local Versions (2)']);
progress.length = 0;

// ------------------------------------------------- guards
await openFirst();
await (await tabEntries('model_manager.mjs')).showModel('model:14');
await waitFor('W', () => title() === 'Model W');
check('a jump from another tab opens the model it names', title(), 'Model W');

await openFirst();
await load();
await pressLabelled('Delete Model');
check('Load Models with nothing changed: Delete still sends X', deleted.at(-1), 'C:/models/Model X.safetensors');

await openFirst();
act('modelManager.closeDetails');
const before = panelPin()?.className;
await act('modelManager.togglePin', { index: 0 });
check('with the panel closed, a card\'s pin leaves the panel as it was', panelPin()?.className, before);

done();

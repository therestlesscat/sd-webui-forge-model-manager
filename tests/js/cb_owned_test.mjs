// Owned in the Civitai Browser (#188, #189, #190).
//
// The server says what the library holds: a model, a version, and which of a
// version's files - by Civitai's id - are held here (owned_files), and which
// models it lists at all (listed_locally), for Show in MM. Download is
// refused for the chosen file only: having a version's fp16 is not having its
// fp32. Where a held file's id is not known, the version's answer stands. And
// the page asks the server again - the tab shown, a model opened, a download
// done - since the library changes under a search's answer: a delete here, by
// hand, or in the other WebUI. It used to mark a downloaded version owned by
// itself, and never unmark one.
import { browserGalleryAnswer, checker, choose, mountTab, openTab, press, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();

// What a press opens, through the page's one click listener (#144).
function opens(element) {
    const opened = [];
    const before = window.open;
    window.open = (...args) => { opened.push(args); return null; };
    element?.dispatchEvent(new window.Event('click', { bubbles: true }));
    window.open = before;
    return opened;
}
const afterUpdate = [];
globalThis.onAfterUiUpdate = (callback) => afterUpdate.push(callback);
const updated = () => afterUpdate.forEach((callback) => callback());

// Forge's tab bar, the Model Manager showing.
document.body.insertAdjacentHTML('afterbegin', `
    <div id="tabs">
        <button id="tab_model_manager_tab-button" class="selected" aria-selected="true">Model Manager</button>
        <button id="tab_civitai_browser_tab-button" aria-selected="false">Civitai Browser</button>
    </div>`);
function showBrowserTab(on) {
    const [manager, browser] = document.querySelectorAll('#tabs button');
    for (const [button, selected] of [[manager, !on], [browser, on]]) {
        button.classList.toggle('selected', selected);
        button.setAttribute('aria-selected', String(selected));
    }
    updated();
}

const file = (id, name, extra = {}) => ({ id, name, sizeKB: 1024, ...extra });
const MODELS = {
    // A version of two files, its fp16 held.
    1: { id: 1, name: 'Two files', type: 'LORA', stats: {}, creator: {}, owned_locally: true, listed_locally: true,
         owned_versions: [10],
         modelVersions: [{ id: 10, name: 'v1', images: [], paid_access: null, owned_locally: true, owned_files: [11],
                           files: [file(11, 'a_fp16.safetensors', { primary: true }), file(12, 'a_fp32.safetensors')] }] },
    // In the other WebUI's folders: listed, not held.
    // Its stats as Civitai sends a model's now: no rating, no favourites.
    2: { id: 2, name: 'Theirs', type: 'LORA', creator: {}, owned_locally: false, listed_locally: true,
         stats: { downloadCount: 2869, thumbsUpCount: 310, thumbsDownCount: 0, commentCount: 2 },
         owned_versions: [],
         modelVersions: [{ id: 20, name: 'v1', images: [], paid_access: null, owned_locally: false, owned_files: [],
                           files: [file(21, 'b.safetensors', { primary: true })] }] },
    // Held through a file whose Civitai id is not known.
    3: { id: 3, name: 'No file id', type: 'LORA', stats: {}, creator: {}, owned_locally: true, listed_locally: true,
         owned_versions: [30],
         modelVersions: [{ id: 30, name: 'v1', images: [], paid_access: null, owned_locally: true, owned_files: [],
                           files: [file(31, 'c_fp16.safetensors', { primary: true }), file(32, 'c_fp32.safetensors')] }] },
    // Its v1 only in a folder Neo ignores: --esrgan-models-path replaces it (#195).
    4: { id: 4, name: 'Ignored copy', type: 'Upscaler', stats: {}, creator: {}, owned_locally: false,
         listed_locally: true, owned_versions: [], ignored_because: '--esrgan-models-path',
         modelVersions: [{ id: 40, name: 'v1', images: [], paid_access: null, owned_locally: false, owned_files: [],
                           ignored_because: '--esrgan-models-path', files: [file(41, 'x.pth', { primary: true })] },
                         { id: 42, name: 'v2', images: [], paid_access: null, owned_locally: false, owned_files: [],
                           files: [file(43, 'y.pth', { primary: true })] }] },
};

const asked = [];
let owned = null;           // the server's next answer about what is held
let progress = [];          // the downloads list it answers
globalThis.fetch = async (url) => {
    const href = String(url);
    asked.push(href);
    const answer = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/ui-options')) return answer({ success: true, webui_short_name: 'Neo' });
    if (href.includes('/civitai/owned')) return answer(owned || { success: true, models: {}, versions: {} });
    if (href.includes('/civitai/download/progress')) return answer({ success: true, downloads: progress });
    if (href.includes('/civitai/download')) {
        return answer({ success: true, progress: { version_id: 10, file_name: 'a_fp16.safetensors',
                                                   status: 'downloading', percent: 10, synced: false } });
    }
    if (href.includes('/versions/') || href.includes('/images')) return answer(browserGalleryAnswer(href, []));
    const single = href.match(/\/civitai\/models\/(\d+)/);
    if (single) return answer({ success: true, model: structuredClone(MODELS[single[1]]) });
    return answer({ success: true });
};

window.mmTiming = { poll: 60 };
await startTab('civitaiBrowser');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (selector) => document.querySelector(selector);
const details = () => $('#cb_details');
const downloadButton = () => details()?.querySelector('[data-action="civitaiBrowser.download"]');
const alreadyOwned = () => Array.from(details()?.querySelectorAll('button') || [])
    .some((b) => b.textContent.trim() === 'Already Owned');
const showInManager = () => Boolean(details()?.querySelector('[data-action="civitaiBrowser.showInModelManager"]'));
const badges = () => document.querySelectorAll('#cb_grid .cb-owned-badge').length;
const ownedAsks = () => asked.filter((u) => u.includes('/civitai/owned'));

async function show(id) {
    await openTab('civitaiBrowser', 'showModel', `model:${id}`);
    await waitFor(`model ${id}'s details`, () => details()?.textContent.includes(MODELS[id].name));
    await new Promise((r) => setTimeout(r, 30));
}

// ------------------------------------------------- one file of two (#189)
await show(1);
check('the chosen file held: Already Owned', [alreadyOwned(), Boolean(downloadButton())], [true, false]);
check('the card says Owned', badges(), 1);
choose('civitaiBrowser.selectFile', 1);
check('its other file can be downloaded, saying another is held',
      [alreadyOwned(), downloadButton()?.disabled, downloadButton()?.title, downloadButton()?.dataset.fileId],
      [false, false, 'You have another file of this version.', '12']);
choose('civitaiBrowser.selectFile', 0);
check('and back on the held one, Already Owned again', alreadyOwned(), true);

// ------------------------------- the other WebUI's file: listed, not held
await show(2);
check('a model only listed: no Owned badge, Download offered', [badges(), alreadyOwned(), Boolean(downloadButton())],
      [0, false, true]);
check('and Show in Model Manager, which lists it', showInManager(), true);
// Civitai sends no rating and no favourites now: they read "★ 0.0 (0 ratings)"
// and "0" on every model. Its votes have a row instead (#208).
const statRow = (label) => Array.from(details()?.querySelectorAll('tr') || [])
    .find((tr) => tr.querySelector('td')?.textContent.trim() === label)?.querySelectorAll('td')[1]?.textContent.trim();
check('its votes and downloads, and no rating or favourites Civitai did not send',
      [statRow('Rating'), statRow('Votes'), statRow('Downloads'), statRow('Favorites'), statRow('Comments')],
      [undefined, '▲ 310▼ 0', '2.9K', undefined, '2']);
const viewOnCivitai = Array.from(details()?.querySelectorAll('.detail-actions > *') || [])
    .find((e) => e.textContent.trim() === 'View on Civitai');
check("the details' View on Civitai is a button, and opens this version's page (#144)",
      [viewOnCivitai?.tagName, opens(viewOnCivitai)],
      ['BUTTON', [['https://civitai.com/models/2?modelVersionId=20', '_blank', 'noopener']]]);

// ------------------------------------------- a held file with no file id
await show(3);
check('held through a file of unknown id: Already Owned', alreadyOwned(), true);
choose('civitaiBrowser.selectFile', 1);
check('for either file: which one is held is not known', alreadyOwned(), true);

// ------------------------------------------ asked again (#190): opened
owned = null;
asked.length = 0;
await show(1);
await waitFor('the page to ask again on opening a model', () => ownedAsks().length > 0);
const url = new URL(ownedAsks()[0], 'http://webui');
check('opening a model asks again, for the models shown and their versions',
      [url.searchParams.get('model_ids'), url.searchParams.get('version_ids')], ['1', '10']);

// Deleted meanwhile: the server no longer holds or lists it.
const probe = () => details()?.querySelector('.model-details-content');
probe().dataset.probe = 'kept';
owned = { success: true, models: { 1: { owned: true, listed: true } }, versions: { 10: { owned: true, files: [11] } } };
asked.length = 0;
showBrowserTab(false);
showBrowserTab(true);
await waitFor('the page to ask again when its tab shows', () => ownedAsks().length > 0);
await new Promise((r) => setTimeout(r, 30));
check('an answer that changes nothing redraws nothing', probe()?.dataset.probe, 'kept');

owned = { success: true, models: { 1: { owned: false, listed: false } }, versions: { 10: { owned: false, files: [] } } };
asked.length = 0;
showBrowserTab(false);
showBrowserTab(true);
await waitFor('the page to ask again', () => ownedAsks().length > 0);
await waitFor('the answer to be drawn', () => !alreadyOwned());
check('the tab shown again: a model deleted meanwhile is no longer Owned, and can be downloaded',
      [badges(), alreadyOwned(), Boolean(downloadButton()), showInManager()], [0, false, true, false]);

// ------------------------------------- asked again (#190): a download done
progress = [{ version_id: 10, file_name: 'a_fp16.safetensors', status: 'downloading', percent: 10, synced: false }];
asked.length = 0;
if (downloadButton()) {
    press(downloadButton());
    await waitFor('the download to be followed', () => asked.some((u) => u.includes('/download/progress')));
}
owned = { success: true, models: { 1: { owned: true, listed: true } }, versions: { 10: { owned: true, files: [11] } } };
progress = [{ version_id: 10, file_name: 'a_fp16.safetensors', status: 'complete', percent: 100, synced: true }];
await waitFor('the page to ask again once it is in the library', () => ownedAsks().length > 0);
await waitFor('the answer to be drawn', () => alreadyOwned());
check('a download done: the server says what is held, and the page shows it',
      [badges(), alreadyOwned(), showInManager()], [1, true, true]);

// ---------------------- a copy in a folder this WebUI ignores (#195)
owned = null;
await show(4);
const ignoredBadge = document.querySelector('#cb_grid .cb-ignored-badge');
check('the card says Neo ignores its copy, and why, in place of Owned',
      [badges(), ignoredBadge?.textContent.trim(), ignoredBadge?.title],
      [0, 'Ignored by Neo', 'Neo does not load this folder: --esrgan-models-path replaces it']);
const pills = Array.from(details()?.querySelectorAll('.mm-version-pill') || []);
check('its version\'s pill is marked, and its tooltip says why',
      [pills[0]?.textContent.includes('\u2298'), pills[0]?.title.includes('(Ignored by Neo: --esrgan-models-path replaces its folder)'),
       pills[1]?.textContent.includes('\u2298')],
      [true, true, false]);
check('Download stays offered, saying the copy there is ignored',
      [alreadyOwned(), downloadButton()?.disabled, downloadButton()?.title],
      [false, false, 'You have a copy in a folder Neo ignores: --esrgan-models-path replaces it. '
                     + 'This downloads one Neo loads.']);

done();

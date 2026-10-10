// Every version of a model in the Model Manager, the way the Civitai Browser
// shows them.
//
// The details panel listed only the versions on disk, and none at all for a
// model with one. It now lists every version Civitai has - as recorded at the
// last sync, so without asking Civitai - with the local ones marked and a
// note that the list may be out of date. A version not downloaded shows the
// Civitai Browser's information and Download, and its download is followed in
// the downloads panel both tabs share; once it is in the library, it is shown
// as a local version.
import { ROOT, act, checker, choose, mountTab, press, startTab, openTab, tabEntries, tabMarkup } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
// The page first: the registry listens to it when it loads.
const { call, provide } = await import(`file:///${ROOT}/javascript/shared/calls.mjs`);
const { check, waitFor, done } = checker();

const local = (id, name) => ({
    id, model_id: 4001, name: 'A Model', display_name: 'A Model', version_name: name,
    base_model: 'SDXL 1.0', model_type: 'LORA', civitai_type: 'LORA', file_path: `C:/models/${name}.safetensors`,
    file_name: `${name}.safetensors`, file_size: 1, nsfw_level: 1, has_civitai_data: true,
    local_version_count: 1, trained_words: [], tags: ['style'], creator: 'someone',
    rating: 4.5, thumbs_up: 90, thumbs_down: 10, download_count: 1234,
});
const FILES = [
    { id: 9031, name: 'v3_fp32.safetensors', sizeKB: 4096, type: 'Model', metadata: { size: 'full', fp: 'fp32' } },
    { id: 9032, name: 'v3_fp16.safetensors', sizeKB: 2048, type: 'Model', primary: true, metadata: { size: 'pruned', fp: 'fp16' } },
];
// v2 is paid; whether the API key's account bought it is the server's to say (#43).
let v2Owned = false;
const listed = () => [
    { id: 503, name: 'v3', baseModel: 'SDXL 1.0', publishedAt: '2026-03-01T12:00:00.000Z', trainedWords: ['third'],
      files: FILES, local: localVersions.some((v) => v.id === 503), paid_access: null },
    { id: 502, name: 'v2', baseModel: 'SDXL 1.0', publishedAt: '2026-02-01', files: [FILES[1]],
      local: false, paid_access: { permanent: true, ends_at: null, owned: v2Owned } },
    { id: 501, name: 'v1', baseModel: 'SDXL 1.0', publishedAt: '2026-01-01', files: [], local: true, paid_access: null },
];
let localVersions = [local(501, 'v1')];
let civitaiVersions = listed;
const posted = [];
const detailsAsked = [];
const progress = [];
let refuse = null;               // an error the download request is answered with

globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    // Forge given C:/models/lora on the command line, its own folder C:/forge.
    if (href.includes('/model-manager/ui-options')) {
        return reply({ success: true, path_roots: [['--lora-dir', 'C:/models/lora'], ['', 'C:/forge']],
                       webui_short_name: 'Neo' });
    }
    if (href.includes('/civitai/download/progress')) return reply({ success: true, downloads: structuredClone(progress) });
    if (href.includes('/civitai/download')) {
        posted.push(Object.fromEntries(init.body.entries()));
        if (refuse) return reply({ success: false, error: refuse });
        progress.push({ version_id: 503, file_name: 'v3_fp32.safetensors', status: 'downloading', percent: 40,
                        downloaded_bytes: 400, total_bytes: 1000, synced: false });
        return reply({ success: true, progress: structuredClone(progress[0]) });
    }
    if (href.includes('/model-manager/models/versions')) {
        return reply({ success: true, versions: localVersions, civitai_versions: civitaiVersions(),
                       versions_synced_at: '2026-09-01T10:00:00' });
    }
    if (href.includes('/model-manager/models/details')) {
        detailsAsked.push(new URL(href).searchParams.get('path'));
        return reply({ success: true, model: { images: [], civitai_model: { description: '<p>About it</p>' } } });
    }
    if (href.includes('/model-manager/models')) {
        return reply({ success: true, total: 1, page: 1, page_size: 20, models: [localVersions[0]] });
    }
    return reply({ success: true });
};

await startTab('modelManager');
document.dispatchEvent(new window.Event('DOMContentLoaded'));
document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the grid', () => document.querySelectorAll('#mm_grid .model-card').length > 0);

const details = () => document.getElementById('mm_details');
const pills = () => Array.from(details().querySelectorAll('.mm-version-pill'));
const pillNames = () => pills().map((p) => p.textContent.trim());
const active = () => pills().filter((p) => p.classList.contains('active')).map((p) => p.textContent.trim());
const click = (el) => press(el);
const pill = (name) => pills().find((p) => p.textContent.trim().startsWith(name));
const row = (label) => Array.from(details().querySelectorAll('.detail-table tr'))
    .find((tr) => tr.querySelector('td')?.textContent.trim() === label)?.querySelectorAll('td')[1]?.textContent.trim();

// "Show in Civitai Browser" hands the Civitai Browser a query, through the
// loading module (#184): the Browser, started beside this tab, watched at its entry.
document.body.insertAdjacentHTML('beforeend', tabMarkup('model_manager/ui/tab_civitai_browser.py'));
await startTab('civitaiBrowser');
const shownInBrowser = [];
(await tabEntries('civitai_browser.mjs')).showModel = async (query) => { shownInBrowser.push(query); };
const showInBrowser = async () => {
    const buttons = details().querySelectorAll('button[data-action="modelManager.showInCivitaiBrowser"]');
    click(buttons[0]);
    await waitFor('the hop', () => shownInBrowser.length > 0, 20);
    return { query: shownInBrowser.pop(), buttons: buttons.length, inHeader:
             !!details().querySelector('.detail-header [data-action="modelManager.showInCivitaiBrowser"]'),
             firstRow: details().querySelector('.detail-table tr')?.querySelector('td[colspan="2"] button')?.textContent.trim() };
};

// ---------------------------------------------------------- the pills
await act('modelManager.selectModel', { index: 0 });
check('1. one version on disk, three on Civitai: all three, in Civitai\'s order, the local one marked',
      pillNames(), ['v3', 'v2 ⬥', 'v1 ✓']);
check('   the one on disk is the one shown', active(), ['v1 ✓']);
// Rating, Votes and Downloads, each in its row: the rating had the downloads
// in brackets, read as how many had rated it (#208).
check('   its rating, votes and downloads, each in a row of its own',
      [row('Rating'), row('Votes'), row('Downloads')], ['★ 4.5', '▲ 90▼ 10', '1.2K']);
check('   the heading counts both', details().querySelector('.mm-version-selector h4')?.textContent.trim(),
      'Versions (3, 1 downloaded)');
const note = details().querySelector('.mm-versions-note')?.textContent || '';
check('   Show in Civitai Browser sends the version on disk',
      (await showInBrowser()).query, 'model:4001 version:501');
check('2. a note says the list may be old, and how to bring it up to date',
      [note.includes('Sep 1, 2026'), note.includes('may not be up to date'),
       note.includes('Sync metadata with Civitai')], [true, true, true]);

// ------------------------------------------------ a version not downloaded
document.getElementById('mm_images').style.display = 'block';
await click(pill('v3'));
// The thumbs have a row of their own: they were the rating's "(100 ratings)" (#208).
check('3. a version not downloaded: the Civitai Browser\'s information',
      [row('Version ID'), row('Version Name'), row('Base Model'), row('Creator'), row('Published'),
       row('Rating'), row('Votes'), row('Downloads')],
      ['503', 'v3', 'SDXL 1.0', 'someone', 'Mar 1, 2026', '★ 4.5', '▲ 90▼ 10', '1.2K']);
check('   its own trigger words, and the model\'s description',
      [details().querySelector('.trigger-word')?.textContent, !!details().textContent.includes('About it')],
      ['third', true]);
check('   the primary file, and a picker for the other', [row('File'), row('File Size'),
      details().querySelectorAll('.mm-file-select option').length], ['v3_fp16.safetensors', '2.00 MB', 2]);
const button = () => document.getElementById('mm_download_btn');
const downloads = () => ['action', 'modelId', 'versionId', 'fileId'].map((key) => button()?.dataset[key]);
check('   a Download for that file', downloads(), ['modelManager.download', '4001', '503', '9032']);
check('   the pill is the one shown', active(), ['v3']);
check('   no gallery: there is no file to have fetched one for',
      document.getElementById('mm_images').style.display, 'none');
check('   and nothing to delete', details().querySelectorAll('.detail-header button.danger').length, 0);

await choose('modelManager.selectFile', '0');
check('4. picking the other file points the rows and the button at it',
      [row('File'), row('File Size'), downloads()],
      ['v3_fp32.safetensors', '4.00 MB', ['modelManager.download', '4001', '503', '9031']]);

await click(pill('v2'));
check('5. a paid version says so, and offers no Download',
      [row('Access'), !!button(), details().querySelector('.detail-actions button[disabled]')?.textContent],
      ['Paid', false, 'Paid']);
const paidLabel = () => details().querySelector('.detail-actions button[disabled]');
// View on Civitai is in the header, for whichever version is shown - a
// button, as its neighbours are, so it looks like them: a link beside them
// did not, whatever its classes.
const viewOnCivitai = () => details().querySelector('.detail-header button[data-open-url*="civitai.com/models/"]');
check('   saying why - the account has not bought it - with View on Civitai in the header, for this version',
      [/has not bought it/.test(paidLabel()?.getAttribute('title') || ''), viewOnCivitai()?.getAttribute('data-open-url')],
      [true, 'https://civitai.com/models/4001?modelVersionId=502']);

check('   Show in Civitai Browser is the table\'s first row, not in the header, and sends this version',
      await showInBrowser(), { query: 'model:4001 version:502', buttons: 1, inHeader: false,
                               firstRow: 'Show in Civitai Browser' });

await click(pill('v1'));
check('6. back to the local version: its panel, gallery and all',
      [active(), !!details().querySelector('.file-path-cell'), detailsAsked.at(-1)],
      [['v1 ✓'], true, 'C:/models/v1.safetensors']);
check('   View on Civitai in its header, for this version, and no buttons at the bottom',
      [viewOnCivitai()?.getAttribute('data-open-url') || '', !!details().querySelector('.detail-actions')],
      ['https://civitai.com/models/4001?modelVersionId=501', false]);
const opened = [];
const openBefore = window.open;
window.open = (...args) => { opened.push(args); return null; };
viewOnCivitai()?.dispatchEvent(new window.Event('click', { bubbles: true }));
window.open = openBefore;
check('   and a click opens it, in a new tab', opened,
      [['https://civitai.com/models/4001?modelVersionId=501', '_blank', 'noopener']]);

// ------------------------------------------------------------ downloading
await click(pill('v3'));
await choose('modelManager.selectFile', '0');
// One click, one download: from the click until the version is in the
// library, the button says how it is going and takes no clicks. A second
// click used to start the same download again.
refuse = 'Civitai: overloaded (503)';
await click(button());
check('7. a download Civitai refuses gives the button back, to try again',
      [button()?.disabled, button()?.textContent.trim()], [false, 'Download']);
refuse = null;
posted.length = 0;

const clicked = click(button());
check('   Download is disabled at the click, before the server answers',
      [button()?.disabled, button()?.textContent.trim()], [true, 'Starting...']);
await clicked;
check('   Download asks for that version and file', posted,
      [{ model_id: '4001', version_id: '503', file_id: '9031' }]);
check('   and stays disabled, saying how it is going',
      [button()?.disabled, button()?.textContent.trim()], [true, 'Downloading...']);
await click(button());
check('   so a second click starts nothing', posted.length, 1);
await click(pill('v2'));
await click(pill('v3'));
check('   and it is still disabled after another version and back',
      [button()?.disabled, button()?.textContent.trim()], [true, 'Downloading...']);
await choose('modelManager.selectFile', '0');
const panel = document.getElementById('mm_downloads');
const badge = () => panel.querySelector('.mm-download-status-badge')?.textContent.trim();
check('   and the download shows in the tab\'s own panel, as it does in the Civitai Browser\'s',
      [panel.style.display, badge()], ['block', 'Downloading']);

Object.assign(progress[0], { status: 'finishing', percent: 100, downloaded_bytes: 1000 });
await waitFor('finishing', () => badge() === 'Adding to library', 100);
localVersions = [local(501, 'v1'), { ...local(503, 'v3'), local_version_count: 2 }];
Object.assign(progress[0], { status: 'complete', synced: true });
await waitFor('the version to arrive', () => detailsAsked.at(-1) === 'C:/models/v3.safetensors', 100);
check('8. once it is in the library, it is shown as a local version',
      [pillNames(), active(), badge()], [['v3 ✓', 'v2 ⬥', 'v1 ✓'], ['v3 ✓'], 'Complete']);
check('   with the delete buttons for a model with two versions here',
      Array.from(details().querySelectorAll('.detail-header button.danger')).map((b) => b.textContent.trim()),
      ['Delete Current Model Version', 'Delete All Model Versions']);

check('   and Show in Civitai Browser sends the version now shown, as does its Version ID row',
      [(await showInBrowser()).query, row('Version ID')], ['model:4001 version:503', '503']);

// ------------------------------------------------ a file, from another tab
// The Generations tab's "Show model in Model Manager": the file's model, and
// the version that file is - not the one the model's row names.
const searched = [];
const realFetch = globalThis.fetch;
globalThis.fetch = async (url, init) => {
    if (String(url).includes('/model-manager/models?')) searched.push(new URL(String(url)).searchParams.get('search'));
    return realFetch(url, init);
};
await click(pill('v1'));
check('   (v1 shown first, so the file has to be found)', active(), ['v1 ✓']);
await openTab('modelManager', 'showFile', 'C:/models/v3.safetensors');
check('10. a file shown from another tab is looked up by its exact path, and its own version opened',
      [searched.at(-1), active(), detailsAsked.at(-1)], ['path:C:/models/v3.safetensors', ['v3 ✓'], 'C:/models/v3.safetensors']);
// By its version, as the Generations tab now asks (#42): no path passed about.
await click(pill('v1'));
await openTab('modelManager', 'showVersion', 503);
check('11. a version shown from another tab is looked up by its id, and opened',
      [searched.at(-1), active()], ['version:503', ['v3 ✓']]);
globalThis.fetch = realFetch;

// ------------------------------------------------- a paid version, bought
// The account bought it: a Download like any other's, saying so.
v2Owned = true;
await act('modelManager.selectModel', { index: 0 });
await click(pill('v2'));
check('12. a paid version the account bought has a Download, saying so, and no Paid label',
      [downloads(), /bought it/.test(button()?.getAttribute('title') || ''), !!paidLabel()],
      [['modelManager.download', '4001', '502', '9032'], true, false]);
v2Owned = false;

// -------------------------------------------------- nothing recorded yet
civitaiVersions = () => [];
localVersions = [local(501, 'v1')];
await act('modelManager.selectModel', { index: 0 });
check('9. with one version on disk and no list recorded, no selector - as before', pills().length, 0);

// ------------------------------------------------ a version of two files
// An fp16 and an fp32 of one version are one version (#133): one pill, and
// its files listed under it - what each is, and the one Send uses. Nothing
// to pick: the galleries are the version's.
const fp32 = { ...local(501, 'v1'), file_path: 'C:/forge/models/Lora/v1_fp32.safetensors', file_name: 'v1_fp32.safetensors',
               file_type: 'LORA', send_uses: false, civitai_file_id: null };
civitaiVersions = listed;
localVersions = [{ ...local(501, 'v1'), file_type: 'LORA', send_uses: true, civitai_file_id: 9011 }, fp32];
await act('modelManager.selectModel', { index: 0 });
const versionPills = () => Array.from(details().querySelectorAll('.mm-version-selector .mm-version-pill'))
    .map((p) => p.textContent.trim());
const cells = (selector) => Array.from(details().querySelectorAll(`.mm-files-slot ${selector}`))
    .map((tr) => Array.from(tr.children).map((cell) => cell.textContent.trim()));
check('13. a version with two files here is one pill', versionPills(), ['v3', 'v2 ⬥', 'v1 ✓']);
check('    counted once', details().querySelector('.mm-version-selector h4')?.textContent.trim(),
      'Versions (3, 1 downloaded)');
check('    its files in a table under it, a column a fact, delete last',
      [details().querySelector('.mm-files-slot h4')?.textContent.trim(), cells('thead tr')[0]],
      ['Files (2)', ['Type', 'Name', 'Size', 'Modified', 'Folder', 'Send', 'File ID', '']]);
const rows = cells('tbody tr');
check('    what each is, the one Send uses, Civitai\'s id for it - none for a file it does not name',
      rows.map((row) => [row[0], row[1], row[5], row[6]]),
      [['LORA', 'v1.safetensors', '✓', '9011'], ['LORA', 'v1_fp32.safetensors', '', '—']]);
check('    each file\'s folder from Forge\'s own - one outside it, whole', rows.map((row) => row[4]),
      ['C:/models', 'models/Lora']);
const fp16 = { ...local(501, 'v1'), file_path: 'C:/models/lora/sdxl/v1_fp16.safetensors', file_name: 'v1_fp16.safetensors',
               file_type: 'LORA' };
localVersions = [...localVersions, fp16];
await act('modelManager.selectModel', { index: 0 });
check('    one in a folder given on the command line, from its option',
      cells('tbody tr').map((row) => row[4]), ['C:/models', 'models/Lora', '--lora-dir/sdxl']);
localVersions = localVersions.slice(0, 2);
await act('modelManager.selectModel', { index: 0 });
check('    and its delete in the last column',
      Array.from(details().querySelectorAll('.mm-files-slot tbody tr')).map((tr) =>
          tr.lastElementChild.querySelector('[data-action="modelManager.deleteFile"]') !== null), [true, true]);
check('    nothing in it to pick', details().querySelectorAll('.mm-files-slot .mm-version-pill, .mm-files-slot [data-action="modelManager.selectPill"]').length, 0);
check('    and the Information table says nothing of one file',
      Array.from(details().querySelectorAll('.mm-file-fact')).map((tr) => tr.style.display), ['none', 'none', 'none']);
await click(pill('v1'));
await openTab('modelManager', 'showVersion', 501, 'C:/forge/models/Lora/v1_fp32.safetensors');
check('14. a version shown from another tab opens the file it names', detailsAsked.at(-1),
      'C:/forge/models/Lora/v1_fp32.safetensors');

// ------------------------------- a file in a folder this WebUI ignores (#195)
// --lora-dir given: Forge's own models\Lora is not loaded. The file is still
// listed; its File row and its row in a version's Files say so, and why.
civitaiVersions = () => [];
localVersions = [{ ...local(501, 'v1'), ignored_because: '--lora-dir' }];
document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await new Promise((r) => setTimeout(r, 50));
await act('modelManager.selectModel', { index: 0 });
const fileTag = details().querySelector('.file-path-cell .ignored-tag');
check('15. a file Neo ignores: its File row says so, and why',
      [fileTag?.textContent.trim(), fileTag?.title], ['Ignored by Neo', 'Neo does not load this folder: --lora-dir replaces it']);
civitaiVersions = listed;
localVersions = [{ ...local(501, 'v1'), file_type: 'LORA', send_uses: true, civitai_file_id: 9011 },
                 { ...fp32, ignored_because: '--lora-dir' }];
await act('modelManager.selectModel', { index: 0 });
check('    and in a version\'s Files, beside its name',
      Array.from(details().querySelectorAll('.mm-files-slot tbody tr'))
          .map((tr) => tr.children[1].querySelector('.ignored-tag')?.textContent.trim() || ''),
      ['', 'Ignored by Neo']);

done();

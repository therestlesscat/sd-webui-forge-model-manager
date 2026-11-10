// The downloads panel's controls (#37, #38): a running download can be
// paused; a waiting one started now, moved up or down, or cancelled; a paused
// one resumed; a failed one retried (#223). The rows are in the server's order - the order downloads were
// added in, which ↑/↓ change - and a change of state never moves one; a
// waiting one says its place in the queue. Pause all and Resume all show when
// there is something to pause or resume.
// Each asks the server (/download/control) and takes the list it answers.
// The server's side: download_test.py.
import { ROOT, act, checker, forgeRefreshButtons, mountTab, press, sharedModule, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
window.mmTiming = { poll: 20 };
const { check, waitFor, done } = checker();

const MB = 1024 * 1024;
// Found by its file (#374): file 1000 + n of version n, so a page reading one for the other fails.
const dl = (id, status, extra = {}) => ({ version_id: id, file_id: 1000 + id, file_name: `v${id}.safetensors`, status, percent: 40,
                                          downloaded_bytes: 40 * MB, total_bytes: 100 * MB, synced: false, ...extra });
// Listed as the server keeps them: states in any order.
const ALL = [dl(4, 'paused'), dl(1, 'downloading'), dl(5, 'complete', { synced: true }),
             dl(2, 'pending', { queue_position: 1 }), dl(3, 'pending', { queue_position: 2 })];
// After a restart: nothing running - only paused and finished - so nothing polls.
let server = [dl(4, 'paused'), dl(5, 'complete', { synced: true })];
const asked = [];
const cancelled = [];
const started = [];
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.endsWith('/civitai/download')) {
        started.push(Number(init.body.get('file_id')));
        return reply({ success: true });
    }
    if (href.includes('/download/control')) {
        const action = init.body.get('action');
        const id = Number(init.body.get('file_id'));
        asked.push([action, id]);
        const v = id - 1000;
        if (action === 'start_now') server = server.map((d) => (d.file_id === id ? dl(v, 'downloading') : d));
        if (action === 'resume_all') server = server.map((d) => (d.status === 'paused' ? dl(d.version_id, 'pending', { queue_position: 1 }) : d));
        if (action === 'retry') server = [...server.filter((d) => d.file_id !== id), dl(v, 'pending', { queue_position: 1 })];
        return reply({ success: true, done: true, downloads: structuredClone(server) });
    }
    if (href.includes('/download/cancel')) {
        const id = Number(init.body.get('file_id'));
        cancelled.push(id);
        server = server.map((d) => (d.file_id === id ? dl(id - 1000, 'cancelled') : d));
        return reply({ success: true });
    }
    if (href.includes('/download/progress')) return reply({ success: true, downloads: structuredClone(server) });
    return reply({ success: true });
};

// In the WebUI the script runs before Gradio has drawn the tab: the panel is
// not there yet when the list first comes back. It is drawn into it once it
// is - after Gradio's update - though nothing is running to poll again.
const hooks = [];
globalThis.onAfterUiUpdate = (callback) => hooks.push(callback);
const panelBox = document.getElementById('mm_downloads');
const panelPlace = panelBox.parentNode;
const panelNext = panelBox.nextSibling;
panelBox.remove();

// Forge's refresh buttons (#193): the checkpoint and VAE / text encoder
// lists', and the extra networks' hidden one - LoRAs, embeddings.
// Pressed one at a time, each waited for (#321): the stand-in answers as Forge does.
const refreshed = forgeRefreshButtons(document, window);

await startTab('modelManager');
const { downloads } = await sharedModule('downloads.mjs');     // the tab's copy
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await new Promise((resolve) => setTimeout(resolve, 100));
panelPlace.insertBefore(panelBox, panelNext);                 // Gradio draws the tab
hooks.forEach((hook) => hook());
// Nothing started in this page: after a restart, the paused downloads the
// server kept are listed all the same - the page asks for the list at load.

const rows = () => Array.from(document.querySelectorAll('#mm_download_list .mm-download-item'));
const row = (id) => rows().find((r) => r.textContent.includes(`v${id}.safetensors`));
const buttons = (id) => Array.from(row(id)?.querySelectorAll('.mm-download-actions button') || [])
    .map((b) => [b.textContent.trim(), b.disabled]);
const calls = (id) => Array.from(row(id)?.querySelectorAll('.mm-download-actions button') || [])
    .map((b) => [b.dataset.action, b.dataset.control, b.dataset.fileId]);
const text = (id) => row(id)?.querySelector('.mm-download-percent')?.textContent.replace(/\s+/g, ' ').trim();
const shown = (id) => document.getElementById(id)?.style.display !== 'none';
await waitFor('the list, asked for at load', () => rows().length === 2);
check('after a restart, the paused download is in the panel, though the panel came after the list',
      [rows().length, shown('mm_downloads'), shown('mm_downloads_resume_all')], [2, true, true]);
// The finished one was finished before this page: Forge's lists already
// had it, or a page that saw it arrive refreshed them. Every page load used
// to refresh them again, while it stayed in the list.
check('a download finished before the page loaded refreshes nothing', refreshed, []);

// Then downloads running and waiting too, as the poll brings them.
server = structuredClone(ALL);
downloads().track(server[1]);
await waitFor('the whole list', () => rows().length === 5);

const names = () => rows().map((r) => r.querySelector('.mm-download-name').textContent.replace('.safetensors', ''));
const LISTED = ['v4', 'v1', 'v5', 'v2', 'v3'];
check('the rows are in the server\'s order, not sorted by state', names(), LISTED);
check('a running one: Pause, and Cancel', buttons(1), [['Pause', false], ['Cancel', false]]);
check('the first waiting: Start now, not up, down, Cancel',
      buttons(2), [['Start now', false], ['↑', true], ['↓', false], ['Cancel', false]]);
check('the last waiting: up, not down', buttons(3), [['Start now', false], ['↑', false], ['↓', true], ['Cancel', false]]);
check('each waiting one says its place', [text(2), text(3)], ['Waiting - 1st in the queue', 'Waiting - 2nd in the queue']);
check('a paused one: how far it got, Resume, and Cancel',
      [text(4), buttons(4)], ['Paused - 40.00 MB / 100.00 MB', [['Resume', false], ['Cancel', false]]]);
check('the buttons ask the server what they say',
      [calls(1)[0], calls(2).slice(0, 3), calls(4)[0]],
      [['downloads.control', 'pause', '1001'],
       [['downloads.control', 'start_now', '1002'], ['downloads.control', 'up', '1002'], ['downloads.control', 'down', '1002']],
       ['downloads.control', 'resume', '1004']]);
check('Pause all and Resume all show, there being something to pause and something to resume',
      [shown('mm_downloads_pause_all'), shown('mm_downloads_resume_all')], [true, true]);
check('and the summary counts the paused', document.getElementById('mm_downloads_summary')?.textContent,
      '1 downloading, 2 pending, 1 paused, 1 finished');

// A download in parts that paused itself says why (#282): Resume tries again.
const WHY = "Civitai's storage would not send part 3 of 4. Resume to try again.";
server = structuredClone(ALL).map((d) => (d.version_id === 4 ? dl(4, 'paused', { error: WHY }) : d));
await waitFor('the paused one with its reason', () => text(4)?.includes('Resume to try'));
check('a paused one with a reason: how far it got, and why',
      [text(4), buttons(4)], [`Paused - 40.00 MB / 100.00 MB · ${WHY}`, [['Resume', false], ['Cancel', false]]]);
server = structuredClone(ALL);
await waitFor('the reason gone again', () => text(4) === 'Paused - 40.00 MB / 100.00 MB');

await act('downloads.control', { control: 'start_now', fileId: 1002 });
check('Start now: asked, and the list is the server\'s answer at once - no row moved',
      [asked.at(-1), buttons(2)[0], names()], [['start_now', 1002], ['Pause', false], LISTED]);
await act('downloads.control', { control: 'resume_all' });
check('Resume all: asked, nothing is left to resume, and the resumed one is where it was',
      [asked.at(-1), shown('mm_downloads_resume_all'), text(4), names()],
      [['resume_all', 0], false, 'Waiting - 1st in the queue', LISTED]);
await act('downloads.cancel', { fileId: 1003 });
check('a waiting one cancelled: at once, without waiting for a poll, and in its row',
      [cancelled, row(3)?.querySelector('.mm-download-status-badge')?.textContent, names()], [[1003], 'Cancelled', LISTED]);

// Civitai is asked at a download's turn (#223): a failure there is its row's,
// and Retry puts it back at the end of the queue.
server = [...server, dl(6, 'error', { error: 'Could not ask Civitai about this version: busy' })];
downloads().track(server[0]);
await waitFor('the failed one', () => row(6));
check('a failed one: why, Retry, and Dismiss',
      [text(6), buttons(6), calls(6)[0]],
      ['Could not ask Civitai about this version: busy', [['Retry', false], ['Dismiss', false]],
       ['downloads.control', 'retry', '1006']]);
const retry = Array.from(row(6)?.querySelectorAll('button') || []).find((b) => b.textContent.trim() === 'Retry');
if (retry) press(retry);
await waitFor('the retry answered', () => row(6)?.querySelector('.mm-download-status-badge')?.textContent !== 'Error');
check('Retry: asked, and the row waits again, last',
      [asked.at(-1), row(6)?.querySelector('.mm-download-status-badge')?.textContent, names().at(-1)],
      [['retry', 1006], 'Queued', 'v6']);

// Download's order of cases (#229): Already Owned before on-site only, and
// on-site only before paid - a version can be both paid and on-site only.
const { renderDownloadControls } = await sharedModule('downloads.mjs');
const CONTROLS = { prefix: 'mm', download: 'modelManager.download', selectFile: 'modelManager.selectFile' };
const drawn = (version, owned = false, fileIndex = 0) => {
    const box = document.createElement('div');
    box.innerHTML = renderDownloadControls({ controls: CONTROLS, modelId: 1, version, fileIndex, owned });
    const button = box.querySelector('button');
    return [button?.textContent.trim(), Boolean(button?.disabled), button?.hasAttribute('data-download-file')];
};
const FILE = [{ id: 1, name: 'a.safetensors', primary: true }];
check('Download: Already Owned before on-site only',
      drawn({ id: 91, files: FILE, on_site_only: true }, true), ['Already Owned', true, false]);
check('on-site only before paid',
      drawn({ id: 92, files: FILE, on_site_only: true, paid_access: { permanent: true, owned: false } }),
      ['On-site only', true, false]);
check('not known, or allowed: Download as today',
      [drawn({ id: 93, files: FILE, on_site_only: null })[2], drawn({ id: 94, files: FILE, on_site_only: false })[2]],
      [true, true]);

// A download is one file (#374): a version's other file is not it. Finished,
// or on its way, it marks its own file's button alone, and the picker's
// button follows the file picked.
const TWO = { id: 95, files: [{ id: 951, name: 'model.safetensors', primary: true },
                              { id: 952, name: 'vae.safetensors' }] };
downloads().track({ version_id: 95, file_id: 951, file_name: 'model.safetensors', status: 'complete', synced: true });
check('one file of a version downloaded: its own button says so, the other\'s offers Download',
      [drawn(TWO, false, 0).slice(0, 2), drawn(TWO, false, 1).slice(0, 2)], [['Downloaded', true], ['Download', false]]);
downloads().track({ version_id: 95, file_id: 951, file_name: 'model.safetensors', status: 'downloading', percent: 10 });
check('one on its way: the other file can still be started',
      [drawn(TWO, false, 0).slice(0, 2), drawn(TWO, false, 1).slice(0, 2)], [['Downloading...', true], ['Download', false]]);
const second = await downloads().start(1, 95, 952, { fileName: 'vae.safetensors' });
check('and pressed, it is asked for, not refused as "Already downloading"', [second.success, started], [true, [952]]);
const again = await downloads().start(1, 95, 951);
check('the file on its way, pressed again, is refused here, the server not asked',
      [again.error, started], ['Already downloading', [952]]);
const { showChosenFile } = await sharedModule('downloads.mjs');
const holder = document.createElement('div');
holder.innerHTML = renderDownloadControls({ controls: CONTROLS, modelId: 1, version: TWO, fileIndex: 1, owned: false });
document.body.appendChild(holder);
const picked = () => { const b = document.getElementById('mm_download_btn'); return [b?.textContent.trim(), Boolean(b?.disabled)]; };
check('drawn for the version\'s other file: Download', picked(), ['Download', false]);
showChosenFile(CONTROLS, 1, TWO, TWO.files[0]);
check('the picker turned to the file on its way: the button follows it', picked(), ['Downloading...', true]);
showChosenFile(CONTROLS, 1, TWO, TWO.files[1]);
check('and back to the other file: Download again', picked(), ['Download', false]);
holder.remove();

// The status and the link are the server's, drawn as markup (S2): a status it
// never sends is text in its class and its badge, and a page link that is not
// http or https is no link. A marker shows a fault: an element, or an
// attribute added to the row.
const ODD = 'odd" data-mm-marker="1 <i data-mm-marker></i>';
server = [...server, dl(7, ODD), dl(8, 'error', { error: 'Gone', page_url: 'ftp://example.invalid/m' }),
          dl(9, 'error', { error: 'Gone', page_url: 'https://civitai.com/models/9' })];
downloads().track(server[0]);
await waitFor('the odd rows', () => row(7) && row(8) && row(9));
check('a status the page does not know is text, in the row\'s class and its badge',
      [document.querySelectorAll('#mm_download_list [data-mm-marker]').length,
       row(7)?.querySelector('.mm-download-status-badge')?.textContent], [0, ODD]);
check('a page link that is not http or https is not drawn; one that is, is',
      [row(8)?.querySelectorAll('a').length, row(9)?.querySelector('a')?.getAttribute('href')],
      [0, 'https://civitai.com/models/9']);

done();

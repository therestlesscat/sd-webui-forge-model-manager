// The downloads panel's controls (#37, #38): a running download can be
// paused; a waiting one started now, moved up or down, or cancelled; a paused
// one resumed. The rows are in the server's order - the order downloads were
// added in, which ↑/↓ change - and a change of state never moves one; a
// waiting one says its place in the queue. Pause all and Resume all show when
// there is something to pause or resume.
// Each asks the server (/download/control) and takes the list it answers.
// The server's side: download_test.py.
import { ROOT, checker, mountTab, sharedModule } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
window.mmTiming = { poll: 20 };
const { check, waitFor, done } = checker();

const MB = 1024 * 1024;
const dl = (id, status, extra = {}) => ({ version_id: id, file_name: `v${id}.safetensors`, status, percent: 40,
                                          downloaded_bytes: 40 * MB, total_bytes: 100 * MB, synced: false, ...extra });
// Listed as the server keeps them: states in any order.
const ALL = [dl(4, 'paused'), dl(1, 'downloading'), dl(5, 'complete', { synced: true }),
             dl(2, 'pending', { queue_position: 1 }), dl(3, 'pending', { queue_position: 2 })];
// After a restart: nothing running - only paused and finished - so nothing polls.
let server = [dl(4, 'paused'), dl(5, 'complete', { synced: true })];
const asked = [];
const cancelled = [];
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/download/control')) {
        const action = init.body.get('action');
        const id = Number(init.body.get('version_id'));
        asked.push([action, id]);
        if (action === 'start_now') server = server.map((d) => (d.version_id === id ? dl(id, 'downloading') : d));
        if (action === 'resume_all') server = server.map((d) => (d.status === 'paused' ? dl(d.version_id, 'pending', { queue_position: 1 }) : d));
        return reply({ success: true, done: true, downloads: structuredClone(server) });
    }
    if (href.includes('/download/cancel')) {
        const id = Number(init.body.get('version_id'));
        cancelled.push(id);
        server = server.map((d) => (d.version_id === id ? dl(id, 'cancelled') : d));
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

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
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
    .map((b) => b.getAttribute('onclick'));
const text = (id) => row(id)?.querySelector('.mm-download-percent')?.textContent.replace(/\s+/g, ' ').trim();
const shown = (id) => document.getElementById(id)?.style.display !== 'none';
await waitFor('the list, asked for at load', () => rows().length === 2);
check('after a restart, the paused download is in the panel, though the panel came after the list',
      [rows().length, shown('mm_downloads'), shown('mm_downloads_resume_all')], [2, true, true]);

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
check('the buttons ask the server what they say (this DOM runs no inline handlers)',
      [calls(1)[0], calls(2).slice(0, 3), calls(4)[0]],
      ["window.mmDownloadControl('pause', 1)",
       ["window.mmDownloadControl('start_now', 2)", "window.mmDownloadControl('up', 2)", "window.mmDownloadControl('down', 2)"],
       "window.mmDownloadControl('resume', 4)"]);
check('Pause all and Resume all show, there being something to pause and something to resume',
      [shown('mm_downloads_pause_all'), shown('mm_downloads_resume_all')], [true, true]);
check('and the summary counts the paused', document.getElementById('mm_downloads_summary')?.textContent,
      '1 downloading, 2 pending, 1 paused, 1 finished');

await window.mmDownloadControl('start_now', 2);
check('Start now: asked, and the list is the server\'s answer at once - no row moved',
      [asked.at(-1), buttons(2)[0], names()], [['start_now', 2], ['Pause', false], LISTED]);
await window.mmDownloadControl('resume_all', 0);
check('Resume all: asked, nothing is left to resume, and the resumed one is where it was',
      [asked.at(-1), shown('mm_downloads_resume_all'), text(4), names()],
      [['resume_all', 0], false, 'Waiting - 1st in the queue', LISTED]);
await window.mmCancelDownload(3);
check('a waiting one cancelled: at once, without waiting for a poll, and in its row',
      [cancelled, row(3)?.querySelector('.mm-download-status-badge')?.textContent, names()], [[3], 'Cancelled', LISTED]);

done();

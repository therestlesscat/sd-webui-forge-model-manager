// Dismissing finished downloads, one at a time or all at once - and staying
// dismissed.
//
// Dismiss took a download off the list in the page only. The server kept
// every download until the WebUI restarted and handed the whole lot to each
// poll, so the next download brought every dismissed one back. Dismiss now
// asks the server to forget it; the list follows the server's; and "Dismiss
// all" takes every finished one off at once, leaving what is still running.
import { ROOT, checker, mountTab, sharedModule } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
window.mmTiming = { poll: 20 };
const { check, waitFor, done } = checker();

// ------------------------------------------------------------- the server
// As download_service.DownloadService keeps them: every download until it is
// dismissed, and only a finished one can be.
const FINISHED = ['complete', 'error', 'cancelled'];
const download = (id, status) => ({ version_id: id, file_name: `v${id}.safetensors`, status,
                                    percent: 50, downloaded_bytes: 5, total_bytes: 10, synced: status === 'complete' });
let server = [download(1, 'downloading'), download(2, 'complete'), download(3, 'error'), download(4, 'cancelled')];
let forgets = true;              // false: the server answers a dismiss, and forgets nothing
const dismissAsked = [];

globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/civitai/download/progress')) {
        return reply({ success: true, downloads: structuredClone(server) });
    }
    if (href.includes('/civitai/download/dismiss')) {
        const asked = Number(init.body.get('version_id'));
        dismissAsked.push(asked);
        if (forgets) server = server.filter((d) => !FINISHED.includes(d.status) || (asked && d.version_id !== asked));
        return reply({ success: true });
    }
    return reply({ success: true });
};

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
const { downloads } = await sharedModule('downloads.mjs');     // the tab's copy
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => document.getElementById(id);
const listed = () => Array.from(document.querySelectorAll('#mm_download_list .mm-download-name'))
    .map((n) => n.textContent.trim());
const dismissAll = () => $('mm_downloads_dismiss_all');
const polls = async (n = 3) => { for (let i = 0; i < n; i++) await new Promise((r) => setTimeout(r, 30)); };

downloads().track(server[0]);
await waitFor('the list', () => listed().length === 4);
check('finished downloads are listed beside the running one',
      listed(), ['v1.safetensors', 'v2.safetensors', 'v3.safetensors', 'v4.safetensors']);
check('with Dismiss all offered while any has finished', dismissAll()?.style.display, '');

await window.mmDismissDownload(2);
check('Dismiss takes one off the list', listed().includes('v2.safetensors'), false);
check('and asks the server to forget it', dismissAsked, [2]);
await polls();
check('so it stays gone while another download keeps the list polling',
      listed().includes('v2.safetensors'), false);

await window.mmDismissFinishedDownloads();
check('Dismiss all takes every finished one off, leaving the running one', listed(), ['v1.safetensors']);
check('asking the server to forget every finished one', dismissAsked.at(-1), 0);
check('and is not offered with nothing finished', dismissAll()?.style.display, 'none');
await polls();
check('none of them comes back', listed(), ['v1.safetensors']);

// A poll already on its way when a download is dismissed - here, a server
// that has not forgotten it yet - does not bring it back.
server = server.concat(download(5, 'error'));
await waitFor('a new failure', () => listed().includes('v5.safetensors'));
forgets = false;
await window.mmDismissDownload(5);
await polls();
check('a dismissed download a poll still carries stays off the list', listed().includes('v5.safetensors'), false);
forgets = true;

// The same version downloaded again is a new download, and is shown.
server = server.map((d) => (d.version_id === 5 ? download(5, 'downloading') : d));
downloads().track(download(5, 'downloading'));
await polls();
check('one dismissed and started again is listed again', listed().includes('v5.safetensors'), true);

// Everything finished, everything dismissed: the panel goes.
server = [download(1, 'complete'), download(5, 'complete')];
await waitFor('both complete', () => listed().length === 2 && dismissAll()?.style.display === '');
await window.mmDismissFinishedDownloads();
check('with nothing left, the list is empty and the panel hidden',
      [listed(), $('mm_downloads').style.display], [[], 'none']);

done();

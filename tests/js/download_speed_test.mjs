// How fast a download is going, and how long it has left (#36), in the
// downloads panel: "42.1% - 2.7 GB / 6.5 GB · 12.4 MB/s · about 5 min left".
// The server measures them (DownloadProgress.rate, download_test.py); the page
// only words them - "stalled" rather than 0 B/s, and nothing at all while
// there is nothing to say, or the download is not downloading.
import { ROOT, checker, mountTab, sharedModule, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
window.mmTiming = { poll: 20 };
const { check, waitFor, done } = checker();

const MB = 1024 * 1024;
const download = (id, extra) => ({ version_id: id, file_name: `v${id}.safetensors`, status: 'downloading',
                                   percent: 42.1, downloaded_bytes: 2.7 * 1024 * MB, total_bytes: 6.5 * 1024 * MB,
                                   synced: false, ...extra });
const server = [download(1, { speed_bps: 12.4 * MB, eta_seconds: 300, stalled: false }),
                download(2, { speed_bps: null, eta_seconds: null, stalled: true }),
                download(3, { speed_bps: null, eta_seconds: null, stalled: false }),
                download(4, { status: 'pending', speed_bps: null, eta_seconds: null, stalled: false }),
                // Refused by Civitai (#43): its reason, and the version's page.
                download(5, { status: 'error', error: 'Civitai refused the download: This asset is in Early Access.',
                              page_url: 'https://civitai.com/models/9?modelVersionId=5' })];
globalThis.fetch = async (url) => {
    const reply = (body) => ({ ok: true, json: async () => body });
    if (String(url).includes('/civitai/download/progress')) return reply({ success: true, downloads: structuredClone(server) });
    return reply({ success: true });
};

const { downloadRateText } = await import(`file:///${ROOT}/javascript/shared/downloads.mjs`);
const rate = (speed, left, extra = {}) => downloadRateText({ status: 'downloading', speed_bps: speed,
                                                              eta_seconds: left, stalled: false, ...extra });
check('the speed, one decimal, and minutes left rounded up',
      rate(12.4 * MB, 300), '12.4 MB/s · about 5 min left');
check('under a minute', rate(12.4 * MB, 30), '12.4 MB/s · less than a minute left');
check('over an hour, in hours and minutes', rate(1.5 * MB, 3725), '1.5 MB/s · about 1 h 3 min left');
check('never "1 h 60 min": minutes rounded first', rate(1.5 * MB, 7199), '1.5 MB/s · about 2 h left');
check('a speed with no total: the speed alone, a whole number without its .0', rate(800 * 1024, null), '800 KB/s');
check('nothing for a while: stalled, not 0 B/s', rate(null, null, { stalled: true }), 'stalled');
check('nothing measured yet: nothing said', rate(null, null), '');
check('not downloading: nothing said, whatever else', rate(12 * MB, 10, { status: 'pending' }), '');

await startTab('modelManager');
const { downloads } = await sharedModule('downloads.mjs');     // the tab's copy
document.dispatchEvent(new window.Event('DOMContentLoaded'));
downloads().track(server[0]);
const line = (id) => Array.from(document.querySelectorAll('#mm_download_list .mm-download-item'))
    .find((item) => item.textContent.includes(`v${id}.safetensors`))
    ?.querySelector('.mm-download-percent')?.textContent.replace(/\s+/g, ' ').trim();
await waitFor('the list', () => [1, 2, 3, 4, 5].every((id) => line(id) !== undefined));
check('the panel says it after how far it has got',
      line(1), '42.1% - 2.70 GB / 6.50 GB · 12.4 MB/s · about 5 min left');
check('a stalled one says so', line(2), '42.1% - 2.70 GB / 6.50 GB · stalled');
check('one not measured yet, just how far', line(3), '42.1% - 2.70 GB / 6.50 GB');
check('a queued one, waiting', line(4), 'Waiting...');
const refused = Array.from(document.querySelectorAll('#mm_download_list .mm-download-item'))
    .find((item) => item.textContent.includes('v5.safetensors'));
check('one Civitai refused says why, with a way to its page there',
      [line(5), refused?.querySelector('.mm-download-percent a')?.getAttribute('href')],
      ['Civitai refused the download: This asset is in Early Access. Open on Civitai',
       'https://civitai.com/models/9?modelVersionId=5']);

done();

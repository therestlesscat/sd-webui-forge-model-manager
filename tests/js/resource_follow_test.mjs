// A resource's Download - in the Resources dialog, and a missing LoRA's chip
// under a sent prompt, which share downloadResource() - for a version the
// downloads list already has (#119). Since the dialog went through the
// downloads list (R45), one on its way was refused - "Already downloading" -
// marked failed, and never followed, so its row and chip stayed failed after
// the download landed; and a finished one still listed could not be
// downloaded again, its model deleted since, until the list was cleared.
//
// Here: one on its way - queued, downloading, paused - is followed, asking
// nothing, to complete; a finished one is asked for again. How each is going
// is the downloads list's, read as a Download button reads it (#111).
import { checker, mountTab, sharedModule, startServices } from './harness.mjs';

mountTab('model_manager/ui/tab_model_manager.py');
const { check, done } = checker();

const posts = [];
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (href.includes('/civitai/download/progress')) return reply({ success: true, downloads: [] });
    if (href.includes('/civitai/download')) {
        const versionId = Number(init.body?.get?.('version_id'));
        posts.push(versionId);
        // A substitute this WebUI holds already: nothing to download.
        if (versionId === 6005) {
            return reply({ success: true, already_installed: true, version_id: 6009, version_name: 'v9',
                           substituted: true });
        }
        return reply({ success: true, version_id: versionId, version_name: 'v1',
                       progress: { version_id: versionId, status: 'pending', percent: 0, file_name: 'x.safetensors' } });
    }
    if (href.includes('/ui-options')) return reply({ success: true, samplers: [], schedulers: [], has_api_key: true });
    return reply({ success: true });
};

// Started as the Model Manager or the Civitai Browser starts them (#182).
const { downloads } = await sharedModule('downloads.mjs');
const { downloadResource, resourceDownload } = await sharedModule('resources.mjs');
await startServices('downloads.mjs', 'resources.mjs');
const job = (id) => {
    const j = resourceDownload(id) || {};
    return { status: j.status, target: j.target, percent: j.percent };
};

// On its way, started from the Civitai Browser: followed, nothing asked.
downloads().track({ version_id: 6001, status: 'downloading', percent: 40, file_name: 'a.safetensors' });
await downloadResource(6001, 4001);
check('a version already downloading is followed, not asked for again',
      [posts.length, job(6001)], [0, { status: 'downloading', target: 6001, percent: 40 }]);
downloads().track({ version_id: 6001, status: 'complete', synced: true, percent: 100, file_name: 'a.safetensors' });
check('and is complete once it is in the library', job(6001).status, 'complete');

for (const [id, status] of [[6003, 'pending'], [6004, 'paused']]) {
    downloads().track({ version_id: id, status, percent: 10, file_name: 'c.safetensors' });
    await downloadResource(id, 4003);
    check(`one ${status} is followed too`, [posts.includes(id), job(id).status, job(id).target], [false, status, id]);
}

// Finished, still in the list - its model deleted since: asked for again.
downloads().track({ version_id: 6002, status: 'complete', synced: true, percent: 100, file_name: 'b.safetensors' });
await downloadResource(6002, 4002);
check('a finished download still in the list is asked for again',
      [posts.includes(6002), job(6002)], [true, { status: 'pending', target: 6002, percent: 0 }]);

// The image's version gone, and the newest held here already: the server
// downloads nothing, and says so. The chip and the row say which it got, and
// the library is asked, as when a download lands.
const told = [];
window.addEventListener('mm-resource-downloads', (event) => told.push(!!event.detail?.installed));
await downloadResource(6005, 4005);
const held = resourceDownload(6005) || {};
check('a substitute held here is complete at once, and the library is asked',
      [held.status, held.target, held.versionName, held.substituted, told.includes(true)],
      ['complete', 6009, 'v9', true, true]);

done();

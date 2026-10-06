// A resource's Download - in the Resources dialog, and a missing LoRA's chip
// under a sent prompt, which share downloadResource() - for a version the
// downloads list already has (#119). Since the dialog went through the
// downloads list (R45), one on its way was refused - "Already downloading" -
// marked failed, and never followed, so its row and chip stayed failed after
// the download landed; and a finished one still listed could not be
// downloaded again, its model deleted since, until the list was cleared.
//
// Here: one on its way - queued, downloading, paused - is followed, asking
// nothing, to Installed; a finished one is asked for again.
import { checker, mountTab, sharedModule } from './harness.mjs';

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
        return reply({ success: true, version_id: versionId, version_name: 'v1',
                       progress: { version_id: versionId, status: 'pending', percent: 0, file_name: 'x.safetensors' } });
    }
    if (href.includes('/ui-options')) return reply({ success: true, samplers: [], schedulers: [], has_api_key: true });
    return reply({ success: true });
};

// Started as the Model Manager or the Civitai Browser starts them (#182).
const { downloads, start: startDownloads } = await sharedModule('downloads.mjs');
const { downloadResource, resourceDownloads, start: startResources } = await sharedModule('resources.mjs');
startDownloads();
startResources();
const job = (id) => {
    const j = resourceDownloads[id] || {};
    return { state: j.state, target: j.target, percent: j.percent };
};

// On its way, started from the Civitai Browser: followed, nothing asked.
downloads().track({ version_id: 6001, status: 'downloading', percent: 40, file_name: 'a.safetensors' });
await downloadResource(6001, 4001);
check('a version already downloading is followed, not asked for again',
      [posts.length, job(6001)], [0, { state: 'downloading', target: 6001, percent: 40 }]);
downloads().track({ version_id: 6001, status: 'complete', synced: true, percent: 100, file_name: 'a.safetensors' });
check('and is Installed once it is in the library', job(6001).state, 'installed');

for (const [id, status] of [[6003, 'pending'], [6004, 'paused']]) {
    downloads().track({ version_id: id, status, percent: 10, file_name: 'c.safetensors' });
    await downloadResource(id, 4003);
    check(`one ${status} is followed too`, [posts.includes(id), job(id).state, job(id).target], [false, 'downloading', id]);
}

// Finished, still in the list - its model deleted since: asked for again.
downloads().track({ version_id: 6002, status: 'complete', synced: true, percent: 100, file_name: 'b.safetensors' });
await downloadResource(6002, 4002);
check('a finished download still in the list is asked for again',
      [posts.includes(6002), job(6002)], [true, { state: 'downloading', target: 6002, percent: 0 }]);

done();

// An image names its checkpoint by a hash - one file's, not its version's
// (#233). A version can hold an fp16 pruned file and an fp32 full one, each
// with its own hash, and an image made with one cannot be made again with the
// other. The Resources dialog said "Installed" for the version while the
// library held only the other file, and offered nothing, while Send stopped
// for the file.
//
// Now, where the server proves the library holds another file of the
// version, the row names the image's file and the one the library has, and
// its Download fetches the image's own, by the file id Civitai gives for the
// hash. Opened by a stopped send, the dialog's one Send is unlocked by a tick
// - "use the file I have instead" - and then sends with that file. A hash the
// server cannot prove another file takes the version's, as before.
import { checker, mountTab, press, sharedModule, startServices } from './harness.mjs';

const { document } = mountTab('model_manager/ui/tab_generations.py');
const { check, waitFor, done } = checker();

const HASH = 'f0dd839481';
const asked = [];
const posts = [];
let heldHashes = {};
let otherFiles = { [HASH]: { name: 'cyber_2202950.safetensors', fp: 'fp16', size: 'pruned', file_size: 2132651338 } };
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    asked.push(href);
    const reply = (body, status = 200) => ({ ok: status < 400, status, json: async () => structuredClone(body) });
    if (href.includes('/civitai/download/progress')) return reply({ success: true, downloads: [] });
    if (href.includes('/civitai/file-by-hash')) {
        return reply({ success: true, file: { file_id: 2202961, name: 'cyber_2202961.safetensors', fp: 'fp32',
                                              size: 'full', size_kb: 5780198.5, version_id: 2312428, model_id: 71185 } });
    }
    if (href.includes('/civitai/download')) {
        posts.push(Object.fromEntries(init.body.entries()));
        return reply({ success: true, version_id: 2312428, version_name: 'Classic v5.0 (Final)',
                       progress: { version_id: 2312428, status: 'pending', percent: 0, file_name: 'cyber_2202961.safetensors' } });
    }
    if (href.includes('/resolve-hashes')) {
        // The image's hash a file of version 2312428; any other, of 9999.
        const hashes = String(init.body?.get?.('hashes') || new URLSearchParams(String(init.body)).get('hashes') || '').split(',');
        return reply({ success: true, deferred: [], resolved: Object.fromEntries(hashes.filter(Boolean).map((h) => [h, {
            version_id: h === HASH ? 2312428 : 9999, model_id: 71185, name: 'CyberRealistic Classic',
            version_name: 'Classic v5.0 (Final)', model_type: 'Checkpoint' }])) });
    }
    if (href.includes('/image-resources')) {
        return reply({ success: true, versions: { 2312428: { version_id: 2312428 }, 9999: { version_id: 9999 } },
                       hashes: heldHashes, other_files: otherFiles, names: {}, embeddings: [] });
    }
    if (href.includes('/ui-options')) return reply({ success: true, samplers: [], schedulers: [], has_api_key: true });
    return reply({ success: true });
};

await sharedModule('downloads.mjs');
const { showImageResources } = await sharedModule('resources.mjs');
await startServices('core.mjs', 'calls.mjs', 'downloads.mjs', 'resources.mjs');
const image = { meta: { resources: [{ type: 'Checkpoint', name: 'CyberRealistic Classic', weight: null, hash: HASH }] } };
const modal = () => document.querySelector('.mm-resources-modal');
const row = () => modal()?.querySelector('.mm-resources-table tbody tr');
const close = () => document.querySelectorAll('.mm-modal-overlay').forEach((n) => n.remove());

// ------------------------------------------------------- opened from a card
await showImageResources(image, null);
await waitFor('the image\'s file named', () => (row()?.querySelector('.mm-res-name')?.textContent || '').includes('fp32 full'));
const name = (row()?.querySelector('.mm-res-name')?.textContent || '').replace(/\s+/g, ' ').trim();
check('the library asked about the file\'s hash, not only its version',
      new URL(asked.find((h) => h.includes('/image-resources')), 'http://x').searchParams.get('hashes'), HASH);
check('the row names the image\'s file, and the file of it the library has',
      [name.includes('Classic v5.0 (Final) · fp32 full'), name.includes('you have its fp16 pruned')], [true, true]);
check('its one control is Download - not "Installed"',
      [row()?.querySelector('[data-action="resources.download"]')?.textContent, (row()?.textContent || '').includes('Installed')],
      ['Download', false]);
check('opened from a card, not a send: no Send, no tick', modal()?.querySelector('.mm-resources-send'), null);
const download = row()?.querySelector('[data-action="resources.download"]');
if (download) press(download);
await waitFor('the download', () => posts.length);
check('Download fetches the file Civitai lists with the hash - never the primary, nor a newer one',
      [asked.some((h) => h.includes(`/civitai/file-by-hash?hash=${HASH}`)), posts[0]?.file_id, posts[0]?.newer_if_gone],
      [true, '2202961', undefined]);
close();

// ------------------------------------------------ opened by a stopped send
const sent = [];
const used = [];
await showImageResources(image, null, { note: 'The checkpoint this image was made with is not in your library.',
                                         send: { why: 'Not in your library yet.', check: null, run: () => sent.push('own'),
                                                 useInstalled: (versionId) => used.push(versionId) } });
await waitFor('the tick', () => modal()?.querySelector('[data-action="resources.useInstalledTick"]'));
const sendButton = () => modal()?.querySelector('[data-action="resources.sendAgain"]');
const tick = modal()?.querySelector('[data-action="resources.useInstalledTick"]');
check('the one Send waits, and a tick offers the file of the version you have',
      [sendButton()?.disabled, tick?.checked, (tick?.closest('label')?.textContent || '').includes('fp16 pruned')],
      [true, false, true]);
await waitFor('the note', () => (modal()?.querySelector('[data-res-note]')?.textContent || '').includes('fp32 full'));
check('the note names the image\'s file',
      (modal()?.querySelector('[data-res-note]')?.textContent || '').includes('fp32 full'), true);
if (tick) { tick.checked = true; press(tick); }
check('ticked, Send is unlocked', sendButton()?.disabled, false);
if (sendButton() && !sendButton().disabled) press(sendButton());
check('and sends with that version\'s file, closing the dialog', [used, sent, Boolean(modal())], [[2312428], [], false]);

// ------------------------------------------- a hash not proven another file
otherFiles = {};
const LORA = 'abcdefabcdef';
await showImageResources({ meta: { resources: [{ type: 'lora', name: 'lora', weight: 1, hash: LORA }] } }, null);
await waitFor('the unproven hash', () => /Installed/.test(row()?.querySelector('[data-res-download]')?.textContent || ''));
check('a hash not proven another file: the version held is installed, as before',
      (row()?.querySelector('[data-res-download]')?.textContent || '').trim(), 'Installed');
close();

// ------------------------------------------- the image's own file held
const HELD = 'ab12cd34ef';
heldHashes = { [HELD]: { version_id: 9999 } };
await showImageResources({ meta: { resources: [{ type: 'Checkpoint', name: 'held', weight: null, hash: HELD }] } }, null);
await waitFor('the held file', () => (row()?.textContent || '').includes('Installed'));
check('with the image\'s own file in the library, it is installed',
      (row()?.querySelector('[data-res-download]')?.textContent || '').trim(), 'Installed');

done();

// The Generations and Civitai Images tabs' box "Choose the checkpoint at
// every Send" (#377), and its setting. The box starts as the setting says at
// every page load - a tick an earlier version kept in this browser is not
// read (#383) - and a change of the setting sets the box of each tab running
// at once: both, then the one left on. A dialog already open stays as it is,
// its box as it was.
import { checker, mountTab, sharedModule, startTab, tabMarkup } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
document.body.insertAdjacentHTML('beforeend', tabMarkup('model_manager/ui/tab_gallery.py'));
const { check, waitFor, done } = checker();

const CHOOSE = 'model_manager_send_choose_checkpoint';
let settingOn = true;
const image = { id: 11, generation_id: 1, position: 0, seed: 7, width: 832, height: 1216, meta: { prompt: 'a lighthouse' },
                infotext: 'a lighthouse\nSteps: 20', url: '/model-manager/generations/images/11/file', exists: true,
                mm_level: 1, mm_level_from_prompt: false, user_level: null, prompt_level: 1, loras: [] };
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/ui-options')) {
        return reply({ success: true, samplers: [], schedulers: [], generations_enabled: true, choose_checkpoint: settingOn });
    }
    if (href.includes('/generations/browse')) {
        return reply({ success: true, more: false, scope: { count: 1 },
                       tiles: [{ kind: 'generation', generation: { id: 1, mode: 'txt2img', image_count: 1 }, matching_count: 1,
                                 images: [image], loras: [], level: 1, user_level: null }],
                       state: { total: 1, filtered: 1, hidden_nsfw: 0, nsfw_count: 0, nsfw_images: 'safe', stored_generations: 1 } });
    }
    if (href.includes('/model-manager/gallery/browse')) {
        return reply({ success: true, seed: 1, more: false, scope: { count: 0 }, tiles: [],
                       state: { total: 0, filtered: 0, hidden_nsfw: 0, nsfw_count: 0 } });
    }
    if (href.includes('/image-resources')) return reply({ success: true, versions: { 8001: { version_id: 8001 } }, hashes: {} });
    return reply({ success: true });
};

// Ticks an earlier version kept, both unticked, under a setting that is on.
localStorage.setItem('mm_generations_choose_checkpoint', 'false');
localStorage.setItem('mm_gallery_choose_checkpoint', 'false');
await startTab('generations');
await startTab('gallery');
const box = () => document.getElementById('gen_choose_checkpoint');
const galleryBox = () => document.getElementById('gal_choose_checkpoint');
await waitFor('the boxes set from the setting', () => box()?.checked && galleryBox()?.checked);
check('29. both tabs\' boxes start as the setting says, a tick kept in this browser not read',
      [box()?.checked, galleryBox()?.checked], [true, true]);
localStorage.removeItem('mm_generations_choose_checkpoint');
localStorage.removeItem('mm_gallery_choose_checkpoint');

// The setting changed: the tab hears it as it does every saved setting.
const changed = () => window.dispatchEvent(new window.CustomEvent('mm-settings-saved',
                                                                  { detail: { changed: [CHOOSE], settings: {} } }));
settingOn = false;
changed();
await waitFor('the boxes following the setting', () => box()?.checked === false && galleryBox()?.checked === false);
check('    the setting changed while both tabs run: each box takes it at once',
      [box()?.checked, galleryBox()?.checked], [false, false]);

// A dialog open as it changes - the Resources button's, whose box the
// setting starts as it opens: as it was.
const { showImageResources } = await sharedModule('resources.mjs');
const send = { opened: 'resources', why: '', reason: '', waits: {}, check: null, run: () => {}, pick: () => {},
               list: null };
await showImageResources({ meta: { civitaiResources: [{ type: 'checkpoint', modelVersionId: 8001, name: 'A' }] } }, null,
                         { send });
const dialogBox = () => document.querySelector('.mm-resources-modal [data-action="resources.chooseTick"]');
const sendLine = () => document.querySelector('.mm-resources-modal .mm-res-send-status')?.textContent || '';
await waitFor('the dialog\'s box set', () => sendLine());
const before = dialogBox()?.checked;
settingOn = true;
changed();
await waitFor('the tab\'s box following', () => box()?.checked === true);
await new Promise((resolve) => setTimeout(resolve, 50));
check('    a Resources button\'s dialog open meanwhile, its checkpoint Installed: its box as it opened, unticked',
      [before, dialogBox()?.checked], [false, false]);
document.querySelectorAll('#mm_meta_modal').forEach((m) => { m.close?.(); m.remove(); });

// The Civitai Images tab switched off: the one left on follows; the other's box is no longer its to set.
const { stopTab } = await sharedModule('loading.mjs');
stopTab('gallery');
const galleryBefore = galleryBox()?.checked;
settingOn = false;
changed();
await waitFor('the running tab\'s box following', () => box()?.checked === false);
await new Promise((resolve) => setTimeout(resolve, 50));
check('    one tab off: the running tab\'s box takes it; the stopped tab\'s is left as it was',
      [box()?.checked, galleryBox()?.checked], [false, galleryBefore]);

done();

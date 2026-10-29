// Thumbnails (#5), in Sync images' dialog and panel, against a stand-in server.
//
// The dialog's Thumbnails box starts as the settings have it; ticked, it
// shows where they go - a folder, its path, or beside each image - and the
// window says the sync makes them after its images; it counts them only as it
// makes them (#365). Start then works with no folder ticked, and sends the
// box, the place and the folder. The panel follows the
// making of them, and the tab reloads once some were made.
import { act, checker, mountTab, startTab, tick } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
const { check, waitFor, done } = checker();
window.mmTiming = { poll: 30 };

const FORGE = 'C:/webui/outputs/txt2img-images';
const DEFAULT = 'C:/webui/extensions/model-manager/thumbnails';
let progress = { state: 'done', stage: 'thumbnails', folder: null, folders: 0, total: 0, read: 0, generations: 0, images: 0, thumbs_total: 0,
                 thumbs_done: 0, thumbs_made: 0, errors: [], error_count: 0, cancelling: false, is_complete: true };
let settings = { thumbnails: false, thumbnails_place: 'In a folder', thumbnails_folder: '',
                 thumbnails_default_folder: DEFAULT };
const posted = [];
let browses = 0;
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => structuredClone(body) });
    if (init.method === 'POST') {
        posted.push([new URL(href, 'http://x').pathname, Object.fromEntries(new URLSearchParams(String(init.body)))]);
        return reply({ success: true });
    }
    if (href.includes('/model-manager/ui-options')) {
        return reply({ success: true, samplers: [], schedulers: [], generations_hide_nsfw: false, generations_enabled: true,
                       path_roots: [['', 'C:/webui']] });
    }
    if (href.includes('/generations/sync/folders')) {
        return reply({ success: true, level: 'Unknown', group: true, levels: ['PG', 'Unknown'], ...settings,
                       folders: [{ path: FORGE, key: 'outdir_txt2img_samples', forge: true, ticked: true, synced: 0 }] });
    }
    // The count walked every folder before the window could start (#365):
    // asked, it never answers.
    if (href.includes('/generations/sync/estimate')) return new Promise(() => {});
    if (href.includes('/generations/sync/progress')) return reply({ success: true, progress });
    if (href.includes('/model-manager/generations/browse')) {
        browses += 1;
        return reply({ success: true, tiles: [], more: false, scope: { count: 0 },
                       state: { total: 0, filtered: 0, hidden_nsfw: 0, nsfw_count: 0 } });
    }
    return reply({ success: true, notes: [] });
};

const byId = (id) => document.getElementById(id);
const text = (id) => (byId(id)?.textContent || '').trim();
const place = (value) => document.querySelector(`input[name="gen_sync_thumbs_place"][value="${value}"]`);

await startTab('generations');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

// ---------------------------------------------------------- the dialog, off
act('generations.syncImages');
await waitFor('the folders', () => document.querySelectorAll('#gen_sync_folders .mm-dialog-option').length === 1
              && text('gen_sync_estimate'));
check('off in the settings, the box starts unticked and the place is hidden',
      [byId('gen_sync_thumbs')?.checked, byId('gen_sync_thumbs_where')?.hidden], [false, true]);
check('with a folder ticked, Start is offered at once', byId('gen_sync_start')?.disabled, false);

// ---------------------------------------------------------------- ticked
tick('generations.syncThumbs', true);
check('ticked, the place shows, starting from the settings: a folder, its default in full as the hint',
      [byId('gen_sync_thumbs_where')?.hidden, place('In a folder')?.checked, byId('gen_sync_thumbs_folder_row')?.hidden,
       byId('gen_sync_thumbs_folder')?.placeholder],
      [false, true, false, `Empty: ${DEFAULT}`]);
check('nothing stands beside the box: the sync counts what it makes', byId('gen_sync_thumbs_count'), null);
check('the line says the thumbnails come after the sync',
      [byId('gen_sync_start')?.disabled, text('gen_sync_estimate')],
      [false, "The sync first looks through the ticked folders and counts the new images as it goes, then reads "
              + "each one's text. Then it makes a thumbnail of every image without one."]);
tick('generations.syncTick', false, { path: FORGE });
check('Start works with no folder ticked, to make thumbnails alone, and says so',
      [byId('gen_sync_start')?.disabled, text('gen_sync_estimate')],
      [false, 'The sync makes a thumbnail of every image without one.']);

const pick = (value) => { if (place(value)) place(value).checked = true; };
pick('Beside each image');
act('generations.syncThumbsPlace');
check('beside each image, the folder\'s box is hidden, as in the settings window',
      byId('gen_sync_thumbs_folder_row')?.hidden, true);
pick('In a folder');
act('generations.syncThumbsPlace');
if (byId('gen_sync_thumbs_folder')) byId('gen_sync_thumbs_folder').value = 'E:/thumbs';

progress = { ...progress, state: 'running', stage: 'thumbnails', is_complete: false };
act('generations.startSync');
await waitFor('the start', () => posted.length);
check('Start sends the box, the place and the folder',
      [posted[0][0], JSON.parse(posted[0][1].folders), posted[0][1].make_thumbnails, posted[0][1].place,
       posted[0][1].folder],
      ['/model-manager/generations/sync', [], 'true', 'In a folder', 'E:/thumbs']);

// ---------------------------------------------------------------- the panel
await waitFor('the panel', () => text('gen_sync_text').startsWith('Looking for images'));
check('before it knows how many, it says it is looking', text('gen_sync_text'),
      'Looking for images without a thumbnail...');
progress = { ...progress, thumbs_total: 1000, thumbs_done: 250, thumbs_made: 240 };
await waitFor('the making', () => text('gen_sync_text').startsWith('Making'));
check('it says how far it has got, and the bar shows it',
      [text('gen_sync_text'), byId('gen_sync_fill')?.style.width], ['Making thumbnails: 250 of 1,000', '25%']);
const before = browses;
progress = { ...progress, state: 'done', thumbs_done: 1000, thumbs_made: 990, is_complete: true };
await waitFor('the end', () => text('gen_sync_text').includes('Made'));
check('once done with no folder walked, it says how many were made, and nothing of images',
      text('gen_sync_text'), 'Made 990 thumbnails.');
await waitFor('the reload', () => browses > before);
check('and the tab reloads, though no generation came in, to load them', browses > before, true);

// ------------------------------------------------------- on in the settings
settings = { ...settings, thumbnails: true, thumbnails_place: 'Beside each image' };
act('generations.syncImages');
await waitFor('the dialog again', () => place('Beside each image')?.checked);
check('on in the settings, the box starts ticked, beside each image',
      [byId('gen_sync_thumbs_where')?.hidden, place('Beside each image')?.checked,
       byId('gen_sync_thumbs_folder_row')?.hidden], [false, true, true]);
act('generations.closeSyncDialog');

// ------------------------------------------------------ a place none names
settings = { ...settings, thumbnails_place: '' };
act('generations.syncImages');
await waitFor('the dialog with no place', () => place('Beside each image')?.checked === false);
check('with no place saved, in a folder is ticked: never a box with neither',
      [place('In a folder')?.checked, place('Beside each image')?.checked, byId('gen_sync_thumbs_folder_row')?.hidden],
      [true, false, false]);

// ---------------------------------------------------------------- just one
progress = { ...progress, state: 'running', stage: 'thumbnails', thumbs_total: 1, thumbs_done: 0, thumbs_made: 0,
             is_complete: false };
act('generations.startSync');
await waitFor('the second start', () => posted.length > 1 && text('gen_sync_text').startsWith('Making'));
progress = { ...progress, state: 'done', thumbs_done: 1, thumbs_made: 1, is_complete: true };
await waitFor('the second end', () => text('gen_sync_text').includes('Made'));
check('and one made is "Made 1 thumbnail."', text('gen_sync_text'), 'Made 1 thumbnail.');
act('generations.closeSyncPanel');
progress = { ...progress, state: 'running', thumbs_total: 0, thumbs_done: 0, thumbs_made: 0, is_complete: false };
act('generations.syncImages');
await waitFor('the dialog for none', () => byId('gen_sync_dialog')?.open && text('gen_sync_estimate'));
act('generations.startSync');
await waitFor('the third start', () => posted.length > 2 && text('gen_sync_text').startsWith('Looking for images'));
progress = { ...progress, state: 'done', is_complete: true };
await waitFor('the end with none', () => text('gen_sync_text').startsWith('Every'));
check('none needed is said so, not left blank', text('gen_sync_text'), 'Every image has a thumbnail already.');

// ------------------------------------------------- Start, beside each image
// The folder box is hidden there: what it holds is not sent, so a path left
// in it can neither be refused nor saved.
settings = { ...settings, thumbnails_place: 'Beside each image' };
act('generations.syncImages');
await waitFor('the dialog beside each image', () => place('Beside each image')?.checked);
if (byId('gen_sync_thumbs_folder')) byId('gen_sync_thumbs_folder').value = 'not/a/full/path';
progress = { ...progress, state: 'running', stage: 'thumbnails', is_complete: false };
act('generations.startSync');
await waitFor('the fourth start', () => posted.length > 3);
check('Start beside each image sends the place, and no folder',
      [posted[3]?.[1].place, 'folder' in (posted[3]?.[1] || {})], ['Beside each image', false]);

done();

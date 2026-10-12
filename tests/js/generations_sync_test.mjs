// Sync images (#233), the Generations tab's side, against a stand-in server.
//
// A sync already running when the page loads is followed at once. The
// button opens a dialog: the folders - Forge's, read from its settings, and
// added ones - each ticked or not and counted, the level for images with no
// text, whether to group them, and what the ticked folders hold. Start
// waits for something new to add. Started, a panel follows the job - what it
// is reading, how far, what could not be read - with Cancel while it runs and
// Close once it ends, and the tab reloads to show what came in.
import { act, checker, mountTab, startTab, tick } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
const { check, waitFor, done } = checker();
window.mmTiming = { poll: 30 };

const FORGE = 'C:/webui/outputs/txt2img-images';
const IMG2IMG = 'C:/webui/outputs/img2img-images';
const ADDED = 'D:/old pictures';
let progress = { state: 'running', stage: 'reading', folder: FORGE, total: 10, read: 4, generations: 0, images: 0,
                 errors: [], error_count: 0, cancelling: false, is_complete: false };
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
        return reply({ success: true, samplers: [], schedulers: [], generations_hide_nsfw: false, generations_enabled: true });
    }
    if (href.includes('/generations/sync/folders')) {
        return reply({ success: true, level: 'Unknown', group: true, levels: ['PG', 'PG-13', 'R', 'X', 'XXX', 'Unknown'],
                       folders: [{ path: FORGE, key: 'outdir_txt2img_samples', forge: true, ticked: true },
                                 { path: IMG2IMG, key: 'outdir_img2img_samples', forge: true, ticked: false },
                                 { path: ADDED, key: null, forge: false, ticked: true }] });
    }
    if (href.includes('/generations/sync/estimate')) {
        return reply({ success: true, counts: { [FORGE]: 1200, [IMG2IMG]: 30, [ADDED]: 0 } });
    }
    if (href.includes('/generations/sync/progress')) return reply({ success: true, progress });
    if (href.includes('/model-manager/generations/browse')) {
        browses += 1;
        return reply({ success: true, tiles: [], more: false, scope: { count: 0 },
                       state: { total: 0, filtered: 0, hidden_nsfw: 0, nsfw_count: 0 } });
    }
    return reply({ success: true, notes: [] });
};

const panel = () => document.getElementById('gen_sync_panel');
const text = (id) => document.getElementById(id).textContent.trim();

await startTab('generations');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

// ---------------------------------------------------- a sync already running
await waitFor('the running sync', () => !panel().hidden && text('gen_sync_text'));
check('a sync running when the page loads is followed at once', text('gen_sync_text'),
      `Reading 4 of 10 images in ${FORGE}`);
check('while it runs, Cancel is offered and Sync images is not',
      [document.getElementById('gen_sync_cancel').hidden, document.getElementById('gen_sync_btn').disabled], [false, true]);
progress = { ...progress, state: 'done', stage: 'writing', images: 10, generations: 3, is_complete: true };
const before = browses;
await waitFor('the end', () => text('gen_sync_text').startsWith('Added'));
check('once it ends, it says what came in', text('gen_sync_text'), 'Added 10 images as 3 generations.');
check('Close takes Cancel\'s place, and Sync images is offered again',
      [document.getElementById('gen_sync_cancel').hidden, document.getElementById('gen_sync_close').hidden,
       document.getElementById('gen_sync_btn').disabled], [true, false, false]);
await waitFor('the reload', () => browses > before);
check('and the tab reloads to show it', browses > before, true);
act('generations.closeSyncPanel');
check('Close hides the panel', panel().hidden, true);

// ----------------------------------------------------------------- the dialog
const dialog = document.getElementById('gen_sync_dialog');
act('generations.syncImages');
await waitFor('the counts', () => text('gen_sync_estimate').includes('new images'));
const rows = () => Array.from(dialog.querySelectorAll('#gen_sync_folders .mm-dialog-option')).map((row) =>
    [row.querySelector('input').checked, row.querySelector('span').textContent, row.querySelector('.mm-dialog-count').textContent]);
check('the dialog lists Forge\'s folders, then the added one, each ticked as kept and counted', rows(),
      [[true, FORGE, '1,200 new'], [false, IMG2IMG, '30 new'], [true, ADDED, '0 new']]);
check('it says what the ticked folders hold', text('gen_sync_estimate'),
      '1,200 new images. Reading their text takes under a minute; writing them comes after.');
check('the level and the grouping start from the settings',
      [document.getElementById('gen_sync_level').value, document.getElementById('gen_sync_group').checked], ['Unknown', true]);
check('Start is offered', document.getElementById('gen_sync_start').disabled, false);

tick('generations.syncTick', false, { path: FORGE });
check('with only folders holding nothing new ticked, Start would do nothing, and says so',
      [document.getElementById('gen_sync_start').disabled, text('gen_sync_estimate')],
      [true, 'No new images in the ticked folders.']);
tick('generations.syncTick', false, { path: ADDED });
check('with none ticked, it asks for one', text('gen_sync_estimate'), 'Tick a folder to sync.');
tick('generations.syncTick', true, { path: FORGE });
tick('generations.syncTick', true, { path: IMG2IMG });
document.getElementById('gen_sync_level').value = 'PG';
document.getElementById('gen_sync_group').checked = false;

progress = { state: 'running', stage: 'walking', folder: FORGE, total: 0, read: 0, generations: 0, images: 0,
             errors: [], error_count: 0, cancelling: false, is_complete: false };
act('generations.startSync');
await waitFor('the start', () => posted.length);
check('Start sends the ticked folders, the level and the grouping',
      [posted[0][0], JSON.parse(posted[0][1].folders), posted[0][1].level, posted[0][1].group],
      ['/model-manager/generations/sync', [FORGE, IMG2IMG], 'PG', 'false']);
await waitFor('the dialog closed and the panel shown', () => dialog.style.display === 'none' && !panel().hidden);
check('the dialog closes, and the panel follows the sync', text('gen_sync_text'), `Looking for new images in ${FORGE}...`);

// ------------------------------------------------- errors, cancel, how it ended
progress = { ...progress, stage: 'reading', total: 1230, read: 615, error_count: 2,
             errors: [`could not read ${FORGE}/00001.png: truncated`, `could not read ${FORGE}/00002.png: truncated`] };
await waitFor('the reading', () => text('gen_sync_text').startsWith('Reading'));
check('it says how far it has got', text('gen_sync_text'), `Reading 615 of 1,230 images in ${FORGE}`);
check('and the bar shows it', document.getElementById('gen_sync_fill').style.width, '50%');
check('what could not be read is listed',
      [document.getElementById('gen_sync_errors').hidden, text('gen_sync_errors_summary'),
       document.querySelectorAll('#gen_sync_errors_list li').length], [false, '2 could not be read', 2]);
act('generations.cancelSync');
await waitFor('the cancel', () => posted.length === 2);
check('Cancel asks the server to stop, and cannot be pressed twice',
      [posted[1][0], document.getElementById('gen_sync_cancel').disabled], ['/model-manager/generations/sync/cancel', true]);
progress = { ...progress, state: 'cancelled', stage: 'writing', images: 400, generations: 120, is_complete: true,
             cancelling: true };
await waitFor('the cancelled end', () => text('gen_sync_text').startsWith('Cancelled'));
check('a cancelled sync says what it added before it stopped', text('gen_sync_text'),
      'Cancelled. 400 images were added as 120 generations before it stopped; the next sync adds the rest.');

done();

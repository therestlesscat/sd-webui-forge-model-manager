// Sync images (#233), the Generations tab's side, against a stand-in server.
//
// A sync already running when the page loads is followed at once. The
// button opens a dialog: the folders - Forge's, read from its settings, and
// added ones - each ticked or not and counted, the level for images with no
// text, whether to group them, and what the ticked folders hold. Start
// waits for something new to add. Started, a panel follows the job - what it
// is reading, how far, what could not be read - with Cancel while it runs and
// Close once it ends, and the tab reloads to show what came in. A folder is
// added by its path, and an added one removed - asked first, in its line,
// naming the generations it takes; Forge's own are only unticked.
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
let folders = [{ path: FORGE, key: 'outdir_txt2img_samples', forge: true, ticked: true, synced: 0 },
               { path: IMG2IMG, key: 'outdir_img2img_samples', forge: true, ticked: false, synced: 0 },
               { path: ADDED, key: null, forge: false, ticked: true, synced: 7 }];
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => structuredClone(body) });
    if (init.method === 'POST') {
        const path = new URL(href, 'http://x').pathname;
        const fields = Object.fromEntries(new URLSearchParams(String(init.body)));
        posted.push([path, fields]);
        if (path.endsWith('/folders/add')) {
            if (fields.path === 'pictures') return reply({ success: false, error: "Give the folder's full path, from its drive." });
            folders = [...folders, { path: fields.path, key: null, forge: false, ticked: true, synced: 0 }];
            return reply({ success: true, path: fields.path });
        }
        if (path.endsWith('/folders/remove')) {
            folders = folders.filter((f) => f.path !== fields.path);
            return reply({ success: true, removed: 7 });
        }
        return reply({ success: true });
    }
    if (href.includes('/model-manager/ui-options')) {
        return reply({ success: true, samplers: [], schedulers: [], generations_hide_nsfw: false, generations_enabled: true });
    }
    if (href.includes('/generations/sync/folders')) {
        return reply({ success: true, level: 'Unknown', group: true, levels: ['PG', 'PG-13', 'R', 'X', 'XXX', 'Unknown'],
                       folders });
    }
    if (href.includes('/generations/sync/estimate')) {
        return reply({ success: true, counts: { [FORGE]: 1200, [IMG2IMG]: 30, [ADDED]: 0 },
                       again: { [FORGE]: 0, [IMG2IMG]: 0, [ADDED]: 40, 'E:/more': 0 } });
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
const text = (id) => (document.getElementById(id)?.textContent || '').trim();

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


// ------------------------------------------------- adding and removing folders
act('generations.syncImages');
await waitFor('the dialog again', () => text('gen_sync_estimate').includes('new images'));
// Missing, as before 0.58.2, they stand in empty: the checks fail, not the suite.
const box = document.getElementById('gen_sync_add_path') || document.createElement('input');
const add = document.getElementById('gen_sync_add') || document.createElement('button');
const removes = () => Array.from(dialog.querySelectorAll('[data-action="generations.askRemoveSyncFolder"]'))
    .map((b) => b.dataset.path);
check('the box starts empty, and Add waits for a path', [box.value, add.disabled], ['', true]);
check('only an added folder offers Remove: Forge\'s are unticked', removes(), [ADDED]);
tick('generations.syncTick', false, { path: FORGE });
box.value = 'pictures';
box.dispatchEvent(new window.Event('input', { bubbles: true }));
check('typing a path offers Add', add.disabled, false);
act('generations.addSyncFolder');
await waitFor('the refusal', () => document.getElementById('gen_sync_add_note')?.hidden === false);
check('a path the server refuses says why, and keeps what was typed',
      [text('gen_sync_add_note'), box.value], ["Not added: Give the folder's full path, from its drive.", 'pictures']);
const NEW = 'E:/more';
box.value = NEW;
box.dispatchEvent(new window.Event('input', { bubbles: true }));
act('generations.addSyncFolder');
await waitFor('the new line', () => rows().length === 4 && !rows().some((r) => r[2] === 'counting...'));
check('an added folder is sent, listed, and counted; the ticks given meanwhile are kept',
      [posted.at(-1), rows().map((r) => [r[0], r[1]]), box.value, document.getElementById('gen_sync_add_note')?.hidden],
      [['/model-manager/generations/sync/folders/add', { path: NEW }],
       [[false, FORGE], [false, IMG2IMG], [true, ADDED], [true, NEW]], '', true]);

act('generations.askRemoveSyncFolder', { path: ADDED });
const asking = () => dialog.querySelector('.gen-sync-remove');
check('Remove asks first, in the folder\'s line, naming what it takes',
      asking()?.querySelector('span')?.textContent, `Remove ${ADDED}, and the 7 generations synced from it? The image files stay.`);
act('generations.keepSyncFolder', { path: ADDED });
check('Keep puts the line back, and nothing is sent',
      [asking(), posted.at(-1)[0]], [null, '/model-manager/generations/sync/folders/add']);
const shown = browses;
act('generations.askRemoveSyncFolder', { path: ADDED });
act('generations.removeSyncFolder', { path: ADDED });
await waitFor('the removal', () => rows().length === 3 && !rows().some((r) => r[2] === 'counting...'));
check('Remove sends the folder, and the line goes', [posted.at(-1), rows().map((r) => r[1])],
      [['/model-manager/generations/sync/folders/remove', { path: ADDED }], [FORGE, IMG2IMG, NEW]]);
await waitFor('the tab reloaded', () => browses > shown);
check('it says what went, and the tab reloads', [text('gen_sync_add_note'), browses > shown],
      ['Removed the folder, and 7 generations.', true]);

// ------------------------------------------------------- Force sync (#246)
// A box reads the synced images again. It is asked for each time: a dialog
// opened anew starts with it off.
folders = [...folders, { path: ADDED, key: null, forge: false, ticked: true, synced: 7 }];
act('generations.closeSyncDialog');
act('generations.syncImages');
await waitFor('the dialog once more', () => text('gen_sync_estimate').includes('new'));
const force = document.getElementById('gen_sync_force') || document.createElement('input');
tick('generations.syncTick', false, { path: FORGE });
tick('generations.syncTick', false, { path: IMG2IMG });
check('the box starts off, and a folder with nothing new leaves Start waiting',
      [force.checked, document.getElementById('gen_sync_start').disabled], [false, true]);
force.checked = true;
act('generations.syncForce');
const added = () => rows().find((r) => r[1] === ADDED);
check('ticked, the estimate and the folder\'s line count what is read again, and Start is offered',
      [text('gen_sync_estimate').startsWith('0 new, 40 to read again.'), added()?.[2],
       document.getElementById('gen_sync_start').disabled],
      [true, '0 new · 40 again', false]);
const sent = posted.length;
act('generations.startSync');
await waitFor('the forced start', () => posted.length > sent);
check('Start asks for a Force sync', [posted.at(-1)[0], posted.at(-1)[1].force],
      ['/model-manager/generations/sync', 'true']);
progress = { state: 'done', stage: 'writing', folder: ADDED, total: 40, read: 40, generations: 12, images: 40, again: 40,
             errors: [], error_count: 0, cancelling: false, is_complete: true };
await waitFor('the forced end', () => text('gen_sync_text').includes('read again'));
check('its end says how many were read again', text('gen_sync_text'),
      'Added 40 images as 12 generations, 40 of them read again.');
act('generations.closeSyncPanel');
act('generations.syncImages');
await waitFor('the dialog reopened', () => text('gen_sync_estimate').length > 0);
check('opened again, the box is off', document.getElementById('gen_sync_force')?.checked, false);

done();

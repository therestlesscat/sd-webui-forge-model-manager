// "Select" in the Generations tab (#21): a tick on every batch and image,
// never on a group; shift-click ticks a range, Select all loaded every tile;
// and one Delete for all of them, asked once - how many images, of how many
// generations, how many of them the NSFW filter hides - in one request. A
// batch's tick is the whole generation, as its own Delete. Select and Rate
// are not on together. The server's side: generations_test.py.
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
const { check, waitFor, done } = checker();

const img = (id, generation, level = 1) => ({
    id, generation_id: generation, width: 832, height: 1216, meta: { prompt: `prompt ${id}` },
    infotext: `prompt ${id}`, url: `/model-manager/generations/images/${id}/file`, exists: true,
    mm_level: level, user_level: null, prompt_level: level,
});
// As the page is sent them, NSFW hidden: G3 four of its five (one X hidden),
// G2 its one, G1 its three.
const TILES = [
    { kind: 'generation', generation: { id: 3, mode: 'txt2img', image_count: 5 }, matching_count: 4,
      images: [img(31, 3), img(33, 3), img(34, 3), img(35, 3)] },
    { kind: 'generation', generation: { id: 2, mode: 'txt2img', image_count: 1 }, matching_count: 1,
      images: [img(21, 2)] },
    { kind: 'generation', generation: { id: 1, mode: 'txt2img', image_count: 3 }, matching_count: 3,
      images: [img(11, 1), img(12, 1), img(13, 1)] },
];
const GROUP = { kind: 'group', generation: TILES[0].generation, matching_count: 8, images: [img(31, 3)],
                group: { id: 'g', value: '832×1216', latest: '2026-09-28', generations: 3 } };
let tiles = TILES;
const deletes = [];
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/generations/delete-many')) {
        deletes.push(Object.fromEntries(new URLSearchParams(String(init.body))));
        return reply({ success: true, images: 9, deleted_files: 8, failed: [] });
    }
    if (href.includes('/generations/browse')) {
        const params = new URL(href, 'http://webui').searchParams;
        // Grouped, the top level is groups; inside one, its batches.
        const grouped = params.get('group') === 'size' && !params.get('in_group');
        return reply({ success: true, tiles: grouped ? [GROUP] : tiles, more: false,
                       state: { total: 9, filtered: 8, hidden_nsfw: 1, nsfw_count: 1, hide_nsfw_images: true,
                                stored_generations: 3 },
                       scope: { count: 8 } });
    }
    if (href.includes('/model-manager/ui-options')) return reply({ success: true, gallery_hide_nsfw: true });
    return reply({ success: true });
};

await import(`file:///${ROOT}/javascript/generations.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => document.getElementById(id);
const ticks = () => Array.from(document.querySelectorAll('#gen_grid [data-gen-pick]'));
const bar = () => $('gen_select_bar');
const count = () => bar()?.querySelector('.mm-select-count')?.textContent;
const buttons = () => Array.from(bar()?.querySelectorAll('button') || []);
const button = (text) => buttons().find((b) => b.textContent.trim() === text);
// This DOM does not run inline handlers: the tick's own label's is run here,
// as a browser would, so one that stops the click before the page counts it fails.
const runInline = (box) => {
    const label = box.closest('label');
    const code = label?.getAttribute('onclick');
    if (code && !label.inlineRun) {
        label.addEventListener('click', new Function('event', code));
        label.inlineRun = true;
    }
};
const pick = (i, shift = false) => {
    const box = ticks()[i];
    runInline(box);
    box.checked = !box.checked;
    box.dispatchEvent(Object.assign(new window.Event('click', { bubbles: true }), { shiftKey: shift }));
};
await waitFor('the tiles', () => document.querySelectorAll('#gen_grid .gen-tile').length === 3);

check('Select is off to start: no ticks, no bar', [$('gen_select').checked, ticks().length, bar().hidden],
      [false, 0, true]);
window.genSetSelecting(true);
check('on: a tick on every batch and image, and a bar with nothing to delete yet',
      [ticks().length, bar().hidden, count(), button('Clear').disabled, button('Delete...').disabled],
      [3, false, '0 images selected', true, true]);

pick(0);
check('a batch\'s tick is the whole generation - its hidden image too', count(), '5 images selected');
pick(2, true);
check('shift-click ticks the range', [ticks().map((b) => b.checked), count()], [[true, true, true], '9 images selected']);
// (This DOM does not run inline handlers: the bar's buttons are read, and their functions run.)
check('the bar\'s buttons call Select\'s functions', buttons().map((b) => b.getAttribute('onclick')),
      ['window.genSelectAll()', 'window.genSelectClear()', 'window.genDeleteSelected()']);
window.genSelectClear();
check('Clear unticks them all', [ticks().some((b) => b.checked), count()], [false, '0 images selected']);
// A click anywhere on a tile's image ticks it: no viewer, and a batch is not opened.
const media = (i) => document.querySelectorAll('#gen_grid .gen-tile')[i].querySelector('.gen-media img');
const clickImage = (i, shift = false) => media(i).dispatchEvent(
    Object.assign(new window.Event('click', { bubbles: true }), { shiftKey: shift }));
clickImage(1);
check('a click on an image ticks it, and opens no viewer', [ticks()[1].checked, !!document.querySelector('.mm-viewer')],
      [true, false]);
clickImage(0);
check('nor, on a batch, the batch: it is ticked', [ticks()[0].checked, !document.querySelector('#gen_path .mm-btn')],
      [true, true]);
clickImage(1);
check('a second click unticks it', ticks()[1].checked, false);
// (This DOM does not run the image's own inline click; were it to get through, it does nothing.)
window.genView(1, 0);
await window.genOpen(0);
check('selecting, the viewer and a batch do not open, however asked',
      [!!document.querySelector('.mm-viewer'), !document.querySelector('#gen_path .mm-btn')], [false, true]);
window.genSelectClear();
clickImage(0);
clickImage(2, true);
check('and shift-click on an image ticks the range', ticks().map((b) => b.checked), [true, true, true]);
window.genSelectClear();
window.genSelectAll();
check('Select all loaded ticks every tile', [ticks().every((b) => b.checked), count()], [true, '9 images selected']);

const deleting = window.genDeleteSelected();
await waitFor('the question', () => document.querySelector('.mm-dialog-backdrop'));
const dialog = document.querySelector('.mm-dialog-backdrop');
check('Delete asks once: how many images, of how many generations, how many hidden',
      dialog.querySelector('h3')?.textContent, 'Delete 9 images of 3 generations? (1 of them hidden by the NSFW filter)');
dialog.querySelector('[data-files]').checked = true;
dialog.querySelector('[data-confirm]').dispatchEvent(new window.Event('click', { bubbles: true }));
await deleting;
check('in one request: the batches whole, the image alone, the files as asked',
      deletes, [{ generation_ids: '3,1', image_ids: '21', delete_files: 'true' }]);
check('and their tiles go, and the selection with them',
      [document.querySelectorAll('#gen_grid .gen-tile').length, count()], [0, '0 images selected']);

tiles = TILES;
await window.genRefresh();
await waitFor('the tiles again', () => document.querySelectorAll('#gen_grid .gen-tile').length === 3);
window.genSetRating(true);
check('Rate turns Select off', [$('gen_select').checked, ticks().length, bar().hidden], [false, 0, true]);
window.genSetSelecting(true);
check('and Select turns Rate off', $('gen_rate').checked, false);

window.genSetGroupBy('size');
await waitFor('the groups', () => document.querySelector('#gen_grid .gen-grouping'));
check('grouped, the top level is only groups, which have no tick: Select is hidden there, and off',
      [$('gen_select').closest('label').hidden, $('gen_select').checked, ticks().length, bar().hidden],
      [true, false, 0, true]);
tiles = TILES;
await window.genOpen(0);
await waitFor('the group opened', () => document.querySelectorAll('#gen_grid .gen-tile').length === 3);
check('opened, a group\'s batches can be picked: Select is back', $('gen_select').closest('label').hidden, false);
await window.genBack();
check('and hidden again back at the top', $('gen_select').closest('label').hidden, true);

done();

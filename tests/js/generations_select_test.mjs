// "Select" in the Generations tab (#21): a tick on every batch and image,
// never on a group; shift-click ticks a range, Select all loaded every tile;
// and one Delete for all of them, asked once - how many images, of how many
// generations, how many of them the NSFW filter hides - in one request. A
// batch's tick is the whole generation, as its own Delete. Select and Rate
// are not on together. The server's side: generations_test.py.
import { ROOT, act, call, checker, mountTab, press, startTab, tick } from './harness.mjs';

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
                       state: { total: 9, filtered: 8, hidden_nsfw: 1, nsfw_count: 1, nsfw_images: 'safe',
                                stored_generations: 3 },
                       scope: { count: 8 } });
    }
    if (href.includes('/model-manager/ui-options')) {
        return reply({ success: true, gallery_hide_nsfw: true, generations_delete_files: true });
    }
    return reply({ success: true });
};

await startTab('generations');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => document.getElementById(id);
const ticks = () => Array.from(document.querySelectorAll('#gen_grid [data-gen-pick]'));
const bar = () => $('gen_select_bar');
const count = () => bar()?.querySelector('.mm-select-count')?.textContent;
const buttons = () => Array.from(bar()?.querySelectorAll('button') || []);
const button = (text) => buttons().find((b) => b.textContent.trim() === text);
// The tick's click reaches the page's listener, which counts it: no markup
// holds a handler that could stop it (check_js_references.mjs).
const pick = (i, shift = false) => {
    const box = ticks()[i];
    box.checked = !box.checked;
    box.dispatchEvent(Object.assign(new window.Event('click', { bubbles: true }), { shiftKey: shift }));
};
await waitFor('the tiles', () => document.querySelectorAll('#gen_grid .gen-tile').length === 3);

check('Select is off to start: no ticks, no bar', [$('gen_select').checked, ticks().length, bar().hidden],
      [false, 0, true]);
// What a tile's image says a click does (#114): its cursor's class, and its title.
const looks = (i) => {
    const media = document.querySelectorAll('#gen_grid .gen-tile')[i]
        .querySelector('[data-action="generations.view"], [data-action="generations.open"]');
    return [['gen-viewable', 'gen-openable', 'gen-pickable'].filter((c) => media.classList.contains(c)),
            media.title];
};
const viewing = [[['gen-openable'], 'Open this generation: all 4 images'], [['gen-viewable'], 'View']];
check('off: an image says a click views it, a batch that it opens', [looks(0), looks(1)], viewing);
tick('generations.selecting', true);
check('on: a tick on every batch and image, and a bar with nothing to delete yet',
      [ticks().length, bar().hidden, count(), button('Clear').disabled, button('Delete...').disabled],
      [3, false, '0 images selected', true, true]);
check('on: an image and a batch say a click selects them, with no zoom-in cursor',
      [looks(0), looks(1)],
      [[['gen-pickable'], 'Select this generation: all 4 images'], [['gen-pickable'], 'Select']]);

pick(0);
check('a batch\'s tick is the whole generation - its hidden image too', count(), '5 images selected');
pick(2, true);
check('shift-click ticks the range', [ticks().map((b) => b.checked), count()], [[true, true, true], '9 images selected']);
check('the bar\'s buttons do what Select does', buttons().map((b) => b.dataset.action),
      ['generations.selectAll', 'generations.selectClear', 'generations.deleteSelected']);
press(button('Clear'));
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
// (In a browser Select takes the click on the way down, before the image's action; this DOM has no
// way down, and the action runs too - doing nothing while selecting, as asked here outright.)
act('generations.view', { tile: 1 });
await act('generations.open', { tile: 0 });
check('selecting, the viewer and a batch do not open, however asked',
      [!!document.querySelector('.mm-viewer'), !document.querySelector('#gen_path .mm-btn')], [false, true]);
act('generations.selectClear');
clickImage(0);
clickImage(2, true);
check('and shift-click on an image ticks the range', ticks().map((b) => b.checked), [true, true, true]);
act('generations.selectClear');
act('generations.selectAll');
check('Select all loaded ticks every tile', [ticks().every((b) => b.checked), count()], [true, '9 images selected']);

const deleting = act('generations.deleteSelected');
// The question open (#292).
const shownDialog = () => document.querySelector('dialog.mm-question[open]');
await waitFor('the question', shownDialog);
const dialog = shownDialog();
check('Delete asks once: how many images, of how many generations, how many hidden',
      dialog.querySelector('h3')?.textContent, 'Delete 9 images of 3 generations? (1 of them hidden by the filters)');
check('the files box starts ticked, as the setting says (#107)', dialog.querySelector('[data-tick]')?.checked, true);
dialog.querySelector('[data-value="true"]').dispatchEvent(new window.Event('click', { bubbles: true }));
await deleting;
check('in one request: the batches whole, the image alone, the files as asked',
      deletes, [{ generation_ids: '3,1', image_ids: '21', delete_files: 'true' }]);
check('and their tiles go, and the selection with them',
      [document.querySelectorAll('#gen_grid .gen-tile').length, count()], [0, '0 images selected']);

tiles = TILES;
await act('generations.refresh');
await waitFor('the tiles again', () => document.querySelectorAll('#gen_grid .gen-tile').length === 3);
tick('generations.rating', true);
check('Rate turns Select off', [$('gen_select').checked, ticks().length, bar().hidden], [false, 0, true]);
check('and the images say a click views them again', [looks(0), looks(1)], viewing);
tick('generations.selecting', true);
check('and Select turns Rate off', $('gen_rate').checked, false);

call('generations.groupBy', 'size');
await waitFor('the groups', () => document.querySelector('#gen_grid .gen-grouping'));
check('grouped, the top level is only groups, which have no tick: Select is hidden there, and off',
      [$('gen_select').closest('label').hidden, $('gen_select').checked, ticks().length, bar().hidden],
      [true, false, 0, true]);
tiles = TILES;
await act('generations.open', { tile: 0 });
await waitFor('the group opened', () => document.querySelectorAll('#gen_grid .gen-tile').length === 3);
check('opened, a group\'s batches can be picked: Select is back', $('gen_select').closest('label').hidden, false);
await act('generations.back');
check('and hidden again back at the top', $('gen_select').closest('label').hidden, true);

// A queued task of several checkpoints, one tile (#401): its tick, its Delete
// and its rating reach every generation it stood for when drawn, whole - and
// nothing else of the task.
call('generations.groupBy', '');
const TASK = { kind: 'task', task: { id: 9, checkpoints: 3, generations: [52, 51, 50], images: 4 },
               generation: { id: 52, mode: 'txt2img', image_count: 1 }, matching_count: 3,
               images: [img(521, 52), img(511, 51), img(501, 50)], level: 1, user_level: null };
tiles = [TASK, TILES[1]];
const ratings = [];
let ratingAnswer = null;
const fetchBeforeTask = globalThis.fetch;
globalThis.fetch = async (url, init = {}) => {
    if (String(url).includes('/generations/rate')) {
        ratings.push(Object.fromEntries(new URLSearchParams(String(init.body))));
        return { ok: true, json: async () => structuredClone(ratingAnswer) };
    }
    return fetchBeforeTask(url, init);
};
await act('generations.refresh');
await waitFor('the task tile', () => document.querySelectorAll('#gen_grid .gen-tile').length === 2);
tick('generations.selecting', true);
check('a task\'s tile has a tick, as the batch beside it', ticks().map((box) => Number(box.dataset.genPick)), [0, 1]);
if (ticks()[0]) pick(0);
check('ticked: every image of its generations, the one hidden too', count(), '4 images selected');
await press(button('Select all loaded'));
const deletingTask = (async () => press(button('Delete...')))();
await waitFor('the question', () => document.querySelector('dialog.mm-question[open]'));
const question = document.querySelector('dialog.mm-question[open]');
check('the one question counts the task\'s images and generations with the batch\'s, the one hidden too',
      question?.textContent.replace(/\s+/g, ' ').includes('Delete 5 images of 4 generations? (1 of them hidden by the filters)'),
      true);
question?.querySelector('[data-value="true"]')?.dispatchEvent(new window.Event('click', { bubbles: true }));
await deletingTask;
check('one request: the task\'s generations whole, the batch\'s image; both tiles gone',
      [deletes.at(-1)?.generation_ids, deletes.at(-1)?.image_ids, document.querySelectorAll('#gen_grid .gen-tile').length],
      ['52,51,50', '21', 0]);
tick('generations.selecting', false);

// Its own Delete, on its facts row.
tiles = [TASK, TILES[1]];
await act('generations.refresh');
await waitFor('the task tile again', () => document.querySelector('#gen_grid .gen-task'));
const own = (async () => call('generations.delete', { tile: 0 }))();
await waitFor('its question', () => document.querySelector('dialog.mm-question[open]'));
check('its Delete asks once, naming the task, its generations and images',
      document.querySelector('dialog.mm-question[open]')?.textContent.includes('Delete these 3 generations of task #9, 4 images?'),
      true);
document.querySelector('dialog.mm-question[open] [data-value="true"]')
    ?.dispatchEvent(new window.Event('click', { bubbles: true }));
await own;
check('and sends its generations alone, through Select\'s request, its files too as the box says',
      [deletes.at(-1)?.generation_ids, deletes.at(-1)?.image_ids, deletes.at(-1)?.delete_files], ['52,51,50', '', 'true']);

// Its rating row: the generations it stood for, no `generation`.
tiles = [TASK, TILES[1]];
await act('generations.refresh');
await waitFor('the task tile once more', () => document.querySelector('#gen_grid .gen-task'));
tick('generations.rating', true);
check('a rating row on the task tile, as on the batch', Array.from(document.querySelectorAll('#gen_grid .gen-tile'))
    .map((t) => !!t.querySelector('.mm-rate-chip')), [true, true]);
ratingAnswer = { success: true, rated: 3, tiles: [{ ...TASK, user_level: 4, level: 4 }], state: { total: 9, filtered: 8 },
                 scope: { count: 8 } };
await call('generations.rate', { tile: 0, level: 4 });
check('rated: the task\'s generations named, no generation - a server before it rates nothing',
      [ratings.at(-1)?.generations, 'generation' in (ratings.at(-1) || {})], ['52,51,50', false]);
check('its tile drawn again from the answer, alone', document.querySelector('#gen_grid .gen-task')
    ?.querySelector('.mm-rate-mine')?.textContent.trim(), 'R');
let reloaded = false;
const fetchBeforeReload = globalThis.fetch;
globalThis.fetch = async (url, init) => {
    if (String(url).includes('/generations/browse')) reloaded = true;
    return fetchBeforeReload(url, init);
};
ratingAnswer = { success: true, rated: 3, tiles: [TILES[0], TILES[1]], state: { total: 9, filtered: 8 }, scope: { count: 8 } };
await call('generations.rate', { tile: 0, level: 4 });
check('an answer of anything but one task tile - a cleared rating left one checkpoint\'s runs - asks the level again',
      reloaded, true);
await waitFor('the level again', () => document.querySelector('#gen_grid .gen-tile'));
tiles = [TASK, TILES[1]];
await act('generations.refresh');
await waitFor('the task tile, to hide', () => document.querySelector('#gen_grid .gen-task'));
ratingAnswer = { success: true, rated: 3, tiles: [], state: { total: 9, filtered: 5 }, scope: { count: 5 } };
await call('generations.rate', { tile: 0, level: 8 });
check('an answer of no tile - every image of it now hidden - takes the tile away',
      [document.querySelector('#gen_grid .gen-task'), document.querySelectorAll('#gen_grid .gen-tile').length], [null, 1]);
globalThis.fetch = fetchBeforeTask;
tick('generations.rating', false);

done();

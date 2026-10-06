// Grouping twice in the Generations tab (#4): Group by's menu, "Model", then
// in its "then by" list "Prompt, as written". The top level is the prompts'
// groups in sections, a header row per model; a prompt's group opens straight
// onto its batches, a batch onto its images - each asked of the server with
// what was opened (in_group the section, in_subgroup the group, generation),
// named on the path, Back one level at a time. Groups cannot be ticked, so
// Select is hidden among them. The server's side: generations_test.py.
import { ROOT, act, call, checker, mountTab, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
const { check, waitFor, done } = checker();

const img = (id, generation) => ({
    id, generation_id: generation, width: 832, height: 1216, meta: { prompt: `prompt ${id}` },
    infotext: `prompt ${id}`, url: `/model-manager/generations/images/${id}/file`, exists: true,
    mm_level: 1, user_level: null, prompt_level: 1,
});
const group = (id, value, by, count, section = null) => ({
    kind: 'group', generation: { id: 1, mode: 'txt2img', image_count: count }, matching_count: count,
    images: [img(id, 1)], group: { id: `g-${id}`, value, by, latest: '2026-09-30', generations: 2 },
    ...(section ? { section } : {}),
});
const MODEL_ONE = { id: 's-1', value: 'model-one', by: 'model', count: 3, groups: 2 };
const MODEL_TWO = { id: 's-2', value: 'model-two', by: 'model', count: 1, groups: 1 };
const BATCHES = [
    { kind: 'generation', generation: { id: 7, mode: 'txt2img', image_count: 2 }, matching_count: 2,
      images: [img(71, 7), img(72, 7)] },
    { kind: 'generation', generation: { id: 8, mode: 'txt2img', image_count: 1 }, matching_count: 1,
      images: [img(81, 8)] },
];
const IMAGES = [
    { kind: 'image', generation: { id: 7, mode: 'txt2img', image_count: 2 }, matching_count: 1, images: [img(71, 7)] },
    { kind: 'image', generation: { id: 7, mode: 'txt2img', image_count: 2 }, matching_count: 1, images: [img(72, 7)] },
];

const asked = [];
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/generations/browse')) {
        const params = new URL(href, 'http://webui').searchParams;
        const q = (key) => params.get(key) || '';
        asked.push([q('group'), q('in_group'), q('in_subgroup'), q('generation')]);
        let tiles = BATCHES;
        if (q('group') === 'model>prompt_written' && !q('generation')) {
            if (!q('in_group')) {
                tiles = [group(21, 'a fox', 'prompt_written', 2, MODEL_ONE), group(22, '', 'prompt_written', 1, MODEL_ONE),
                         group(23, 'a cat', 'prompt_written', 1, MODEL_TWO)];
            }
        }
        if (q('group') === 'base_model' && !q('in_group')) {
            tiles = [group(31, 'Illustrious', 'base_model', 2), group(32, '', 'base_model', 1)];
        }
        if (q('generation')) tiles = IMAGES;
        return reply({ success: true, tiles, more: false,
                       state: { total: 4, filtered: 4, hidden_nsfw: 0, nsfw_count: 0, hide_nsfw_images: true,
                                stored_generations: 2 },
                       scope: { count: 3 } });
    }
    if (href.includes('/model-manager/ui-options')) return reply({ success: true, gallery_hide_nsfw: true });
    return reply({ success: true });
};

await startTab('generations');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => document.getElementById(id);
const tileKinds = () => Array.from(document.querySelectorAll('#gen_grid .gen-tile'))
    .map((t) => (t.querySelector('.gen-group-name') ? 'group' : 'tile'));
const names = () => Array.from(document.querySelectorAll('#gen_grid .gen-group-name')).map((n) => n.textContent);
const trail = () => Array.from(document.querySelectorAll('#gen_path .gen-path-trail > span:not(.gen-path-sep)'))
    .map((s) => s.textContent);
const selectHidden = () => $('gen_select').closest('label').hidden;
const last = () => asked[asked.length - 1];
await waitFor('the tiles', () => document.querySelectorAll('#gen_grid .gen-tile').length === 2);

// Group by is a menu: the groupings, each with a "then by" list beside it.
const click = (el) => el?.dispatchEvent(new window.Event('click', { bubbles: true }));
const list = () => document.querySelector('#generations_app .gen-group-list');
const item = (key) => list().querySelector(`.gen-group-item[data-group-first="${key}"]`);
const texts = (els) => Array.from(els).map((e) => e.textContent.replace('▸', '').trim());
check('Group by shows what it groups by, its list closed', [$('gen_group_by').textContent, list().hidden],
      ['Nothing', true]);
click($('gen_group_by'));
check('a click opens it: Nothing, and the seven groupings',
      [list().hidden, texts(list().querySelectorAll(':scope > button, .gen-group-item > button'))],
      [false, ['Nothing', 'Prompt, as written', 'Prompt, as generated', 'Base model', 'Model', 'LoRA combination',
               'Size', 'Day']]);
check('no "then by" list open yet', Array.from(list().querySelectorAll('.gen-group-sub')).some((s) => !s.hidden), false);
item('model').dispatchEvent(new window.Event('mouseover', { bubbles: true }));
check('over a grouping, its "then by" list opens beside it: any other grouping',
      [item('model').querySelector('.gen-group-sub').hidden,
       texts(item('model').querySelectorAll('.gen-group-sub button'))],
      [false, ['Prompt, as written', 'Prompt, as generated', 'Base model', 'LoRA combination', 'Size', 'Day']]);
item('day').dispatchEvent(new window.Event('mouseover', { bubbles: true }));
check('over another, its list instead', [item('day').querySelector('.gen-group-sub').hidden,
      item('model').querySelector('.gen-group-sub').hidden], [false, true]);
click(item('day').querySelector(':scope > button'));
await waitFor('grouped by day', () => last()[0] === 'day');
check('a click on a grouping groups by it alone, and closes the list',
      [last(), list().hidden, $('gen_group_by').textContent], [['day', '', '', ''], true, 'Day']);
click($('gen_group_by'));
item('model').dispatchEvent(new window.Event('mouseover', { bubbles: true }));
click(Array.from(item('model').querySelectorAll('.gen-group-sub button')).find((b) => b.textContent === 'Prompt, as written'));
await waitFor('the sections', () => names().includes('a fox'));
check('picked there: the list closes, and the button says both',
      [list().hidden, $('gen_group_by').textContent], [true, 'Model › Prompt, as written']);
const heads = () => Array.from(document.querySelectorAll('#gen_grid .gen-section-head'))
    .map((h) => [h.querySelector('.gen-section-name')?.textContent, h.querySelector('.gen-section-facts')?.textContent]);
check('grouped twice, asked as a pair: the second grouping\'s groups, under a header row per group of the first',
      [last(), heads(), names(), selectHidden()],
      [['model>prompt_written', '', '', ''], [['Model: model-one', '2 prompts · 3 images'], ['Model: model-two', '1 prompt · 1 image']],
       ['a fox', 'None', 'a cat'], true]);
check('each header above its own groups, and nothing packed above it',
      [Array.from(document.querySelectorAll('#gen_grid .gen-set')).map((set) => !!set.querySelector('.gen-section-head')),
       document.getElementById('gen_grid').classList.contains('gen-sectioned')],
      [[true, false, true], true]);
click($('gen_group_by'));
check('opened again, what is chosen is marked, its "then by" list open',
      [texts(list().querySelectorAll('.gen-group-chosen')), item('model').querySelector('.gen-group-sub').hidden],
      [['Model', 'Prompt, as written'], false]);
document.dispatchEvent(Object.assign(new window.Event('keydown'), { key: 'Escape' }));
check('Esc closes it, and goes back nowhere', [list().hidden, last()[0]], [true, 'model>prompt_written']);
click($('gen_group_by'));
click(document.body);
check('as does a click anywhere else', list().hidden, true);

check('a group\'s tooltip names its own grouping',
      document.querySelector('#gen_grid .gen-group-name')?.getAttribute('title'), 'Prompt, as written: a fox');

await act('generations.open', { tile: 0 });
await waitFor('the batches', () => last()[2] === 'g-21' && !names().length);
check('a group opens straight onto its batches, in it and its section; Select is back',
      [last(), tileKinds(), selectHidden(), heads()],
      [['model>prompt_written', 's-1', 'g-21', ''], ['tile', 'tile'], false, []]);
check('the path names both', trail(), ['Generations', 'Model: model-one › Prompt, as written: a fox']);

await act('generations.open', { tile: 0 });
await waitFor('the images', () => last()[3] === '7');
check('a batch there is asked for within both', last(), ['model>prompt_written', 's-1', 'g-21', '7']);

await act('generations.back');
await act('generations.back');
check('Back, twice, is the sections again, Select hidden',
      [heads().length, names(), selectHidden()], [2, ['a fox', 'None', 'a cat'], true]);

// By base model (#35): the checkpoint's, as the library holds it; one the
// library has none for is Unknown.
await call('generations.groupBy', 'base_model');
await waitFor('the base models', () => names().includes('Illustrious'));
check('by base model, a checkpoint the library has none for is Unknown', names(), ['Illustrious', 'Unknown']);

await call('generations.groupBy', 'model>nonsense');
await waitFor('ungrouped', () => last()[0] === '');
check('a pair that is not one is no grouping', [last(), selectHidden()], [['', '', '', ''], false]);

done();

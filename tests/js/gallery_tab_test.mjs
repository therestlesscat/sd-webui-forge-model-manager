// The Civitai Images tab (#209): the library's stored Civitai images, laid out as the
// Generations tab lays out your own, in an order a sorting seed picks.
//
// The seed is the server's, shown in the toolbar: typed, it is kept and the
// grid starts again from its top; New seed asks for another. Group by gathers
// a model's images into a tile, which opens onto them, with Back to where the
// groups were. The grid scrolls for more. The NSFW switch starts as the
// galleries' setting says. An image that names no checkpoint cannot be sent,
// and says why; Show model opens its version in the Model Manager. Group by
// goes two deep, "then by" another grouping, and the search asks the server
// for the images whose prompts hold its words (#283).
import { readFileSync } from 'node:fs';
import { ROOT, act, call, checker, mountTab, press, startTab, tabEntries, tabMarkup, tick } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_gallery.py');
const { check, waitFor, done } = checker();

const image = (id, extra = {}) => ({
    id, url: `https://image.civitai.com/x/original=true/${id}.jpeg`, width: 1024, height: 1536, mm_level: 1,
    mm_level_from_prompt: false, meta: { prompt: `a cat ${id}`, Model: 'someCheckpoint' }, ...extra,
});
const imageTile = (id, extra = {}) => ({
    kind: 'image', image: image(id, extra),
    model: { id: 40, name: 'A LoRA', civitai_type: 'LORA', model_type: 'LORA', base_model: 'SDXL 1.0' },
    version: { id: 400, name: 'v1', file_path: 'C:/models/Lora/a.safetensors', file_type: 'LORA', base_model: 'SDXL 1.0' },
});
// An embedding's image: its type said as the Type menus say it.
const embedding = (id) => ({ ...imageTile(id), model: { id: 41, name: 'An Embedding', civitai_type: 'TextualInversion',
                                                      model_type: 'TextualInversion', base_model: 'SD 1.5' } });
const STATE = { total: 30, filtered: 24, hidden_nsfw: 6, nsfw_count: 6 };

const browses = [];
const seeds = [];
let seed = 123;
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (href.includes('/model-manager/gallery/browse')) {
        const params = new URL(href, 'http://webui').searchParams;
        browses.push(params);
        const page = Number(params.get('page'));
        if (params.get('search') === 'nothing') {
            return reply({ success: true, seed, more: false, state: { total: 0, filtered: 0, hidden_nsfw: 0, nsfw_count: 0 },
                           scope: { count: 0 }, tiles: [] });
        }
        if (params.get('in_subgroup')) {
            return reply({ success: true, seed, more: false, state: { ...STATE, total: 3, filtered: 3 },
                           scope: { count: 3 }, tiles: [1, 2].map((id) => imageTile(id)) });
        }
        if (params.get('group') === 'model>day' && params.get('in_group')) {
            return reply({ success: true, seed, more: false, state: { ...STATE, total: 7, filtered: 7 },
                           scope: { count: 7, groups: 2 }, tiles: [
                { kind: 'group', group: { key: '2026-01-02', value: '2026-01-02', by: 'day', count: 3 }, matching_count: 3,
                  images: [image(1), image(2)] },
                { kind: 'group', group: { key: '2026-01-03', value: '2026-01-03', by: 'day', count: 4 }, matching_count: 4,
                  images: [image(3)] }] });
        }
        if (String(params.get('group') || '').startsWith('model') && !params.get('in_group')) {
            return reply({ success: true, seed, more: false, state: STATE, scope: { count: 30, groups: 2 }, tiles: [
                { kind: 'group', group: { key: 40, value: 'A LoRA', by: 'model', count: 7 }, matching_count: 7,
                  images: [image(1), image(2), image(3), image(4)] },
                { kind: 'group', group: { key: 41, value: 'B LoRA', by: 'model', count: 2 }, matching_count: 2,
                  images: [image(5), image(6)] }] });
        }
        if (params.get('in_group')) {
            return reply({ success: true, seed, more: false, state: { ...STATE, total: 7, filtered: 7 },
                           scope: { count: 7 }, tiles: [1, 2, 3].map((id) => imageTile(id)) });
        }
        const tiles = page === 1
            ? [imageTile(1), imageTile(2), imageTile(3, { meta: { prompt: 'no checkpoint named' } })]
            : [imageTile(4, { width: 1600, height: 900 }), embedding(5)];
        return reply({ success: true, seed, more: page === 1, state: STATE, scope: { count: 30 }, tiles });
    }
    if (href.includes('/model-manager/gallery/seed')) {
        const body = init.body instanceof URLSearchParams ? init.body : new URLSearchParams(String(init.body || ''));
        seeds.push(body.get('seed'));
        seed = body.get('seed') ? Number(body.get('seed')) : 999;
        return reply({ success: true, seed });
    }
    if (href.includes('/model-manager/ui-options')) {
        return reply({ success: true, samplers: [], schedulers: [], gallery_hide_nsfw: true });
    }
    return reply({ success: true });
};

// The Model Manager, for Show model: its entry stood in for, its markup there.
document.body.insertAdjacentHTML('beforeend', tabMarkup('model_manager/ui/tab_model_manager.py'));
await startTab('modelManager');
const shownVersions = [];
(await tabEntries('model_manager.mjs')).showVersion = async (...args) => { shownVersions.push(args); };

await startTab('gallery');
const $ = (id) => document.getElementById(id);
const tileEls = () => [...document.querySelectorAll('#gal_grid .gen-set')];
const lastBrowse = () => browses.at(-1);
// The end of the grid in view - it always is here - the next part follows the first.
await waitFor('the first two parts', () => tileEls().length === 5);

check('the first part asked for, ungrouped, the NSFW switch as the galleries\' setting says',
      [browses[0]?.get('page'), browses[0]?.get('group'), browses[0]?.get('hide_nsfw_images')], ['1', null, 'true']);
check('the end in view: the next part asked for, and added after the first',
      [browses[1]?.get('page'), tileEls().length], ['2', 5]);
check('the seed the server used, in the toolbar', $('gal_seed')?.value, '123');
check('a tile per image, each a Civitai copy, lazily', tileEls().map((el) => el.querySelector('img')?.getAttribute('data-src')?.includes('image.civitai.com')),
      [true, true, true, true, true]);
check('the banner counts what is stored', /30/.test($('gal_banner')?.textContent || ''), true);
check('each image\'s tile says what kind of model it is from, which, and its size',
      tileEls()[0]?.querySelector('.gen-date')?.textContent, 'LORA · A LoRA · 1024×1536');
check('a type said as the Type menus say it: an embedding, not TextualInversion',
      tileEls()[4]?.querySelector('.gen-date')?.textContent, 'Embedding · An Embedding · 1024×1536');
// A copy the width the tile draws: a column for a tall image, 320 wide; a
// wide one's tile spans columns, 300 x 16/9 = 533px, so 800.
const copyWidth = (index) => (tileEls()[index]?.querySelector('img')?.getAttribute('data-src') || '').match(/width=(\d+)/)?.[1];
check('each image\'s copy as wide as its tile draws it: a tall one 320, a wide one 800',
      [copyWidth(0), copyWidth(3)], ['320', '800']);

// ------------------------------------------------------------- what it shows
// A message on top says the tab shows only what is stored, and asks Civitai
// for nothing; closed, it stays closed in this browser.
const about = () => $('gal_about');
check('the message shows, saying where the images come from and how to get more',
      [about()?.hidden, /stored/.test(about()?.textContent || ''), /asks Civitai for nothing new/.test(about()?.textContent || ''),
       /Load More Images/.test(about()?.textContent || '')], [false, true, true, true]);
// Pressed only where it is drawn: without it, the checks fail rather than the suite.
if (document.querySelector('[data-action="gallery.closeAbout"]')) act('gallery.closeAbout');
check('Close hides it, and the browser remembers', [about()?.hidden, localStorage.getItem('mm_gallery_about_closed')],
      [true, 'true']);
check('a closed banner is not drawn: its display gives way to hidden',
      /\.mm-banner\[hidden\]\s*\{\s*display:\s*none;/.test(readFileSync(`${ROOT}/style.css`, 'utf8')), true);

// ------------------------------------------------------------- Send
const sendOf = (index) => tileEls()[index]?.querySelector('[data-action="gallery.send"]');
check('an image that names its checkpoint can be sent', sendOf(0)?.disabled, false);
check('one that names none cannot, and says why',
      [sendOf(2)?.disabled, /checkpoint/.test(sendOf(2)?.getAttribute('title') || '')], [true, true]);

// ------------------------------------------------------------- Show model
act('gallery.showModel', { tile: 0 });
await waitFor('the Model Manager asked', () => shownVersions.length > 0);
check('Show model opens its version in the Model Manager, at its file',
      shownVersions[0], [400, 'C:/models/Lora/a.safetensors']);

// ------------------------------------------------------------- the seed
const box = $('gal_seed');
box.value = '456';
const fromTop = browses.length;
act('gallery.seed');
await waitFor('the seed kept', () => seeds.length === 1);
await waitFor('the grid again', () => browses.length > fromTop && tileEls().length === 5);
check('a seed typed is kept, and the grid starts again from its top',
      [seeds[0], box.value, browses[fromTop]?.get('page')], ['456', '456', '1']);
box.value = 'abc';
act('gallery.seed');
check('anything but a whole number puts the kept seed back, asking nothing', [box.value, seeds.length], ['456', 1]);
act('gallery.newSeed');
await waitFor('a new seed', () => seeds.length === 2);
await waitFor('its seed in the box', () => box.value === '999');
check('New seed asks for one, and shows it', [seeds[1], box.value], [null, '999']);

// ------------------------------------------------------------- the NSFW switch
await waitFor('the banner', () => !!document.querySelector('[data-action="gallery.showNsfw"]'));
tick('gallery.showNsfw', true);
await waitFor('the grid with NSFW shown', () => lastBrowse()?.get('hide_nsfw_images') === 'false');
check('Show NSFW: asked again without hiding', lastBrowse()?.get('hide_nsfw_images'), 'false');

// ------------------------------------------------------------- Group by
call('gallery.groupBy', 'model');
await waitFor('the groups', () => tileEls().length === 2);
check('grouped by model: asked so, a tile per group, its count and its name',
      [lastBrowse()?.get('group'), tileEls().map((el) => el.querySelector('.gen-count')?.textContent),
       tileEls().map((el) => el.querySelector('.gen-group-name')?.textContent)],
      ['model', ['×7', '×2'], ['A LoRA', 'B LoRA']]);
check('the button says the grouping', $('gal_group_by')?.textContent, 'Model');
const before = browses.length;
act('gallery.open', { tile: 0 });
await waitFor('the group', () => tileEls().length === 3 && browses.length > before);
check('a group opens onto its images', lastBrowse()?.get('in_group'), '40');
check('with Back, and which group', [!!document.querySelector('[data-action="gallery.back"]'),
      /Model: A LoRA/.test($('gal_path')?.textContent || '')], [true, true]);
// Named for what it shows - Civitai's images of the library's models - in the
// tab bar, its heading and the path inside a group. The tab's id stays gallery.
const registered = readFileSync(`${ROOT}/scripts/model_manager_ui.py`, 'utf8').match(/create_gallery_ui\(\), "([^"]*)", "(\w+)"/);
check('the tab is called Civitai Images, its id still gallery_tab',
      [registered?.[1], registered?.[2]], ['Civitai Images', 'gallery_tab']);
check('so are its heading and the path inside a group',
      [document.querySelector('#gallery_app h2')?.textContent.trim(),
       $('gal_path')?.querySelector('.gen-path-trail span')?.textContent], ['Civitai Images', 'Civitai Images']);
const asked = browses.length;
act('gallery.back');
check('Back: the groups again, as they were, asking nothing', [tileEls().length, browses.length], [2, asked]);
check('and the path gone', $('gal_path')?.innerHTML.trim(), '');
call('gallery.groupBy', '');
await waitFor('ungrouped again', () => lastBrowse()?.get('group') === null && tileEls().length === 5);
check('Group by Nothing: the images again', $('gal_group_by')?.textContent, 'Nothing');

// ------------------------------------------------------------- two deep (#283)
// Each block reports what is missing as a failure, rather than stopping the suite.
const click = (el) => {
    if (!el) throw new Error('nothing to click');
    el.dispatchEvent(new window.Event('click', { bubbles: true }));
};
try {
click($('gal_group_by'));
const menu = document.querySelector('#gallery_app .gen-group-list');
const firsts = [...menu.querySelectorAll('.gen-group-item > [data-group-pick]')].map((b) => b.dataset.groupPick);
check('Group by offers the image\'s own groupings beside the gallery\'s: prompt, LoRAs, day',
      firsts, ['model', 'base_model', 'type', 'size', 'prompt', 'loras', 'day']);
check('and beside each, what to group its groups by then',
      [...menu.querySelectorAll('[data-group-first="model"] .gen-group-sub [data-group-pick]')].map((b) => b.dataset.groupPick),
      ['model>base_model', 'model>type', 'model>size', 'model>prompt', 'model>loras', 'model>day']);
click(menu.querySelector('[data-group-pick="model>day"]'));
await waitFor('grouped two deep', () => lastBrowse()?.get('group') === 'model>day' && tileEls().length === 2);
check('model, then day: asked so, and the button says both', $('gal_group_by')?.textContent, 'Model › Day');
act('gallery.open', { tile: 0 });
await waitFor('the model\'s days', () => lastBrowse()?.get('in_group') === '40' && tileEls().length === 2
    && tileEls()[0].querySelector('.gen-group-name')?.textContent === '2026-01-02');
check('a model\'s group opens onto its days, not its images', lastBrowse()?.get('in_subgroup'), null);
act('gallery.open', { tile: 0 });
await waitFor('the day\'s images', () => lastBrowse()?.get('in_subgroup') === '2026-01-02' && tileEls().length === 2);
check('a day opens onto its images, inside its model',
      [lastBrowse()?.get('in_group'), lastBrowse()?.get('in_subgroup')], ['40', '2026-01-02']);
check('the path names both groups',
      [...document.querySelectorAll('#gal_path *')].some((el) => /Model: A LoRA/.test(el.textContent))
      && [...document.querySelectorAll('#gal_path *')].some((el) => /Day: 2026-01-02/.test(el.textContent)), true);
const deep = browses.length;
act('gallery.back');
check('Back: the model\'s days again, asking nothing',
      [tileEls().map((el) => el.querySelector('.gen-group-name')?.textContent), browses.length],
      [['2026-01-02', '2026-01-03'], deep]);
act('gallery.back');
check('Back again: the models', [tileEls().length, $('gal_path')?.innerHTML.trim()], [2, '']);
} catch (error) {
    check('two deep: Group by\'s "then by", a group, a subgroup and Back', String(error), null);
}

// ------------------------------------------------------------- search (#283)
try {
const search = $('gal_search');
if (!search) throw new Error('no search box');
check('a search box, starting empty', search?.value, '');
search.value = 'a cat';
press(search);
await waitFor('the search asked', () => lastBrowse()?.get('search') === 'a cat');
check('a search keeps the grouping, from its top level',
      [lastBrowse()?.get('group'), lastBrowse()?.get('in_group'), lastBrowse()?.get('page')], ['model>day', null, '1']);
call('gallery.groupBy', '');
await waitFor('ungrouped, searched', () => lastBrowse()?.get('group') === null && tileEls().length === 5);
check('the banner says what the search found, not all that is stored',
      /found by the search/.test($('gal_banner')?.textContent || ''), true);
search.value = 'nothing';
press(search);
await waitFor('nothing found', () => lastBrowse()?.get('search') === 'nothing'
    && $('gal_status')?.textContent !== 'Loading...');
check('a search that finds nothing says so', [tileEls().length, $('gal_status')?.textContent],
      [0, 'No image matches the search.']);
const searched = browses.length;
search.value = '';
search.dispatchEvent(new window.Event('search'));
await waitFor('everything again', () => browses.length > searched && tileEls().length === 5);
check('its × empties it, and shows everything again: no search asked', lastBrowse()?.get('search') || '', '');
} catch (error) {
    check('search: the box, what it asks, what it says', String(error), null);
}

const source = readFileSync(`${ROOT}/javascript/tabs/gallery.mjs`, 'utf8');
check('the tab loads no module of your generations\' - what both tabs use is shared/grouping.mjs',
      [/['"]generations\.mjs['"]/.test(source), /tabs\/generations/.test(source), /['"]grouping\.mjs['"]/.test(source)],
      [false, false, true]);

done();

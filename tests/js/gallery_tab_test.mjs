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
// for the images whose prompts hold its words (#283). An image's ⋯ lists its
// checkpoints and LoRAs, asked of the server when pressed (#298).
import { readFileSync } from 'node:fs';
import { ROOT, act, call, checker, mountTab, press, sendLoaders, sharedModule, startTab, tabEntries, tabMarkup,
         tick } from './harness.mjs';

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
let withVideo = false;    // a video among the first part's tiles (#299)
let withResources = false;    // two images whose data names resources (#362)

// An image's ⋯ menu, as api/gallery.image_menu answers it (#298): a held
// checkpoint, a LoRA the library lacks, and one whose record names no model.
const menuAsks = [];
let menuHeld = null;         // a promise each answer waits for, while a check holds them
const menuOwnHolds = [];     // or, each answer its own: a check lets them go one by one
let holdEach = false;
let menuFails = false;
const menuItems = (id) => [
    { role: 'checkpoint', type: 'Checkpoint', model_id: 70, version_id: 701, name: `Base ${id}`, version_name: 'v7',
      file_path: 'C:/models/Stable-diffusion/base.safetensors' },
    { role: 'lora', type: 'LORA', model_id: 80, version_id: 801, name: 'Style', version_name: 'v8', file_path: null },
    { role: 'lora', type: 'LORA', model_id: null, version_id: 901, name: 'Nameless', version_name: '', file_path: null },
];

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
            ? [{ ...imageTile(1), menu: true }, { ...imageTile(2), menu: true },
               imageTile(3, { meta: { prompt: 'no checkpoint named' } }),
               ...(withVideo ? [imageTile(6, { url: 'https://image.civitai.com/x/original=true/6.mp4', type: 'video' })] : []),
               ...(withResources ? [
                   imageTile(7, { meta: { prompt: 'a cat 7', Model: 'someCheckpoint', civitaiResources: [
                       { type: 'checkpoint', modelVersionId: 701, name: 'Base', modelVersionName: 'v7' },
                       { type: 'lora', modelVersionId: 400, name: 'A LoRA', modelVersionName: 'v1' }] } }),
                   imageTile(8, { meta: { prompt: 'a cat 8', Model: 'someCheckpoint', civitaiResources: [
                       { type: 'lora', modelVersionId: 400, name: 'A LoRA', modelVersionName: 'v1' }] } })] : [])]
            : [imageTile(4, { width: 1600, height: 900 }), embedding(5)];
        return reply({ success: true, seed, more: page === 1, state: STATE, scope: { count: 30 }, tiles });
    }
    if (href.includes('/model-manager/gallery/menu')) {
        const params = new URL(href, 'http://webui').searchParams;
        menuAsks.push(params);
        if (menuHeld) await menuHeld;
        if (holdEach) await new Promise((resolve) => menuOwnHolds.push(resolve));
        return reply(menuFails ? { success: false, error: 'Gallery menu error: no database' }
            : { success: true, items: menuItems(params.get('image_id')) });
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
check('a group\'s tile has no ⋯: its images are of many models (#298)',
      tileEls().map((el) => !!el.querySelector('.gen-menu-btn')), [false, false]);
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

// ------------------------------------------------------------- the ⋯ menu (#298)
// An image's checkpoints and LoRAs, asked of the server when ⋯ is pressed:
// each in the Model Manager when the library holds it, in the Civitai Browser
// when it does not. Each block reports what is missing as a failure.
const menuEl = () => document.querySelector('.gen-menu');
const menuButton = (index) => tileEls()[index]?.querySelector('.gen-menu-btn');
// Show All and Resources first (#362), then the five sends into img2img (#299), then the Show items.
const TOP = 2;
const SENDS = 5;
const buttons = () => [...(menuEl()?.querySelectorAll('button') || [])];
const items = () => buttons().slice(TOP + SENDS).map((b) => [b.textContent.trim(), b.disabled]);
const titles = () => buttons().slice(TOP + SENDS).map((b) => b.getAttribute('title'));
const showItem = (index) => buttons()[TOP + SENDS + index];
try {
check('every image tile has ⋯ - its sends into img2img (#299) - whether the server says it has Show items or not',
      [0, 1, 2].map((i) => !!menuButton(i)), [true, true, true]);
let release;
menuHeld = new Promise((resolve) => { release = resolve; });
const before = menuAsks.length;
act('gallery.menu', { tile: 0 });
check('pressed: the server asked for that image\'s, by the image and its version',
      [menuAsks.length - before, menuAsks.at(-1)?.get('image_id'), menuAsks.at(-1)?.get('version_id')], [1, '1', '400']);
check('while it asks, ⋯ is disabled, saying so, and no menu is open',
      [menuButton(0)?.disabled, menuButton(0)?.getAttribute('title'), menuEl()], [true, 'Looking…', null]);
act('gallery.menu', { tile: 0 });
check('pressed again while it asks: nothing more asked', menuAsks.length - before, 1);
release();
menuHeld = null;
await waitFor('the menu', () => menuEl());
check('then the menu: a held checkpoint in the Model Manager; a LoRA it lacks in the Civitai Browser, greyed '
      + 'while that tab has not started; one with no model, greyed',
      items(), [['Show checkpoint Base 1 in Model Manager', false], ['Show LoRA Style in Civitai Browser', true],
                ['Show LoRA Nameless in Civitai Browser', true]]);
check('each saying why, and an item its version\'s name',
      titles(), ['v7', 'The Civitai Browser tab has not started yet', 'Civitai\'s record names no model for it']);
check('and ⋯ ready again', [menuButton(0)?.disabled, menuButton(0)?.getAttribute('title')], [false, 'More']);
check('first in it, Show All and Resources (#362): Resources greyed for an image whose data names none, saying so',
      [buttons().slice(0, TOP).map((b) => [b.textContent.trim(), b.disabled]), buttons()[1]?.getAttribute('title')],
      [[['Show All', false], ['Resources', true]], 'This image\'s data names no resources']);
const shownBefore = shownVersions.length;
showItem(0).dispatchEvent(new window.Event('click', { bubbles: true }));
// Read at once: the stand-in Model Manager is no tab Gradio can show, and the place is let go after.
const noted = localStorage.getItem('gal_scroll_target') || '';
await waitFor('the Model Manager asked', () => shownVersions.length > shownBefore);
check('the checkpoint opens in the Model Manager at its version and file, the menu closed',
      [shownVersions.at(-1), menuEl()], [[701, 'C:/models/Stable-diffusion/base.safetensors'], null]);
check('the place left noted first: this image, for ↓ Back to image',
      /image:1\b/.test(noted), true);

// The Civitai Browser started: the LoRA there, by its model and version.
document.body.insertAdjacentHTML('beforeend', tabMarkup('model_manager/ui/tab_civitai_browser.py'));
await startTab('civitaiBrowser');
const civitaiAsked = [];
(await tabEntries('civitai_browser.mjs')).showModel = (query) => { civitaiAsked.push(query); };
act('gallery.menu', { tile: 0 });
await waitFor('the menu again', () => menuEl());
showItem(1).dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the Civitai Browser asked', () => civitaiAsked.length);
check('the LoRA the library lacks opens in the Civitai Browser at its model and version',
      civitaiAsked, ['model:80 version:801']);

// Its own ⋯ again closes it, asking nothing (R4); another tile's opens that one's.
act('gallery.menu', { tile: 0 });
await waitFor('the menu, to press its ⋯ again', () => menuEl());
await new Promise((resolve) => setTimeout(resolve, 20));
const asksBefore = menuAsks.length;
act('gallery.menu', { tile: 0 });
await new Promise((resolve) => setTimeout(resolve, 20));
check('its own ⋯ pressed again: the menu closed, nothing asked', [menuEl(), menuAsks.length - asksBefore], [null, 0]);
act('gallery.menu', { tile: 0 });
await waitFor('the menu, for another tile', () => menuEl());
await new Promise((resolve) => setTimeout(resolve, 20));
act('gallery.menu', { tile: 1 });
await waitFor('the other tile\'s menu', () => items()[0]?.[0] === 'Show checkpoint Base 2 in Model Manager');
check('another tile\'s ⋯ with a menu open: that tile\'s menu, alone',
      [document.querySelectorAll('.gen-menu').length, items()[0]?.[0]], [1, 'Show checkpoint Base 2 in Model Manager']);
document.body.dispatchEvent(Object.assign(new window.Event('keydown', { bubbles: true }), { key: 'Escape' }));

// Esc, a scroll of the page and a resize of the window each close it; a
// scroll inside it does not.
act('gallery.menu', { tile: 0 });
await waitFor('the menu, for Esc', () => menuEl());
document.body.dispatchEvent(Object.assign(new window.Event('keydown', { bubbles: true }), { key: 'Escape' }));
check('Esc closes it', menuEl(), null);
act('gallery.menu', { tile: 0 });
await waitFor('the menu, for a scroll', () => menuEl());
menuEl().dispatchEvent(new window.Event('scroll'));
check('a scroll inside it leaves it open', !!menuEl(), true);
window.dispatchEvent(new window.Event('scroll'));
check('a scroll of the page closes it', menuEl(), null);
act('gallery.menu', { tile: 0 });
await waitFor('the menu, for a resize', () => menuEl());
window.dispatchEvent(new window.Event('resize'));
check('a resize of the window closes it', menuEl(), null);

// A late answer opens nothing: another ⋯ pressed meanwhile has its own. The
// second answers first; the first's, coming after, must not replace it.
holdEach = true;
act('gallery.menu', { tile: 0 });
act('gallery.menu', { tile: 1 });
await waitFor('both asked', () => menuOwnHolds.length === 2);
holdEach = false;
menuOwnHolds[1]();
await waitFor('the second image\'s menu', () => menuEl());
menuOwnHolds[0]();
await new Promise((resolve) => setTimeout(resolve, 40));
check('two pressed, the first answering late: only the second\'s menu',
      [document.querySelectorAll('.gen-menu').length, items()[0]?.[0]], [1, 'Show checkpoint Base 2 in Model Manager']);
document.body.dispatchEvent(Object.assign(new window.Event('keydown', { bubbles: true }), { key: 'Escape' }));

// A failed request: the menu says so, rather than nothing happening.
menuFails = true;
act('gallery.menu', { tile: 0 });
await waitFor('the failed menu', () => menuEl());
check('the request failed: one greyed item, saying what failed',
      [items(), titles()], [[['Could not read its resources', true]], ['Gallery menu error: no database']]);
menuFails = false;
document.body.dispatchEvent(Object.assign(new window.Event('keydown', { bubbles: true }), { key: 'Escape' }));

// ------------------------------------------------- into img2img's modes (#299)
// An image tile's ⋯ sends its original into one of img2img's modes: the
// loader asked with the mode and the original's address, under the progress
// popup while it fetches - any image, one naming no checkpoint too.
document.body.insertAdjacentHTML('beforeend', `
    <div id="tabs"><button id="tab_txt2img-button"></button><button id="tab_img2img-button"></button>
        <button id="img2img_img2img_sketch_tab-button"></button><button id="img2img_inpaint_tab-button"></button></div>
    <div id="txt2img_prompt"><textarea></textarea></div><div id="img2img_prompt"><textarea></textarea></div>`);
const loads = [];
let loadAnswer = () => ({ pasted: true });
let canvasAnswer = () => ({ source: true });
let progressSeen = false;
sendLoaders(document, { onAsk: (tab, request) => {
    loads.push({ tab, ...request });
    progressSeen = progressSeen || !!document.querySelector('.mm-progress');
}, answer: (tab, request) => loadAnswer(tab, request), canvasAnswer: (mode, request) => canvasAnswer(mode, request),
    delay: 60 });
const { originalMediaUrl } = await sharedModule('media.mjs');
// The settings button's requests, and the canvas buttons' - img2img's canvases set apart.
const settingsLoads = (from) => loads.slice(from).filter((r) => r.canvas === undefined);
const canvasLoads = (from) => loads.slice(from).filter((r) => r.canvas !== undefined);
const sendItem = (label) => buttons().slice(TOP, TOP + SENDS).find((b) => b.textContent.trim() === label);
act('gallery.menu', { tile: 0 });
await waitFor('the menu, for its sends', () => menuEl());
check('an image\'s menu has, after Show All and Resources, the five sends into img2img, in Forge\'s order, then its Show items',
      [buttons().slice(TOP, TOP + SENDS).map((b) => [b.textContent.trim(), b.disabled]), items().length > 0],
      [[['Send to img2img', false], ['Send to Sketch', false], ['Send to Inpaint', false],
        ['Send to Inpaint sketch', false], ['Send to Inpaint upload', false]], true]);
let loaded = loads.length;
sendItem('Send to Sketch').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the send into Sketch', () => canvasLoads(loaded).length);
check('Send to Sketch: img2img\'s settings button asked with the image as its source, the mode and the image\'s size',
      settingsLoads(loaded).map(({ tab, source, into }) => [tab, source?.kind, source?.image, into?.mode, into?.width, into?.height]),
      [['img2img', 'civitai', image(1).id, 1, 1024, 1536]]);
check('then Sketch\'s canvas button, with the original\'s address',
      canvasLoads(loaded).map(({ canvas, picture }) => [canvas, picture]), [[1, { url: originalMediaUrl(image(1).url) }]]);
await waitFor('the send to end', () => !document.querySelector('.mm-progress'));
check('under the progress popup while it fetched, closed once the send ended', progressSeen, true);

// No Show items to ask for: the menu opens at once, asking nothing.
const asksBefore299 = menuAsks.length;
act('gallery.menu', { tile: 2 });
await waitFor('the menu of an image with no Show items', () => menuEl());
check('an image the server says has no Show items: Show All, Resources and its five sends at once, nothing asked',
      [buttons().length, menuAsks.length - asksBefore299], [TOP + SENDS, 0]);
loaded = loads.length;
sendItem('Send to Inpaint').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the send of an image naming no checkpoint', () => canvasLoads(loaded).length);
check('an image naming no checkpoint - Send cannot send it - goes into Inpaint all the same',
      [sendOf(2)?.disabled, settingsLoads(loaded).map(({ tab, into }) => [tab, into?.mode]),
       canvasLoads(loaded).map((r) => r.canvas)], [true, [['img2img', 2]], [2]]);
await waitFor('that send to end', () => !document.querySelector('.mm-progress'));

// A fetch that fails is said: the canvas button's answer.
canvasAnswer = () => ({ error: 'Could not fetch the image from Civitai: 404 Not Found' });
document.querySelectorAll('.mm-notice').forEach((n) => n.remove());
act('gallery.menu', { tile: 2 });
await waitFor('the menu, for a failing send', () => menuEl());
sendItem('Send to img2img').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the notice', () => document.querySelector('.mm-notice'));
check('a fetch that fails: said, the settings in but the picture not, and the popup closed',
      [/picture could not be put in: Could not fetch the image from Civitai: 404 Not Found/.test(document.querySelector('.mm-notice')?.textContent || ''),
       (await waitFor('the popup gone', () => !document.querySelector('.mm-progress')), !document.querySelector('.mm-progress'))],
      [true, true]);
canvasAnswer = () => ({ source: true });

// Send's own button asks nothing of the sort.
loaded = loads.length;
act('gallery.send', { tile: 0 });
await waitFor('Send', () => loads.length > loaded);
await new Promise((resolve) => setTimeout(resolve, 100));
check('Send\'s own button: into txt2img, no mode or picture, no canvas button',
      loads.slice(loaded).map(({ tab, into, canvas }) => [tab, into, canvas]), [['txt2img', undefined, undefined]]);

// A video gets ⋯ too (#362): Show All and Resources, and no sends into
// img2img, which take a picture.
withVideo = true;
act('gallery.refresh');
await waitFor('the grid with a video', () => tileEls().some((el) => el.querySelector('video')));
const videoTile = tileEls().findIndex((el) => el.querySelector('video'));
check('a video\'s tile has ⋯', [videoTile >= 0, !!menuButton(videoTile)], [true, true]);
act('gallery.menu', { tile: videoTile });
await waitFor('the video\'s menu', () => menuEl());
check('with Show All and Resources, and no sends into img2img', buttons().map((b) => b.textContent.trim()),
      ['Show All', 'Resources']);
document.body.dispatchEvent(Object.assign(new window.Event('keydown', { bubbles: true }), { key: 'Escape' }));
withVideo = false;

// Show All opens the image's metadata window; Resources, labelled as the
// viewer's, its resources but the gallery's own model - greyed, saying so,
// where that is all it names (#362).
withResources = true;
act('gallery.refresh');
const tileOf = (id) => tileEls().findIndex((el) => el.innerHTML.includes(`/${id}.jpeg`));
await waitFor('the grid with resources', () => tileOf(7) >= 0 && tileOf(8) >= 0);
act('gallery.menu', { tile: tileOf(7) });
await waitFor('the menu of an image naming resources', () => menuEl());
check('an image naming another model: Resources ready, labelled as the viewer labels it',
      [buttons()[1]?.textContent.trim(), buttons()[1]?.disabled], ['Resources (1)', false]);
buttons()[1]?.dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the Resources dialog', () => document.querySelector('.mm-resources-modal'));
check('pressed: the Resources dialog on that image, the gallery\'s own model left out, the menu closed',
      [document.querySelector('.mm-resources-modal')?.textContent.includes('Base'),
       document.querySelector('.mm-resources-modal')?.textContent.includes('A LoRA'), menuEl()], [true, false, null]);
document.querySelectorAll('#mm_meta_modal').forEach((m) => { m.close?.(); m.remove(); });
act('gallery.menu', { tile: tileOf(8) });
await waitFor('the menu of an image naming only this model', () => menuEl());
check('an image naming only the gallery\'s own model: Resources greyed, saying so',
      [buttons()[1]?.textContent.trim(), buttons()[1]?.disabled, buttons()[1]?.getAttribute('title')],
      ['Resources', true, 'This image names no resource but this model']);
buttons()[0]?.dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the metadata window', () => document.querySelector('#mm_meta_modal'));
check('Show All: that image\'s metadata window, the menu closed',
      [document.querySelector('#mm_meta_modal h3')?.textContent, document.querySelector('#mm_meta_modal')?.textContent.includes('a cat 8'), menuEl()],
      ['Image Metadata', true, null]);
document.querySelectorAll('#mm_meta_modal').forEach((m) => { m.close?.(); m.remove(); });
withResources = false;

// The tab switched off while it asks: its answer opens nothing.
menuHeld = new Promise((resolve) => { release = resolve; });
act('gallery.menu', { tile: 0 });
const { stopTab } = await sharedModule('loading.mjs');
stopTab('gallery');
release();
menuHeld = null;
await new Promise((resolve) => setTimeout(resolve, 40));
check('the tab switched off while it asks: no menu', menuEl(), null);
} catch (error) {
    check('the ⋯ menu: its button, what it asks, what it opens, what closes it', String(error), null);
}

const source = readFileSync(`${ROOT}/javascript/tabs/gallery.mjs`, 'utf8');
check('the tab loads no module of your generations\' - what both tabs use is shared/grouping.mjs',
      [/['"]generations\.mjs['"]/.test(source), /tabs\/generations/.test(source), /['"]grouping\.mjs['"]/.test(source)],
      [false, false, true]);

done();

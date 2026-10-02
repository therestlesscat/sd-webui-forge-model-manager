// The Generations tab: every image you have generated, newest first.
//
// A tile per generation - a batch its first four images, how many it has, a
// border of its own colour - or, grouped, a tile per group of images. A click
// on a batch or a group opens it in a grid of its own, in place of this one,
// with a header and Back, which lands where the grid was left; a click on an
// image opens the viewer. Every tile sends its image's own infotext to the tab
// it was made in and is deleted - a batch whole, an image alone - with its
// files only when asked. Each tile says when it was made, in its corner. The
// grid loads on as it is scrolled; only the NSFW switch applies.
import { readFileSync } from 'node:fs';
import { ROOT, checker, mountTab } from './harness.mjs';
const { provide } = await import(`file:///${ROOT}/javascript/shared/calls.mjs`);

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
const { check, waitFor, done } = checker();

// ------------------------------------------------------------- the server
// As api/generations.browse_page() answers, which generations_test.py holds
// it to: filtered first, then cut into parts - two tiles a part here.
const PART = 2;
const img = (id, generation, position, level = 1) => ({
    id, generation_id: generation, position, seed: 1000 + id, width: 832, height: 1216,
    meta: { prompt: `prompt ${id}`, negativePrompt: 'blurry', steps: 20, sampler: 'Euler' },
    infotext: `prompt ${id}\nSteps: 20, Seed: ${1000 + id}`,
    url: `/model-manager/generations/images/${id}/file`, exists: true,
    mm_level: level, mm_level_from_prompt: level > 1, user_level: null, prompt_level: level,
});
// The files a menu names, as the server's file_ref() gives them (#42): by
// version and model; a path only for a file Civitai does not know.
const ANIMA_PATH = 'C:/models/Stable-diffusion/anima.safetensors';
const ANIMA = { path: ANIMA_PATH, name: 'anima', in_library: true, version_id: 701, model_id: 70, model_name: 'Anima' };
const ANIMA_UNKNOWN = { ...ANIMA, version_id: null, model_id: null, model_name: null };
const DETAIL = { path: 'C:/models/Lora/detail.safetensors', name: 'detail', in_library: true, version_id: 801,
                 model_id: 80, model_name: 'Detail' };
const GONE = { path: 'C:/models/Lora/gone.safetensors', name: 'gone', in_library: false, version_id: null,
               model_id: null, model_name: null };
// Newest first: G3 of five (one X), G2 of one, G1 of three. Image 31's own
// checkpoint is one Civitai does not know.
let generations = [
    { generation: { id: 3, mode: 'txt2img', created_at: '2026-09-28T20:00:00', image_count: 5,
                    checkpoint_path: ANIMA_PATH },
      checkpoint: ANIMA, loras: [DETAIL, GONE],
      images: [{ ...img(31, 3, 0), checkpoint: ANIMA_UNKNOWN }, img(32, 3, 1, 8), img(33, 3, 2), img(34, 3, 3),
               img(35, 3, 4)] },
    { generation: { id: 2, mode: 'img2img', created_at: '2026-09-28T19:00:00', image_count: 1 },
      images: [{ ...img(21, 2, 0), width: 1216, height: 832 }] },
    { generation: { id: 1, mode: 'txt2img', created_at: '2026-09-28T18:00:00', image_count: 3 },
      images: [img(11, 1, 0), img(12, 1, 1), img(13, 1, 2)] },
];
const shownOf = (g, hide) => g.images.filter((i) => !hide || i.mm_level <= 3);
const asked = [];
const posted = [];
const rated = [];

// Grouped by size only, here - the server's groupings are generations_test.py's.
const sizeOf = (i) => `${i.width}×${i.height}`;
function browse(params) {
    const hide = params.get('hide_nsfw_images') !== 'false';
    const page = Number(params.get('page') || 1);
    const grouped = params.get('group') === 'size';
    const inGroup = params.get('in_group');
    const opened = params.get('generation');
    let rows = generations.flatMap((g) => g.images.map((i) => ({ g, i })));
    if (grouped && inGroup) rows = rows.filter((r) => sizeOf(r.i) === inGroup);
    if (opened) rows = rows.filter((r) => r.g.generation.id === Number(opened));
    const shown = rows.filter((r) => !hide || r.i.mm_level <= 3);
    const kind = opened ? 'image' : grouped && !inGroup ? 'group' : 'generation';
    const units = new Map();
    for (const r of shown) {
        const unit = kind === 'image' ? r.i.id : kind === 'group' ? sizeOf(r.i) : r.g.generation.id;
        if (!units.has(unit)) units.set(unit, []);
        units.get(unit).push(r);
    }
    const tiles = [...units.entries()].map(([unit, rs]) => ({
        kind, generation: rs[0].g.generation, matching_count: rs.length,
        images: rs.slice(0, 4).map((r) => ({ ...r.i, checkpoint_path: r.g.generation.checkpoint_path,
                                             checkpoint: r.i.checkpoint || r.g.checkpoint || null,
                                             loras: r.g.loras || [] })),
        checkpoint_path: new Set(rs.map((r) => r.g.generation.checkpoint_path)).size === 1
            ? rs[0].g.generation.checkpoint_path : null,
        checkpoint: new Set(rs.map((r) => r.g.generation.checkpoint_path)).size === 1 ? rs[0].g.checkpoint || null : null,
        loras: rs[0].g.loras || [],
        level: new Set(rs.map((r) => r.i.mm_level)).size === 1 ? rs[0].i.mm_level : null,
        user_level: new Set(rs.map((r) => r.i.user_level)).size === 1 ? rs[0].i.user_level : null,
        ...(kind === 'group' ? { group: { id: unit, value: unit, latest: rs[0].g.generation.created_at,
                                          generations: new Set(rs.map((r) => r.g.generation.id)).size } } : {}),
    }));
    const total = rows.length;
    return {
        success: true,
        tiles: tiles.slice((page - 1) * PART, page * PART),
        more: tiles.length > page * PART,
        state: { total, filtered: shown.length, hidden_nsfw: total - shown.length,
                 nsfw_count: rows.filter((r) => r.i.mm_level > 3).length,
                 hide_nsfw_images: hide, stored_generations: generations.length },
        scope: { count: shown.length, first: shown.at(-1)?.g.generation.created_at,
                 last: shown[0]?.g.generation.created_at,
                 ...(grouped ? { grouping: 'Size', value: inGroup || undefined } : {}),
                 ...(opened ? { generation: rows[0]?.g.generation } : {}) },
    };
}

globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    const params = new URL(href, 'http://webui').searchParams;
    if (href.includes('/send-plan')) return reply({ success: false });
    if (href.includes('/model-manager/ui-options')) {
        return reply({ success: true, gallery_hide_nsfw: true, hide_promptless_images: true });
    }
    if (href.includes('/generations/browse')) {
        asked.push(params);
        return reply(browse(params));
    }
    const images = href.match(/\/generations\/(\d+)\/images/);
    if (images) {
        const g = generations.find((x) => x.generation.id === Number(images[1]));
        return reply({ success: true, images: g ? shownOf(g, params.get('hide_nsfw_images') !== 'false') : [] });
    }
    if (href.includes('/generations/rate')) {
        const form = new URLSearchParams(String(init.body));
        rated.push(Object.fromEntries(form));
        const hide = form.get('hide_nsfw_images') !== 'false';
        const level = form.get('level') ? Number(form.get('level')) : null;
        const apply = (i) => { i.user_level = level; i.mm_level = level ?? i.prompt_level; };
        if (form.get('image_id')) {
            const image = generations.flatMap((g) => g.images).find((i) => i.id === Number(form.get('image_id')));
            apply(image);
            return reply({ success: true, rated: 1, image: { ...image }, visible: !hide || image.mm_level <= 3 });
        }
        const g = generations.find((x) => x.generation.id === Number(form.get('generation')));
        const shown = shownOf(g, hide);
        shown.forEach(apply);
        return reply({ success: true, rated: shown.length });
    }
    const deleteImage = href.match(/\/generations\/images\/(\d+)\/delete/);
    const deleteGeneration = href.match(/\/generations\/(\d+)\/delete/);
    if (deleteImage || deleteGeneration) {
        posted.push([href.replace(/^.*\/model-manager/, ''), String(init.body)]);
        if (deleteImage) {
            for (const g of generations) g.images = g.images.filter((i) => i.id !== Number(deleteImage[1]));
        } else {
            generations = generations.filter((g) => g.generation.id !== Number(deleteGeneration[1]));
        }
        generations = generations.filter((g) => g.images.length);
        return reply({ success: true, deleted_files: 0, failed: [] });
    }
    return reply({ success: true });
};

// Forge's generation tabs, which Send pastes into (shared/send.mjs): what
// each paste carried, and where.
document.body.insertAdjacentHTML('afterbegin', `
    <div id="txt2img_prompt"><textarea></textarea></div>
    <div id="txt2img_tools"><button id="paste"></button></div>
    <div id="img2img_prompt"><textarea></textarea></div>
    <div id="img2img_tools"><button id="paste"></button></div>`);
const sent = [];
for (const mode of ['txt2img', 'img2img']) {
    document.querySelector(`#${mode}_tools #paste`).addEventListener('click', () => {
        sent.push({ infotext: document.querySelector(`#${mode}_prompt textarea`).value, mode });
    });
}
// The Model Manager's showing a file, which this tab calls.
const shownFiles = [];
provide('modelManager.showFile', (path) => { shownFiles.push(path); });
const shownVersions = [];
provide('modelManager.showVersion', (id) => { shownVersions.push(id); });
const civitaiAsked = [];

// This DOM has no layout: the end of the grid is put where the test says,
// far below the window until it is scrolled to.
let endTop = 100000;
const sentinel = document.getElementById('gen_sentinel');
sentinel.getBoundingClientRect = () => ({ top: endTop });
window.innerHeight = 900;

// All three tabs are one page, and the Model Manager keeps its sync and scan
// dialogs in its markup, hidden: the keys took them for open questions, and
// did nothing. One is here too.
document.body.insertAdjacentHTML('beforeend', '<div class="mm-dialog-backdrop" style="display: none;"></div>');

// Gradio draws the tab's markup after the page is ready, and the script runs
// before it: the first load found no grid to draw into, and the tab stayed
// empty until Refresh. So the markup comes late here too.
const app = document.getElementById('generations_app');
const holder = app.parentNode;
app.remove();

await import(`file:///${ROOT}/javascript/generations.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await new Promise((resolve) => setTimeout(resolve, 400));
holder.appendChild(app);

const grid = () => document.getElementById('gen_grid');
const tileEls = () => Array.from(grid().querySelectorAll('.gen-tile'));
// A tile by its generation, "g" for a folded one, "G" for a group.
const tileIds = () => tileEls().map((t) => `${t.getAttribute('data-generation')}`
    + `${t.classList.contains('gen-grouping') ? 'G' : t.classList.contains('gen-group') ? 'g' : ''}`);
const pathText = () => (document.getElementById('gen_path')?.textContent || '').replace(/\s+/g, ' ').trim();
const click = (el) => el.dispatchEvent(new window.Event('click', { bubbles: true }));
// The question showing - not the hidden dialog put in the page above.
const dialog = () => Array.from(document.querySelectorAll('.mm-dialog-backdrop'))
    .filter((d) => d.style.display !== 'none').pop() || null;
const lastAsked = () => asked.at(-1);

await waitFor('the first part', () => tileEls().length === 2);
check('the tab fills itself once its markup is there, with no Refresh', tileEls().length, 2);
check('the newest generations first, a part at a time: a batch folded, a single image plain',
      tileIds(), ['3g', '2']);
const group = tileEls()[0];
check('a folded batch shows its first four images the filter leaves, and how many there are',
      [group.querySelectorAll('.mm-generation-tile').length, group.querySelector('.gen-count')?.textContent], [4, '×4']);
check('the NSFW images hidden as the gallery setting says', lastAsked().get('hide_nsfw_images'), 'true');
const clickAt = (tile) => tile.querySelector('.gen-viewable, .gen-openable')?.getAttribute('onclick');
check('a click on an image opens the viewer on it; on a batch, the batch, in a grid of its own',
      [clickAt(tileEls()[1]), clickAt(group)], ['window.genView(1, 0)', 'window.genOpen(0)']);
check('every tile offers Send - named for the tab it was made in - and Delete, in one row',
      [Array.from(tileEls()[1].querySelectorAll('.gen-actions button')).map((b) => b.textContent.trim()),
       tileEls()[1].querySelector('.gen-actions button')?.getAttribute('title')],
      [['img2img', 'Delete'], 'Send to img2img']);
check('a wide image gets a horizontal tile, a tall one or a batch of them a vertical one',
      tileEls().map((t) => t.classList.contains('gen-wide')), [false, true]);
// A wide tile takes the columns nearest its image's width at the tiles'
// height - cropped least - from two up to four, and no more than there are.
// Columns of 200 and a gap of 12, tiles 300 high, six columns in the window:
const span = (ratio, columns = 6) => window.genSpanFor(ratio, 200, 12, 300, columns);
check('a wide tile takes the columns nearest its image\'s width: 1216x832 two, 16:9 three, 3:1 four',
      [span(1216 / 832), span(16 / 9), span(21 / 9), span(3), span(6)], [2, 3, 3, 4, 4]);
check('never more than the window has, and a tall or square image one',
      [span(3, 3), span(3, 1), span(1), span(2 / 3)], [3, 1, 1, 1]);
check('each tile carries its image\'s shape for that', tileEls()[1].getAttribute('data-aspect'), '1.462');

// "Preserve order": every tile one column, the same size, strictly in order.
// This DOM has no layout: a grid 1300 wide, columns of 200 and a gap of 12.
const sizes = { '--gen-column-width': '200px', '--gen-gap': '12px', '--gen-image-height': '300px' };
window.getComputedStyle = () => ({ getPropertyValue: (name) => sizes[name] || '' });
grid().getBoundingClientRect = () => ({ width: 1300, top: 0 });
const wideSpan = () => tileEls()[1].style.gridColumn;
window.genSetPreserveOrder(false);
check('without it, the wide tile takes the columns nearest its image', wideSpan(), 'span 2');
window.genSetPreserveOrder(true);
check('with it, every tile is one column, wide ones too', wideSpan(), 'span 1');
check('which is remembered in this browser, and turns the grid\'s filling in off',
      [window.localStorage.getItem('mm_generations_preserve_order'), grid().classList.contains('gen-ordered')],
      ['true', true]);
window.genSetPreserveOrder(false);
check('and back', [grid().classList.contains('gen-ordered'), wideSpan()], [false, 'span 2']);
const made = new Date('2026-09-28T20:00:00').toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' });
check('each tile says when it was made, and its size, in its image\'s corner',
      group.querySelector('.gen-media > .gen-date')?.textContent, `${made} · 832×1216`);
check('there is no "Show every image": a tile is a generation', document.getElementById('gen_every_image'), null);
check('the banner counts what is stored, and what the NSFW switch hides',
      document.querySelector('#gen_banner .mm-nsfw-warning span')?.textContent.includes('9 images stored'), true);

// ---------------------------------------------------------------- the ⋯ menu
// More that can be done with a tile, behind ⋯ at its image's top-right -
// drawn only when there is something in it. First: its model, in the Model
// Manager, when its images share one checkpoint.
const menuEl = () => document.querySelector('.gen-menu');
const key = (name) => document.dispatchEvent(Object.assign(new window.Event('keydown'), { key: name }));
check('a tile whose images share a checkpoint has ⋯; one with no checkpoint recorded has none',
      tileEls().map((t) => !!t.querySelector('.gen-menu-btn')), [true, false]);
check('its NSFW badge moved to the left, out of ⋯\'s way: the tab\'s stylesheet says so',
      /\.gen-media \.mm-nsfw-badge \{[^}]*left: 6px/.test(readFileSync(`${ROOT}/style.css`, 'utf8')), true);
window.genMenu(0, tileEls()[0].querySelector('.gen-menu-btn'));
const items = () => Array.from(menuEl()?.querySelectorAll('button') || []).map((b) => [b.textContent.trim(), b.disabled]);
check('⋯ opens a menu: the model in the Model Manager and the Civitai Browser, then each LoRA - '
      + 'one the library no longer has greyed',
      items(), [['Show model in Model Manager', false], ['Show model in Civitai Browser', false],
                ['Show LoRA detail in Model Manager', false], ['Show LoRA gone in Model Manager', true]]);
check('the greyed one says why', menuEl().querySelectorAll('button')[3].getAttribute('title'),
      'gone is not in the library: deleted, moved, or never scanned');
click(menuEl().querySelectorAll('button')[3]);
check('and does nothing', [menuEl() !== null, shownVersions, shownFiles], [true, [], []]);
key('Escape');
check('Esc closes it', menuEl(), null);
window.genMenu(0, tileEls()[0].querySelector('.gen-menu-btn'));
click(menuEl().querySelector('button'));
check('the model is asked for by its version, not its file', [shownVersions, shownFiles, menuEl()], [[701], [], null]);
// The Civitai Browser asked directly: not loaded, this tab says so, not the
// Model Manager's status line in a tab nobody is looking at.
window.genMenu(0, tileEls()[0].querySelector('.gen-menu-btn'));
click(menuEl().querySelectorAll('button')[1]);
check('without the Civitai Browser, this tab says so',
      document.getElementById('gen_status')?.textContent, 'The Civitai Browser tab has not started yet: open it once and try again.');
provide('civitaiBrowser.showModel', (query) => { civitaiAsked.push(query); });
window.genMenu(0, tileEls()[0].querySelector('.gen-menu-btn'));
click(menuEl().querySelectorAll('button')[1]);
check('and in the Civitai Browser by its model and version', civitaiAsked, ['model:70 version:701']);
window.genMenu(0, tileEls()[0].querySelector('.gen-menu-btn'));
click(menuEl().querySelectorAll('button')[2]);
check('a LoRA by its own version', shownVersions, [701, 801]);

// ---------------------------------------------------------------- the viewer
// An image over the page, ← and → through every image in the grid's order -
// a folded batch's too - and past the last loaded, the next part, into the
// grid as well. Send and Delete below it; its details beside it.
const viewer = () => document.querySelector('.mm-viewer');
const shownId = () => viewer()?.querySelector('.mm-viewer-image')?.getAttribute('src')?.match(/images\/(\d+)\//)?.[1];

const settle = () => new Promise((resolve) => setTimeout(resolve, 30));

await window.genView(0, 0);
check('the viewer steps through the images a batch\'s tile shows, saying where it is in the batch',
      [shownId(), viewer()?.querySelector('.mm-viewer-where')?.textContent], ['31', '1 of 4 in this generation']);
check('with its details beside it: its prompts and what was recorded, and a way to the file',
      [viewer()?.querySelector('.gen-info-prompt')?.textContent, viewer()?.textContent.includes('anima.safetensors'),
       viewer()?.textContent.includes('Seed'), !!viewer()?.querySelector('a[href$="/images/31/file"]')],
      ['prompt 31', true, true, true]);
check('Send, Delete and ⋯ below the image', Array.from(viewer().querySelectorAll('.mm-viewer-actions > button'))
      .map((b) => b.textContent.trim()), ['Send to txt2img', 'Delete', '⋯']);
click(viewer().querySelector('[data-gen-menu]'));
click(menuEl().querySelector('button'));
check('⋯ in the viewer shows the image\'s own checkpoint - one Civitai does not know, by its file - closing the viewer',
      [shownFiles.at(-1), viewer()], [ANIMA_PATH, null]);
await window.genView(0, 0);
check('nothing before the first', viewer().querySelector('.mm-viewer-prev').disabled, true);
key('ArrowRight'); await settle();
check('→ steps through them', shownId(), '33');
for (let i = 0; i < 3; i++) { key('ArrowRight'); await settle(); }
check('then on to the next generation', [shownId(), viewer()?.querySelector('.mm-viewer-where')?.textContent],
      ['21', '']);
check('with no ⋯ for an image with no checkpoint recorded', viewer().querySelector('[data-gen-menu]'), null);
key('ArrowLeft'); await settle();
check('← back to the batch\'s last image', shownId(), '35');
key('ArrowRight'); await settle();
key('ArrowRight'); await settle();
await waitFor('the next part', () => shownId() === '11');
check('past the last loaded, the next part is loaded - into the grid too', [shownId(), tileIds()],
      ['11', ['3g', '2', '1g']]);
key('ArrowRight'); await settle();
key('ArrowRight'); await settle();
check('and at the very end, nothing after', [shownId(), viewer().querySelector('.mm-viewer-next').disabled],
      ['13', true]);
const wheel = (deltaY, on = viewer().querySelector('.mm-viewer-image')) => {
    const event = Object.assign(new window.Event('wheel', { bubbles: true, cancelable: true }), { deltaY });
    on.dispatchEvent(event);
    return event.defaultPrevented;
};
check('the page under the viewer does not scroll', document.body.classList.contains('mm-modal-open'), true);
await new Promise((resolve) => setTimeout(resolve, 200));
check('the wheel is the viewer\'s, not the page\'s', wheel(-120), true);
await settle();
check('turned up, it goes back an image', shownId(), '12');
check('a small turn is not yet a step', [wheel(-20), shownId()], [true, '12']);
await new Promise((resolve) => setTimeout(resolve, 200));
wheel(120); await settle();
check('turned down, on an image', shownId(), '13');
click(viewer().querySelector('[data-panel]'));
check('the details fold away, and that is remembered',
      [viewer().classList.contains('mm-viewer-collapsed'),
       window.localStorage.getItem('mm_viewer_panel_closed')], [true, 'true']);
click(viewer().querySelector('.mm-viewer-image'));
click(viewer().querySelector('.mm-viewer-info'));
check('a click on the image or its details leaves it open', !!viewer(), true);
click(viewer().querySelector('.mm-viewer-frame'));
check('a click around the image closes it', viewer(), null);
await window.genView(2, 2);
key('Escape');
check('Esc closes it, and gives the page its scrolling back',
      [viewer(), document.body.classList.contains('mm-modal-open')], [null, false]);
await window.genView(1, 0);
check('and it opens again with its details folded, as left', viewer()?.classList.contains('mm-viewer-collapsed'), true);
click(viewer().querySelector('[data-panel]'));
const sentBefore = sent.length;
click(viewer().querySelector('[data-gen-send]'));
await waitFor('the paste', () => sent.length > sentBefore);
check('Send from the viewer sends that image, and closes it',
      [sent.at(-1)?.infotext.startsWith('prompt 21'), sent.at(-1)?.mode, viewer()], [true, 'img2img', null]);

// ---------------------------------------------------- a batch's own grid
// A click on a batch opens it in a grid of its own, in place of this one: its
// images, a tile each, under a header with Back. Back lands where the grid was
// left - the same tiles, the page scrolled back - loaded again only if
// something was deleted inside.
const scrolled = [];
window.scrollTo = (x, y) => scrolled.push(y);
const scrollTo = (y) => Object.defineProperty(window, 'scrollY', { value: y, configurable: true, writable: true });
scrollTo(640);
await window.genOpen(0);
await window.genLoadMore();              // two tiles a part, here, at every level
check('a click on a batch opens it in a grid of its own: a tile for each of its images',
      [lastAsked().get('generation'), tileIds()], ['3', ['3', '3', '3', '3']]);
check('under a header with Back, the way here, and what it is',
      [!!document.querySelector('#gen_path button'), pathText().includes('Generations ›'),
       pathText().includes('4 images'), pathText().includes('anima.safetensors')], [true, true, true, true]);
await window.genSend(2);
check('Send on one of its images sends that image\'s own infotext, to its generation\'s tab',
      [sent.at(-1).infotext, sent.at(-1).mode], ['prompt 34\nSteps: 20, Seed: 1034', 'txt2img']);

const deleting = window.genDelete(1);
await waitFor('the question', () => dialog());
check('Delete asks first, offering to delete the file too',
      dialog().querySelector('h3')?.textContent, 'Delete this image?');
dialog().querySelector('[data-files]').checked = true;
click(dialog().querySelector('[data-confirm]'));
await deleting;
check('an image is deleted alone, with its file when asked',
      [posted.at(-1), tileIds()], [['/generations/images/33/delete', 'delete_files=true'], ['3', '3', '3']]);
scrollTo(0);
await window.genBack();
check('Back lands where the grid was left, the page scrolled back to it', scrolled.at(-1), 640);
check('with what was deleted inside counted there', [tileIds(), tileEls()[0].querySelector('.gen-count')?.textContent],
      [['3g', '2', '1g'], '×3']);
check('and no header on the top grid', pathText(), '');

await window.genOpen(2);
await window.genLoadMore();
check('another batch opens the same way', tileIds(), ['1', '1', '1']);
const loadsBefore = asked.length;
key('Escape');
await waitFor('the way back', () => pathText() === '');
check('Esc goes back too, drawing the grid again as it was, without loading it',
      [tileIds(), asked.length], [['3g', '2', '1g'], loadsBefore]);

await window.genSend(0);
check('Send on a batch sends its first image\'s', sent.at(-1).infotext.startsWith('prompt 31'), true);
await window.genSend(1);
check('and a generation made in img2img goes back to img2img', sent.at(-1).mode, 'img2img');

// ---------------------------------------------------------------- deleting
const cancelled = window.genDelete(1);
await waitFor('the question', () => dialog());
click(dialog().querySelector('[data-close]'));
await cancelled;
check('cancelled, nothing is deleted', [posted.length, tileIds()], [1, ['3g', '2', '1g']]);

const whole = window.genDelete(2);
await waitFor('the question', () => dialog());
check('a batch is deleted whole, and says how many images',
      dialog().querySelector('h3')?.textContent, 'Delete this generation of 3 images?');
click(dialog().querySelector('[data-confirm]'));
await whole;
check('its records only, unless asked', posted.at(-1), ['/generations/1/delete', 'delete_files=false']);
check('and its tile goes', tileIds(), ['3g', '2']);

// Delete from the viewer: that image, and the viewer moves on to the next.
await window.genView(0, 1);
const viewDelete = (async () => { click(viewer().querySelector('[data-gen-delete]')); })();
await waitFor('the question', () => dialog());
click(dialog().querySelector('[data-confirm]'));
await viewDelete;
await waitFor('the next image', () => shownId() === '35');
check('Delete in the viewer deletes the image shown, and shows the one after it',
      [posted.at(-1)[0], shownId(), viewer()?.querySelector('.mm-viewer-where')?.textContent],
      ['/generations/images/34/delete', '35', '2 of 2 in this generation']);
key('Escape');

// ---------------------------------------------------------------- grouping
// Grouped, a tile per group of images, whatever generation they are of; a
// group opens onto its generations, a generation onto its images.
await window.genSetGroupBy('size');
check('"Group by" is remembered in this browser, and asked for',
      [window.localStorage.getItem('mm_generations_group_by'), lastAsked().get('group')], ['size', 'size']);
check('a tile per group, saying what it is', [tileIds(), tileEls().map((t) => t.querySelector('.gen-group-name')?.textContent)],
      [['3G', '2G'], ['832×1216', '1216×832']]);
check('a group has neither Send nor Delete - misleading, and too much at once - but says what it holds',
      [tileEls()[0].querySelectorAll('.gen-actions button').length,
       tileEls()[0].querySelector('.gen-group-facts')?.textContent.trim()], [0, '2 images · 1 generation']);
await window.genOpen(0);
check('a group opens onto its generations', [lastAsked().get('in_group'), tileIds()], ['832×1216', ['3g']]);
check('its header naming the group', pathText().includes('Size: 832×1216'), true);
await window.genOpen(0);
check('and a generation in it onto its images in the group, as deep as it goes',
      [lastAsked().get('in_group'), lastAsked().get('generation'), tileIds()], ['832×1216', '3', ['3', '3']]);
check('the way here all in its header', pathText().includes('Generations › Size: 832×1216 ›'), true);
await window.genBack();
await window.genBack();
check('Back, and Back, to the groups', tileIds(), ['3G', '2G']);
await window.genSetGroupBy('');
check('and grouped by nothing, a tile per generation again', tileIds(), ['3g', '2']);

// ---------------------------------------------------------------- the switches

await window.genShowNsfw(true);
check('the NSFW switch starts again from the first part, showing NSFW',
      [lastAsked().get('page'), lastAsked().get('hide_nsfw_images'), tileEls()[0].querySelector('.gen-count')?.textContent],
      ['1', 'false', '×3']);   // 33 and 34 deleted above, 32 hidden until now
const before = asked.length;
await window.genRefresh();
check('Refresh loads it again from the first part', [asked.length > before, lastAsked().get('page')], [true, '1']);

generations.push({ generation: { id: 0, mode: 'txt2img', created_at: '2026-09-28T17:00:00', image_count: 1 },
                   images: [img(1, 0, 0)] });
await window.genRefresh();
endTop = 1000;
window.dispatchEvent(new window.Event('scroll'));
await waitFor('the next part', () => tileEls().length === 3);
check('scrolling near the end brings the next part, added after', tileIds(), ['3g', '2', '0']);
check('the last', lastAsked().get('page'), '2');
endTop = 100000;

// ---------------------------------------------------------------- rating
// "Rate": a row of NSFW levels under every image - the level it has outlined,
// your rating filled; your rating again clears it. A rated image the switch
// now hides leaves at once; a batch rated, every image of it shown.
await window.genShowNsfw(false);
await window.genLoadMore();
const rows = () => tileEls().map((t) => !!t.querySelector('.mm-rate'));
const chips = (tile) => Array.from(tile.querySelectorAll('.mm-rate-chip'));
const marked = (tile, cls) => chips(tile).filter((c) => c.classList.contains(cls)).map((c) => c.textContent.trim());
check('no row of levels until "Rate" is ticked', rows().every((r) => !r), true);
window.genSetRating(true);
check('then one under every image', [rows().every(Boolean), chips(tileEls()[1]).map((c) => c.textContent.trim())],
      [true, ['PG', 'PG-13', 'R', 'X', 'XXX']]);
check('the level an image has outlined, none of them yours yet',
      [marked(tileEls()[1], 'mm-rate-current'), marked(tileEls()[1], 'mm-rate-mine')], [['PG'], []]);
await window.genRate(1, 2);
check('a click rates the image, and marks it as yours',
      [rated.at(-1).image_id, rated.at(-1).level, marked(tileEls()[1], 'mm-rate-mine')], ['21', '2', ['PG-13']]);
await window.genRate(1, 2);
check('your rating clicked again clears it', [rated.at(-1).level, marked(tileEls()[1], 'mm-rate-mine')], ['', []]);
await window.genRate(1, 8);
check('an image rated X, with NSFW hidden, leaves the grid at once', tileIds(), ['3g', '0']);
const loadsBeforeBatch = asked.length;
await window.genRate(0, 2);
check('a batch rated: every image of it the tab shows, and the grid loaded again in place',
      [rated.at(-1).generation, rated.at(-1).level, asked.length > loadsBeforeBatch,
       marked(tileEls()[0], 'mm-rate-mine')], ['3', '2', true, ['PG-13']]);
await window.genSetGroupBy('size');
check('a group has no row: rated whole, its images are easily misrated', rows(), [false]);
await window.genSetGroupBy('');
window.genSetRating(false);
check('unticked, the rows go', rows().every((r) => !r), true);

await window.genView(1, 0);
check('the viewer always shows the row of levels', chips(viewer()).map((c) => c.textContent.trim()),
      ['PG', 'PG-13', 'R', 'X', 'XXX']);
await window.genRateInViewer(4);
await waitFor('the viewer to move on', () => !viewer() || shownId() !== '1');
check('an image rated R there, with NSFW hidden, leaves, and the viewer goes on or closes',
      [rated.at(-1).image_id, tileIds()], ['1', ['3g']]);
key('Escape');

// The head - Group by and the switches, Back, the banner - is held at the top
// while the grid scrolls, as the other tabs' banners are: one block, under
// the rule they share. The banner alone could not stick: its own box is no
// taller than it.
const head = document.querySelector('.gen-sticky-head');
const css = readFileSync(`${ROOT}/style.css`, 'utf8');
check('the switches, Back and the banner are one block, the grid outside it',
      [!!head?.querySelector('#gen_group_by'), !!head?.querySelector('#gen_path'), !!head?.querySelector('#gen_banner'),
       head?.contains(document.getElementById('gen_grid'))], [true, true, true, false]);
check('held at the top by the rule the other tabs\' banners use',
      /\.filter-banner-sticky,\s*\.gen-sticky-head\s*\{[^}]*position:\s*sticky/.test(css), true);

done();

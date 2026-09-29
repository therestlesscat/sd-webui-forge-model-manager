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
import { ROOT, checker, mountTab } from './harness.mjs';

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
    mm_level: level, mm_level_from_prompt: level > 1,
});
// Newest first: G3 of five (one X), G2 of one, G1 of three.
let generations = [
    { generation: { id: 3, mode: 'txt2img', created_at: '2026-09-28T20:00:00', image_count: 5,
                    checkpoint_path: 'C:/models/Stable-diffusion/anima.safetensors' },
      images: [img(31, 3, 0), img(32, 3, 1, 8), img(33, 3, 2), img(34, 3, 3), img(35, 3, 4)] },
    { generation: { id: 2, mode: 'img2img', created_at: '2026-09-28T19:00:00', image_count: 1 },
      images: [{ ...img(21, 2, 0), width: 1216, height: 832 }] },
    { generation: { id: 1, mode: 'txt2img', created_at: '2026-09-28T18:00:00', image_count: 3 },
      images: [img(11, 1, 0), img(12, 1, 1), img(13, 1, 2)] },
];
const shownOf = (g, hide) => g.images.filter((i) => !hide || i.mm_level <= 3);
const asked = [];
const posted = [];

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
        kind, generation: rs[0].g.generation, images: rs.slice(0, 4).map((r) => r.i), matching_count: rs.length,
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
    if (href.includes('/generations/group/delete')) {
        const form = new URLSearchParams(String(init.body));
        posted.push(['/generations/group/delete', String(init.body)]);
        const hide = form.get('hide_nsfw_images') !== 'false';
        for (const g of generations) {
            g.images = g.images.filter((i) => sizeOf(i) !== form.get('in_group') || (hide && i.mm_level > 3));
        }
        generations = generations.filter((g) => g.images.length);
        return reply({ success: true, deleted: 1, deleted_files: 0, failed: [] });
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

// The Model Manager's paste, which this tab calls.
const sent = [];
window.mmSendInfotext = (what) => { sent.push(what); return true; };

// This DOM has no layout: the end of the grid is put where the test says,
// far below the window until it is scrolled to.
let endTop = 100000;
const sentinel = document.getElementById('gen_sentinel');
sentinel.getBoundingClientRect = () => ({ top: endTop });
window.innerHeight = 900;

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
const dialog = () => document.querySelector('.mm-dialog-backdrop');
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

// ---------------------------------------------------------------- the viewer
// An image over the page, ← and → through every image in the grid's order -
// a folded batch's too - and past the last loaded, the next part, into the
// grid as well. Send and Delete below it; its details beside it.
const viewer = () => document.querySelector('.gen-viewer');
const shownId = () => viewer()?.querySelector('.gen-viewer-image')?.getAttribute('src')?.match(/images\/(\d+)\//)?.[1];
const key = (name) => document.dispatchEvent(Object.assign(new window.Event('keydown'), { key: name }));
const settle = () => new Promise((resolve) => setTimeout(resolve, 30));

await window.genView(0, 0);
check('the viewer steps through the images a batch\'s tile shows, saying where it is in the batch',
      [shownId(), viewer()?.querySelector('.gen-viewer-where')?.textContent], ['31', '1 of 4 in this generation']);
check('with its details beside it: its prompts and what was recorded, and a way to the file',
      [viewer()?.querySelector('.gen-info-prompt')?.textContent, viewer()?.textContent.includes('anima.safetensors'),
       viewer()?.textContent.includes('Seed'), !!viewer()?.querySelector('a[href$="/images/31/file"]')],
      ['prompt 31', true, true, true]);
check('Send and Delete below the image', Array.from(viewer().querySelectorAll('.gen-viewer-actions button'))
      .map((b) => b.textContent.trim()), ['Send to txt2img', 'Delete']);
check('nothing before the first', viewer().querySelector('.gen-viewer-prev').disabled, true);
key('ArrowRight'); await settle();
check('→ steps through them', shownId(), '33');
for (let i = 0; i < 3; i++) { key('ArrowRight'); await settle(); }
check('then on to the next generation', [shownId(), viewer()?.querySelector('.gen-viewer-where')?.textContent],
      ['21', '']);
key('ArrowLeft'); await settle();
check('← back to the batch\'s last image', shownId(), '35');
key('ArrowRight'); await settle();
key('ArrowRight'); await settle();
await waitFor('the next part', () => shownId() === '11');
check('past the last loaded, the next part is loaded - into the grid too', [shownId(), tileIds()],
      ['11', ['3g', '2', '1g']]);
key('ArrowRight'); await settle();
key('ArrowRight'); await settle();
check('and at the very end, nothing after', [shownId(), viewer().querySelector('.gen-viewer-next').disabled],
      ['13', true]);
const wheel = (deltaY, on = viewer().querySelector('.gen-viewer-image')) => {
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
      [viewer().classList.contains('gen-viewer-collapsed'),
       window.localStorage.getItem('mm_generations_viewer_panel_closed')], [true, 'true']);
click(viewer().querySelector('.gen-viewer-image'));
click(viewer().querySelector('.gen-viewer-info'));
check('a click on the image or its details leaves it open', !!viewer(), true);
click(viewer().querySelector('.gen-viewer-frame'));
check('a click around the image closes it', viewer(), null);
await window.genView(2, 2);
key('Escape');
check('Esc closes it, and gives the page its scrolling back',
      [viewer(), document.body.classList.contains('mm-modal-open')], [null, false]);
await window.genView(1, 0);
check('and it opens again with its details folded, as left', viewer()?.classList.contains('gen-viewer-collapsed'), true);
click(viewer().querySelector('[data-panel]'));
click(viewer().querySelector('[data-send]'));
await settle();
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
window.genSend(2);
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

window.genSend(0);
check('Send on a batch sends its first image\'s', sent.at(-1).infotext.startsWith('prompt 31'), true);
window.genSend(1);
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
const viewDelete = (async () => { click(viewer().querySelector('[data-delete]')); })();
await waitFor('the question', () => dialog());
click(dialog().querySelector('[data-confirm]'));
await viewDelete;
await waitFor('the next image', () => shownId() === '35');
check('Delete in the viewer deletes the image shown, and shows the one after it',
      [posted.at(-1)[0], shownId(), viewer()?.querySelector('.gen-viewer-where')?.textContent],
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
check('a group has Send and Delete too',
      Array.from(tileEls()[0].querySelectorAll('.gen-actions button')).map((b) => b.textContent.trim()),
      ['txt2img', 'Delete']);
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
const groupDelete = window.genDelete(1);
await waitFor('the question', () => dialog());
check('deleting a group asks first, saying how many images, from how many generations',
      dialog().querySelector('h3')?.textContent, 'Delete these 1 image, from 1 generation?');
click(dialog().querySelector('[data-confirm]'));
await groupDelete;
check('and deletes the images of it the grid shows, the grouping and the filter sent with it',
      [posted.at(-1)[0], Object.fromEntries(new URLSearchParams(posted.at(-1)[1]))],
      ['/generations/group/delete', { group: 'size', in_group: '1216×832', hide_nsfw_images: 'true',
                                      delete_files: 'false' }]);
check('its tile gone', tileIds(), ['3G']);
await window.genSetGroupBy('');
check('and grouped by nothing, a tile per generation again', tileIds(), ['3g']);

// ---------------------------------------------------------------- the switches

await window.genShowNsfw(true);
check('the NSFW switch starts again from the first part, showing NSFW',
      [lastAsked().get('page'), lastAsked().get('hide_nsfw_images'), tileEls()[0].querySelector('.gen-count')?.textContent],
      ['1', 'false', '×3']);   // 33 and 34 deleted above, 32 hidden until now
generations.push({ generation: { id: 2, mode: 'img2img', created_at: '2026-09-28T19:00:00', image_count: 1 },
                   images: [{ ...img(21, 2, 0), width: 1216, height: 832 }] });
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

done();

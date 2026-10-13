// "Expand generations" in the Generations tab (#252): a box beside Preserve
// order, kept in this browser. Ticked, every request asks for a tile per
// image; the level you are on loads again, and those above it on Back; inside
// a batch nothing is asked. An image tile at the top works as one inside a
// batch: a click opens the viewer; rating, Delete and Select take that image.
// The server's side: generations_expand_test.py.
import { act, checker, mountTab, startTab, tick } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
const { check, waitFor, done } = checker();

const img = (id, generation) => ({
    id, generation_id: generation, width: 832, height: 1216, meta: { prompt: `prompt ${id}` },
    infotext: `prompt ${id}`, url: `/model-manager/generations/images/${id}/file`, exists: true,
    mm_level: 1, user_level: null, prompt_level: 1,
});
const gen = (id, count) => ({ id, mode: 'txt2img', image_count: count });
// Two batches: G2 of two images, G1 of one.
const BATCHES = [
    { kind: 'generation', generation: gen(2, 2), matching_count: 2, images: [img(21, 2), img(22, 2)] },
    { kind: 'generation', generation: gen(1, 1), matching_count: 1, images: [img(11, 1)] },
];
const imageTile = (i) => ({ kind: 'image', generation: gen(i.generation_id, 1), matching_count: 1, images: [i] });
const IMAGES = [img(21, 2), img(22, 2), img(11, 1)].map(imageTile);

const asked = [];
const rated = [];
const deleted = [];
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/generations/browse')) {
        const params = new URL(href, 'http://webui').searchParams;
        asked.push(Object.fromEntries(params));
        const batch = params.get('generation');
        const expanded = params.get('expand') === 'true';
        const tiles = batch ? IMAGES.filter((t) => String(t.generation.id) === batch)
            : expanded ? IMAGES : BATCHES;
        return reply({ success: true, tiles, more: false,
                       state: { total: 3, filtered: 3, hidden_nsfw: 0, nsfw_count: 0, hide_nsfw_images: false,
                                stored_generations: 2 },
                       scope: { count: batch ? tiles.length : 3 } });
    }
    if (href.includes('/generations/rate')) {
        rated.push(Object.fromEntries(new URLSearchParams(String(init.body))));
        return reply({ success: true, image: { user_level: 4 }, visible: true });
    }
    if (href.includes('/delete')) {
        deleted.push(href);
        return reply({ success: true, deleted_files: 0 });
    }
    if (href.includes('/model-manager/ui-options')) return reply({ success: true, generations_hide_nsfw: false });
    return reply({ success: true });
};

// Kept from an earlier visit: the box starts ticked, and the first request expands.
localStorage.setItem('mm_generations_expand', 'true');
await startTab('generations');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => document.getElementById(id);
const tileEls = () => Array.from(document.querySelectorAll('#gen_grid .gen-tile'));
const last = () => asked[asked.length - 1];
// The box pressed where it is drawn: without it, checks fail rather than the suite.
const toggle = (on) => { if ($('gen_expand')) tick('generations.expand', on); };
const press = (action, tile) => {
    if (document.querySelector(`[data-action="${action}"][data-tile="${tile}"]`)) act(action, { tile });
};
const media = (i) => tileEls()[i]?.querySelector('[data-action="generations.view"], [data-action="generations.open"]');

await waitFor('the first part', () => tileEls().length > 0);
check('kept in this browser: the box starts ticked, and the first part asks for images',
      [$('gen_expand')?.checked, last()?.expand, tileEls().length], [true, 'true', 3]);

// --------------------------------------------------------------- unticked
const before = asked.length;
toggle(false);
await waitFor('the level again', () => asked.length > before && tileEls().length === 2);
check('unticked: kept off, and the level asks again for batches, from its first part',
      [localStorage.getItem('mm_generations_expand'), last()?.expand, last()?.page, tileEls().length],
      ['false', 'false', '1', 2]);

// ---------------------------------------------------------------- ticked
toggle(true);
await waitFor('images again', () => tileEls().length === 3);
check('ticked again: kept on, and asked for images', [localStorage.getItem('mm_generations_expand'), last()?.expand],
      ['true', 'true']);
check('at the top, an image tile opens the viewer, not a level',
      media(0)?.getAttribute('data-action'), 'generations.view');
press('generations.view', 0);
await waitFor('the viewer', () => document.querySelector('.mm-viewer'));
check('the viewer shows that image, and no level was opened',
      [document.querySelector('.mm-viewer-image')?.getAttribute('src')?.includes('/images/21/'), last()?.generation],
      [true, undefined]);
document.querySelector('.mm-viewer [data-close]')?.dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the viewer closed', () => !document.querySelector('.mm-viewer'));

// What an image tile's buttons act on: that one image.
check('each image tile has its own Send', tileEls().map((t) => !!t.querySelector('[data-action="generations.send"]')),
      [true, true, true]);
tick('generations.rating', true);
act('generations.rate', { tile: 1, level: 4 });
await waitFor('the rating', () => rated.length === 1);
check('rating an image tile rates that image', [rated[0]?.image_id, rated[0]?.generation], ['22', undefined]);
tick('generations.rating', false);
press('generations.delete', 2);
await waitFor('the question', () => document.querySelector('.mm-delete-dialog'));
check('Delete asks about one image', document.querySelector('.mm-delete-dialog')?.textContent.includes('Delete this image?'),
      true);
const dialogButton = (text) => Array.from(document.querySelectorAll('.mm-delete-dialog button'))
    .find((b) => b.textContent.trim() === text);
const askedBeforeDelete = asked.length;
dialogButton('Delete')?.dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the delete', () => deleted.length === 1 && asked.length > askedBeforeDelete);
check('it deletes that image, and the banner\'s count asks again with expand',
      [/images\/11\/delete/.test(deleted[0] || ''), last()?.expand, last()?.page], [true, 'true', '1']);
tick('generations.selecting', true);
const firstTick = document.querySelector('#gen_grid [data-gen-pick]');
if (firstTick) {
    firstTick.checked = true;
    firstTick.dispatchEvent(new window.Event('click', { bubbles: true }));
}
check('Select ticks an image tile as one image',
      document.querySelector('#gen_select_bar .mm-select-count')?.textContent.trim().startsWith('1 image'), true);
tick('generations.selecting', false);

// ------------------------------------------------------- inside a batch
toggle(false);
await waitFor('batches', () => tileEls().length === 2);
act('generations.open', { tile: 0 });
await waitFor('the batch', () => last()?.generation === '2' && tileEls().length === 2);
const insideBatch = asked.length;
toggle(true);
await new Promise((r) => setTimeout(r, 100));
check('inside a batch, ticking it asks nothing: a batch already shows its images',
      [asked.length === insideBatch, $('gen_expand')?.checked], [true, true]);
act('generations.back');
await waitFor('the top again', () => asked.length > insideBatch);
check('Back loads the level above again, now expanded', [last()?.generation, last()?.expand], [undefined, 'true']);

done();

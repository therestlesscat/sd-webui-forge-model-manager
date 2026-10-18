// The ⋯ menu kept inside the window (#298), through the Generations tab's ⋯.
//
// Measured once drawn: below its button, else above, else moved in from the
// bottom; growing left from the button's right edge, else right from its
// left, else moved in from the right; capped to the window less 8 px a side
// where it is bigger. Esc, a scroll of the page and a resize of the window
// close it, and so does its own ⋯ pressed again; a scroll inside it does not. Until #298 it was placed by its
// right edge alone: its left could run past the window, its bottom below it.
//
// linkedom has no layout: the window's size, the button's box and the menu's
// own size are stood in for, as a browser would measure them.
import { checker, mountTab, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
const { check, waitFor, done } = checker();

const FILE = (name, version) => ({ path: `C:/models/Lora/${name}.safetensors`, name, in_library: true,
                                   version_id: version, model_id: version * 10, model_name: name });
const tile = {
    kind: 'generation', matching_count: 1,
    generation: { id: 1, mode: 'txt2img', created_at: '2026-10-18T12:00:00', image_count: 1 },
    images: [{ id: 11, generation_id: 1, position: 0, width: 832, height: 1216, url: '/x/11/file', exists: true,
               meta: { prompt: 'a prompt' }, infotext: 'a prompt', mm_level: 1, prompt_level: 1, user_level: null }],
    checkpoint: { ...FILE('base', 7), path: 'C:/models/Stable-diffusion/base.safetensors' },
    loras: [FILE('a_lora_with_a_rather_long_name_of_sixty_characters_or_so', 8)],
};
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/model-manager/ui-options')) return reply({ success: true, gallery_hide_nsfw: true });
    if (href.includes('/generations/browse')) {
        return reply({ success: true, tiles: [tile], more: false,
                       state: { total: 1, filtered: 1, hidden_nsfw: 0, nsfw_count: 0, stored_generations: 1 },
                       scope: { count: 1 } });
    }
    return reply({ success: true });
};

// The menu's own size, as the browser would measure it: `natural`, until a
// width is set on it - narrowed, its items wrap and it grows taller.
let natural = { width: 300, height: 150 };
const proto = Object.getPrototypeOf(Object.getPrototypeOf(document.createElement('div')));
const rect = proto.getBoundingClientRect;
proto.getBoundingClientRect = function getBoundingClientRect() {
    if (!this.classList?.contains('gen-menu')) return rect ? rect.call(this) : { top: 0, left: 0, width: 0, height: 0 };
    const set = parseFloat(this.style.width);
    const width = set && set < natural.width ? set : natural.width;
    const height = Math.round(natural.height * natural.width / width);
    return { top: 0, left: 0, right: width, bottom: height, width, height };
};

await startTab('generations');
const button = () => document.querySelector('#gen_grid .gen-menu-btn');
await waitFor('the tile and its ⋯', () => button());
const menuEl = () => document.querySelector('.gen-menu');
const escape = () => document.body.dispatchEvent(Object.assign(new window.Event('keydown', { bubbles: true }),
                                                               { key: 'Escape' }));

/**
 * The menu opened from a button at `box` in a window `view` big: where it
 * landed, as the browser would draw it - its left from `left`, or, as the
 * code before #298 set it, from `right`.
 */
async function opened(box, view, size) {
    natural = size;
    window.innerWidth = view.width;
    window.innerHeight = view.height;
    if (menuEl()) escape();
    const b = button();
    b.getBoundingClientRect = () => ({ ...box, width: box.right - box.left, height: box.bottom - box.top });
    b.dispatchEvent(new window.Event('click', { bubbles: true }));
    await waitFor('the menu', () => menuEl());
    const el = menuEl();
    const measured = el.getBoundingClientRect();
    const left = el.style.left ? parseFloat(el.style.left)
        : view.width - parseFloat(el.style.right) - measured.width;
    const top = parseFloat(el.style.top);
    const height = el.style.maxHeight ? Math.min(parseFloat(el.style.maxHeight), measured.height) : measured.height;
    return { left, top, right: left + measured.width, bottom: top + height, width: measured.width,
             maxHeight: el.style.maxHeight || '', hidden: el.style.visibility === 'hidden' };
}
const VIEW = { width: 1000, height: 800 };
const at = (left, top) => ({ left, right: left + 28, top, bottom: top + 24 });

let place = await opened(at(500, 100), VIEW, { width: 300, height: 150 });
check('room below and to the left: under the button, 4 px down, its right edge on the button\'s - as before',
      [place.top, place.right, place.left], [128, 528, 228]);
check('and shown once placed', place.hidden, false);

place = await opened(at(10, 100), VIEW, { width: 320, height: 150 });
check('a tile in the first column, a menu wider than the room to its left: it grows right from the button\'s left',
      [place.left, place.top], [10, 128]);
check('inside the window', place.left >= 8 && place.right <= VIEW.width - 8, true);

place = await opened(at(500, 760), VIEW, { width: 300, height: 180 });
check('a tile in the window\'s bottom row: the menu opens above, its bottom 4 px over the button',
      [place.top, place.bottom], [576, 756]);

place = await opened(at(500, 120), { width: 1000, height: 300 }, { width: 300, height: 200 });
check('no room above or below: moved in, its bottom 8 px from the window\'s', [place.top, place.bottom], [92, 292]);

place = await opened(at(500, 100), VIEW, { width: 300, height: 1000 });
check('taller than the window: 8 px from its top, capped to the window less 16 px, with a scroll of its own',
      [place.top, place.maxHeight, place.bottom], [8, '784px', 792]);

place = await opened(at(150, 100), { width: 300, height: 800 }, { width: 500, height: 100 });
check('wider than the window: 8 px from its left, as wide as the window less 16 px',
      [place.left, place.width, place.right], [8, 284, 292]);

place = await opened({ left: 990, right: 1018, top: 100, bottom: 124 }, VIEW, { width: 300, height: 150 });
check('a button partly past the window\'s right edge - its tile cut there: the menu still 8 px inside',
      [place.left, place.right], [692, 992]);

// Its own ⋯ again closes it (R4): the click-away listener closed it, and the
// same click's action opened it again.
await opened(at(500, 100), VIEW, { width: 300, height: 150 });
await new Promise((resolve) => setTimeout(resolve, 20));
button().dispatchEvent(new window.Event('click', { bubbles: true }));
await new Promise((resolve) => setTimeout(resolve, 20));
check('its own ⋯ pressed again: the menu closed, and still closed once the click is done', menuEl(), null);

// Esc: the menu closes, and the key goes no further - not to the tab's own
// keys, nor the WebUI's, which interrupts a running generation on Esc.
await opened(at(500, 100), VIEW, { width: 300, height: 150 });
const heard = [];
const listener = (event) => heard.push(event.key);
document.addEventListener('keydown', listener);
escape();
document.removeEventListener('keydown', listener);
check('Esc closes it, and goes no further', [menuEl(), heard], [null, []]);

await opened(at(500, 100), VIEW, { width: 300, height: 150 });
menuEl().dispatchEvent(new window.Event('scroll'));
check('a scroll inside it leaves it open', !!menuEl(), true);
window.dispatchEvent(new window.Event('scroll'));
check('a scroll of the page closes it: it is fixed to the window, not to its tile', menuEl(), null);
await opened(at(500, 100), VIEW, { width: 300, height: 150 });
window.dispatchEvent(new window.Event('resize'));
check('a resize of the window closes it', menuEl(), null);

done();

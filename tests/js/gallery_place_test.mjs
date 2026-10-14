// Previous Position in the Civitai Images tab (#250). Send took the page to
// txt2img, and back in the tab it was at its top: the tab had no way back,
// where the Model Manager had a Previous Position button.
//
// Send, from a tile or the viewer, and Show model note where the page is
// before they switch. The button shows in the toolbar, before Refresh;
// pressed, the page goes back there; a right-click clears it.
import { checker, mountTab, press, startTab, tabEntries, tabMarkup } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_gallery.py');
const { check, waitFor, done } = checker();

const imageTile = (id) => ({
    kind: 'image',
    image: { id, url: `https://image.civitai.com/x/original=true/${id}.jpeg`, width: 1024, height: 1536, mm_level: 1,
             mm_level_from_prompt: false, meta: { prompt: `a cat ${id}`, Model: 'someCheckpoint' } },
    model: { id: 40, name: 'A LoRA', civitai_type: 'LORA', model_type: 'LORA', base_model: 'SDXL 1.0' },
    version: { id: 400, name: 'v1', file_path: 'C:/models/Lora/a.safetensors', file_type: 'LORA', base_model: 'SDXL 1.0' },
});
globalThis.onAfterUiUpdate = () => {};
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (href.includes('/model-manager/gallery/browse')) {
        return reply({ success: true, seed: 1, more: false, state: { total: 1, filtered: 1 }, scope: { count: 1 },
                       tiles: [imageTile(1)] });
    }
    // The Classic grid: closing the viewer brings its tile into view by scrollIntoView.
    if (href.includes('/model-manager/ui-options')) {
        return reply({ success: true, samplers: [], schedulers: [], gallery_grid: 'Classic' });
    }
    return reply({ success: true });
};

// The Model Manager, for Show model: its entry stood in for.
document.body.insertAdjacentHTML('beforeend', tabMarkup('model_manager/ui/tab_model_manager.py'));
await startTab('modelManager');
const shownVersions = [];
(await tabEntries('model_manager.mjs')).showVersion = async (...args) => { shownVersions.push(args); };
await startTab('gallery');
await waitFor('the grid', () => document.querySelectorAll('#gal_grid .gen-tile').length === 1);

const scrollY = (y) => Object.defineProperty(window, 'scrollY', { value: y, configurable: true });
const scrolls = [];
window.scrollTo = (...args) => { scrolls.push(typeof args[0] === 'object' ? args[0].top : args[1]); };
const button = () => document.getElementById('gal_scroll_restore_btn');
const showing = () => Boolean(button()) && button().style.display !== 'none';
// No button, no press: a check fails rather than the suite.
const pressBack = () => {
    scrolls.length = 0;
    scrollY(0);
    if (button()) press(button());
    return scrolls[0] ?? null;
};
const clear = () => button()?.dispatchEvent(new window.Event('contextmenu', { bubbles: true, cancelable: true }));
// What Send does after the place is noted is not this suite's.
const quietly = async (run) => { try { await run(); } catch (e) { /* the send's own business */ } };

check('before anything, no Previous Position', showing(), false);

// ------------------------------------------------------------ Send from a tile
scrollY(20000);
await quietly(() => press(document.querySelector('#gal_grid [data-action="gallery.send"][data-tile="0"]')));
check('a Send from a tile 20,000 px down shows Previous Position', showing(), true);
check('in the toolbar, before Refresh',
      [Boolean(button()?.closest('.gen-toolbar')), button()?.nextElementSibling?.id], [true, 'gal_refresh_btn']);
check('pressed, the page goes back to where it was', pressBack(), 20000);
clear();
check('a right-click clears it', showing(), false);

// ------------------------------------------------------------ Send from the viewer
// Noted once the viewer has closed, which brings the image it showed last
// into view: the button goes back to the image sent.
scrollY(5000);
await press(document.querySelector('#gal_grid [data-action="gallery.view"][data-tile="0"]'));
await waitFor('the viewer', () => document.querySelector('[data-gal-send]'));
const intoView = window.HTMLElement.prototype.scrollIntoView;
window.HTMLElement.prototype.scrollIntoView = function() { scrollY(6100); };
document.querySelector('[data-gal-send]').dispatchEvent(new window.Event('click', { bubbles: true }));
await new Promise((resolve) => setTimeout(resolve, 0));
window.HTMLElement.prototype.scrollIntoView = intoView;
check('a Send from the viewer shows Previous Position', showing(), true);
check('pressed, the page goes back to the image sent, where closing the viewer brought it', pressBack(), 6100);
clear();

// ------------------------------------------------------------ Show model
scrollY(7000);
await press(document.querySelector('#gal_grid [data-action="gallery.showModel"][data-tile="0"]'));
await waitFor('the Model Manager asked', () => shownVersions.length > 0);
check('Show model shows Previous Position', showing(), true);
check('pressed, the page goes back to where it was', pressBack(), 7000);

// ------------------------------------------------------------ the grid starting again clears it
// The place is a height in the grid it was noted in: in another grid it
// would land on other images.
await press(document.getElementById('gal_refresh_btn'));
await waitFor('the grid again', () => document.querySelectorAll('#gal_grid .gen-tile').length === 1);
check('Refresh starts the grid again, and clears Previous Position', showing(), false);

done();

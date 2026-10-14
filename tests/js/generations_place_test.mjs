// Previous Position in the Generations tab (#250). The whole WebUI is one
// page with one scroll: Send took the page to txt2img, and back in the tab
// it was at its top, hundreds of images above the one sent. The Model
// Manager had a Previous Position button for this; the tab had nothing.
//
// The tab's actions that leave it - Send, from a tile or the viewer, and
// the ⋯ menu's links - note where the page is, before they switch. The
// button shows in the toolbar, before Sync images; pressed, the page goes
// back there; a right-click clears it. A plain click on the tab bar notes
// nothing: the person scrolled to the top to reach it.
import { checker, mountTab, press, sendLoaders, startTab, tabEntries, tabMarkup, tabsAnswer } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
// The Model Manager, for the ⋯ menu's Show model in Model Manager.
document.body.insertAdjacentHTML('beforeend', tabMarkup('model_manager/ui/tab_model_manager.py'));
const { check, waitFor, done } = checker();

document.body.insertAdjacentHTML('afterbegin', `
    <div id="tabs">
        <button id="tab_txt2img-button">txt2img</button>
        <button id="tab_img2img-button">img2img</button>
        <button id="tab_generations_tab-button" class="selected" aria-selected="true">Generations</button>
        <button id="tab_model_manager_tab-button">Model Manager</button>
    </div>
    <div id="txt2img_prompt"><textarea></textarea></div>
    <div id="txt2img_tools"><button id="paste"></button></div>`);
const pastes = sendLoaders(document);

const INFOTEXT = 'a lighthouse at dusk\nSteps: 20, Sampler: Euler, Seed: 7';
const image = {
    id: 11, generation_id: 1, position: 0, seed: 7, width: 832, height: 1216,
    meta: { prompt: 'a lighthouse at dusk', steps: 20 }, infotext: INFOTEXT,
    url: '/model-manager/generations/images/11/file', exists: true,
    mm_level: 1, mm_level_from_prompt: false, user_level: null, prompt_level: 1, loras: [],
};
const generation = { id: 1, mode: 'txt2img', created_at: '2026-10-02T10:00:00', image_count: 1 };
const checkpoint = { name: 'a_checkpoint', path: 'C:/models/a.safetensors', version_id: 5, model_id: 9, in_library: true };
const tiles = [{ kind: 'generation', generation, matching_count: 1, images: [image], loras: [], level: 1,
                 user_level: null, checkpoint }];
globalThis.onAfterUiUpdate = () => {};
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (href.includes('/ui-options')) {
        // The Classic grid: closing the viewer brings its tile into view by scrollIntoView.
        return reply({ success: true, samplers: ['Euler'], schedulers: ['Automatic'], generations_enabled: true,
                       generations_grid: 'Classic',
                       tabs: tabsAnswer({ generations: true, model_manager: true }) });
    }
    if (href.includes('/generations/browse')) {
        return reply({ success: true, more: false, tiles,
                       state: { total: 1, filtered: 1, hidden_nsfw: 0, nsfw_count: 0, stored_generations: 1 },
                       scope: { count: 1 } });
    }
    if (href.includes('/send-plan')) return reply({ success: false });
    return reply({ success: true });
};

await startTab('generations');
await startTab('modelManager');
// What the Model Manager would do with the model is not this suite's.
const entries = await tabEntries('model_manager.mjs');
const shownInManager = [];
entries.showVersion = async (...args) => { shownInManager.push(args); };
entries.showFile = async (...args) => { shownInManager.push(args); };
await waitFor('the grid', () => document.querySelectorAll('#gen_grid .gen-tile').length === 1);

const scrollY = (y) => Object.defineProperty(window, 'scrollY', { value: y, configurable: true });
const scrolls = [];
window.scrollTo = (...args) => { scrolls.push(typeof args[0] === 'object' ? args[0].top : args[1]); };
const button = () => document.getElementById('gen_scroll_restore_btn');
const showing = () => Boolean(button()) && button().style.display !== 'none';
// No button, no press: a check fails rather than the suite.
const pressBack = () => {
    scrolls.length = 0;
    scrollY(0);
    if (button()) press(button());
    return scrolls[0] ?? null;
};
const clear = () => button()?.dispatchEvent(new window.Event('contextmenu', { bubbles: true, cancelable: true }));

check('before anything, no Previous Position', showing(), false);

// ------------------------------------------------------------ Send from a tile
scrollY(20000);
let before = pastes.length;
await press(document.querySelector('#gen_grid [data-action="generations.send"][data-tile="0"]'));
await waitFor('the paste', () => pastes.length > before);
check('a Send from a tile 20,000 px down shows Previous Position', showing(), true);
check('in the toolbar, before Sync images',
      [button()?.closest('.gen-toolbar') !== null, button()?.nextElementSibling?.id], [true, 'gen_sync_btn']);
check('pressed, the page goes back to where it was', pressBack(), 20000);

// ------------------------------------------------------------ a right-click clears it
clear();
check('a right-click clears it', showing(), false);

// ------------------------------------------------------------ the tab bar notes nothing
scrollY(3000);
document.getElementById('tab_txt2img-button').click();
document.getElementById('tab_generations_tab-button').click();
check('a plain click on the tab bar, away and back, notes nothing', showing(), false);

// ------------------------------------------------------------ Send from the viewer
// The place is noted once the viewer has closed: closing it brings the image
// it showed last into view, so the button goes back to the image sent - as
// the Model Manager's does - not to where the viewer opened.
scrollY(5000);
await press(document.querySelector('#gen_grid [data-action="generations.view"][data-tile="0"]'));
await waitFor('the viewer', () => document.querySelector('[data-gen-send]'));
const intoView = window.HTMLElement.prototype.scrollIntoView;
window.HTMLElement.prototype.scrollIntoView = function() { scrollY(6100); };
before = pastes.length;
document.querySelector('[data-gen-send]').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the paste from the viewer', () => pastes.length > before);
window.HTMLElement.prototype.scrollIntoView = intoView;
check('a Send from the viewer shows Previous Position', showing(), true);
check('pressed, the page goes back to the image sent, where closing the viewer brought it', pressBack(), 6100);
clear();

// ------------------------------------------------------------ the ⋯ menu's link
scrollY(7000);
await press(document.querySelector('#gen_grid [data-action="generations.menu"][data-tile="0"]'));
await waitFor('the menu', () => document.querySelector('.gen-menu'));
const item = [...document.querySelectorAll('.gen-menu [data-item]')]
    .find((b) => b.textContent === 'Show model in Model Manager');
check('the menu offers Show model in Model Manager', Boolean(item) && !item.disabled, true);
item?.dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the Model Manager asked', () => shownInManager.length > 0);
check('Show model in Model Manager shows Previous Position', showing(), true);
check('pressed, the page goes back to where it was', pressBack(), 7000);

// ------------------------------------------------------------ the grid starting again clears it
// The place is a height in the grid it was noted in: in another grid - a
// group opened, Back, a search, Refresh - it would land on other images.
const noteBySend = async (y) => {
    scrollY(y);
    const sent = pastes.length;
    await press(document.querySelector('#gen_grid [data-action="generations.send"][data-tile="0"]'));
    await waitFor('the paste', () => pastes.length > sent);
};
await press(document.getElementById('gen_refresh_btn'));
await waitFor('the grid again', () => document.querySelectorAll('#gen_grid .gen-tile').length === 1);
check('Refresh starts the grid again, and clears Previous Position', showing(), false);

await noteBySend(4000);
const box = document.getElementById('gen_search');
box.value = 'lighthouse';
await press(box);
check('a search clears it', showing(), false);
box.value = '';
await press(box);

// A batch of two, which opens onto its images.
tiles[0] = { ...tiles[0], matching_count: 2, images: [image, { ...image, id: 12, url: '/model-manager/generations/images/12/file' }] };
await press(document.getElementById('gen_refresh_btn'));
await waitFor('the batch', () => document.querySelector('#gen_grid [data-action="generations.open"][data-tile="0"]'));
await noteBySend(4500);
await press(document.querySelector('#gen_grid [data-action="generations.open"][data-tile="0"]'));
check('opening a batch clears it', showing(), false);
await waitFor('the batch opened', () => document.querySelector('[data-action="generations.back"]'));
await noteBySend(2500);
check('noted inside the batch, it shows', showing(), true);
await press(document.querySelector('[data-action="generations.back"]'));
check('Back clears it', showing(), false);

done();

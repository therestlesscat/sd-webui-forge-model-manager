// A jump to another tab lands where it means to (#263).
//
// The WebUI is one page with one scroll, and showing a tab kept it: a jump
// from deep in a gallery opened the Civitai Browser or the Model Manager at
// that depth, through the bottom while the model loaded. goToTab shows the
// tab, puts its tab bar at the top of the view at once, and lands where it is
// told - a number below the tab bar, an element, or what an entry answers -
// unless the person scrolls meanwhile. open() goes through it, and the
// entries of the Civitai Browser and the Model Manager answer their model's
// details.
//
// The suites have no layout: the tab bar and the targets are given
// positions here, and the check reads the scrolls asked for.
import { act, checker, mountTab, openTab, sharedModule, startTab, tabMarkup } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();
document.body.insertAdjacentHTML('beforeend', tabMarkup('model_manager/ui/tab_civitai_browser.py'));
document.body.insertAdjacentHTML('afterbegin', `
    <div id="tabs"><div class="tab-nav">
        <button id="tab_txt2img-button">txt2img</button>
        <button id="tab_img2img-button">img2img</button>
        <button id="tab_model_manager_tab-button">Model Manager</button>
        <button id="tab_civitai_browser_tab-button">Civitai Browser</button>
    </div></div>
    <div id="land_here"></div><div id="hidden_one"></div>`);

// --------------------------------------------------------- a layout of our own
// Where each thing is on the page, from its top; the view starts deep down.
const AT = { '.tab-nav': 120, '#land_here': 900, '#cb_details': 813, '#mm_details': 936 };
let scrollY = 5000;
Object.defineProperty(window, 'scrollY', { get: () => scrollY, configurable: true });
const scrolls = [];
window.scrollTo = (x, y) => {
    const top = typeof x === 'object' ? x.top : y;
    scrolls.push(top);
    scrollY = top;
};
for (const [selector, top] of Object.entries(AT)) {
    const element = document.querySelector(selector);
    if (element) element.getBoundingClientRect = () => ({ top: top - scrollY, bottom: top - scrollY + 50, height: 50, width: 400 });
}
const jump = async (run) => {
    scrollY = 5000;
    scrolls.length = 0;
    await run();
    return [...scrolls];
};

// ---------------------------------------------------------------- the server
const MODEL = { id: 600, name: 'Sea Spray', type: 'LORA', stats: {}, creator: {},
                modelVersions: [{ id: 6001, name: 'v1', images: [], files: [] }] };
const MANAGER_MODEL = { id: 1, model_id: 600, version_id: 6001, name: 'Sea Spray', model_type: 'LORA',
                        file_path: 'C:/models/Lora/sea_spray.safetensors' };
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (href.includes('/model-manager/ui-options')) return reply({ success: true, has_api_key: true });
    if (/\/model-manager\/civitai\/models\/600\b/.test(href)) return reply({ success: true, model: MODEL });
    if (/\/model-manager\/civitai\/models\/\d+/.test(href)) {
        return reply({ success: false, error: 'Model not found' });
    }
    if (href.includes('/model-manager/models/versions')) {
        return reply({ success: true, versions: [MANAGER_MODEL], civitai_versions: [] });
    }
    if (href.includes('/model-manager/models/details')) {
        return reply({ success: true, model: { civitai_version: { id: 6001 }, images: [], images_state: { version_id: 6001 } } });
    }
    if (href.includes('/model-manager/models')) {
        return reply({ success: true, total: 1, page: 1, page_size: 20, models: [MANAGER_MODEL] });
    }
    if (href.includes('/model-manager/images/gallery-page')) {
        return reply({ success: true, images: [], images_state: { version_id: 6001 } });
    }
    return reply({ success: true });
};

await startTab('modelManager');
await startTab('civitaiBrowser');
document.dispatchEvent(new window.Event('DOMContentLoaded'));
const { goToTab } = await sharedModule('tabs.mjs');
const go = (...args) => (goToTab ? goToTab(...args) : Promise.resolve('no goToTab'));

// --------------------------------------------------------------- goToTab
check('nothing named: the tab shown, its tab bar at the top of the view',
      await jump(() => go('txt2img')), [120]);
check('a number: the tab bar first, then that far below it', await jump(() => go('txt2img', 300)), [120, 420]);
check('{ top }: the tab bar first, then that place on the page - 0, the WebUI\'s header',
      await jump(() => go('txt2img', { top: 0 })), [120, 0]);
check('a selector: the tab bar first, then its element 8 px below the top of the view',
      await jump(() => go('txt2img', '#land_here')), [120, 892]);
check('an element, the same', await jump(() => go('txt2img', document.getElementById('land_here'))), [120, 892]);
check('a selector that finds nothing: the tab bar', await jump(() => go('txt2img', '#not_there')), [120]);
check('an element not shown: the tab bar', await jump(() => go('txt2img', '#hidden_one')), [120]);
check('a function - an entry - run once the tab shows, its answer the landing',
      await jump(() => go('txt2img', async () => '#land_here')), [120, 892]);
check('the person scrolling while it runs: no landing after it',
      await jump(() => go('txt2img', async () => {
          window.dispatchEvent(new window.Event('wheel'));
          return '#land_here';
      })), [120]);

// ------------------------------------------------- the entries, through open()
check('the Civitai Browser at a model: its details, once drawn',
      await jump(() => openTab('civitaiBrowser', 'showModel', 'model:600 version:6001')), [120, 805]);
check('a model Civitai has not: the tab bar, where the status line says so',
      await jump(() => openTab('civitaiBrowser', 'showModel', 'model:404404')), [120]);
check('the Model Manager at a model: its details',
      await jump(() => openTab('modelManager', 'showModel', 'model:600')), [120, 928]);
check('at a version: its details',
      await jump(() => openTab('modelManager', 'showVersion', 6001, MANAGER_MODEL.file_path)), [120, 928]);
check('at a file: its details',
      await jump(() => openTab('modelManager', 'showFile', MANAGER_MODEL.file_path)), [120, 928]);

done();

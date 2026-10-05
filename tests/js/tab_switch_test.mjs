// Moving between the WebUI's tabs (#87). The tabs found each other's button
// by its label, clicked it, and waited a fixed 100 ms before searching - the
// grid measures itself, and a hidden tab measures nothing. Slower than that,
// the search ran on a hidden tab; a translated label, and nothing was found.
//
// Here a stand-in for Gradio shows a tab's panel 300 ms after its button is
// clicked, as a slow machine might. A model asked for in another tab is shown
// there: the tab is switched by its id, and the search runs once its panel
// shows - not before, and not never. And the ids are the ones the extension's
// tabs register with.
import { readFileSync } from 'node:fs';
import { ROOT, checker, mountTab, tabMarkup } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
for (const tab of ['tab_civitai_browser.py', 'tab_generations.py']) {
    document.body.insertAdjacentHTML('beforeend', tabMarkup(`model_manager/ui/${tab}`));
}
const { check, waitFor, done } = checker();

// ------------------------------------------------- a stand-in for Gradio
// Gradio 4 gives a tab's panel the id it was registered with and its button
// that id with "-button"; a click selects the button, and shows the panel by
// setting its display.
const SHOW_AFTER = 300;
let gradioStuck = false;            // shows nothing at all
window.mmTiming = { tabShown: 1000 };
const TABS = [['tab_txt2img', 'txt2img'], ['tab_img2img', 'img2img'], ['tab_generations_tab', 'Generations'],
              ['tab_model_manager_tab', 'Model Manager'], ['tab_civitai_browser_tab', 'Civitai Browser']];
const bar = document.createElement('div');
bar.id = 'tabs';
document.body.prepend(bar);
const panel = (id) => document.getElementById(id);
const shows = (id) => panel(id).style.display !== 'none';
for (const [id, label] of TABS) {
    const button = document.createElement('button');
    button.id = `${id}-button`;
    button.textContent = label;
    button.addEventListener('click', () => {
        bar.querySelectorAll('button').forEach((b) => {
            b.classList.toggle('selected', b === button);
            b.setAttribute('aria-selected', String(b === button));
        });
        if (gradioStuck) return;
        setTimeout(() => TABS.forEach(([other]) => { panel(other).style.display = other === id ? 'block' : 'none'; }),
                   SHOW_AFTER);
    });
    bar.appendChild(button);
    const box = document.createElement('div');
    box.id = id;
    box.style.display = id === 'tab_generations_tab' ? 'block' : 'none';
    document.body.appendChild(box);
}
bar.querySelector('#tab_generations_tab-button').classList.add('selected');

// ------------------------------------------------------------ the server
// Each search, with whether its tab was showing when it was asked for.
const searches = [];
globalThis.onAfterUiUpdate = () => {};
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/model-manager/civitai/models')) {
        searches.push({ tab: 'civitaiBrowser', showing: shows('tab_civitai_browser_tab') });
        return reply({ success: false, error: 'Model not found' });
    }
    if (href.includes('/model-manager/models?') && href.includes('model%3A12345')) {
        searches.push({ tab: 'modelManager', showing: shows('tab_model_manager_tab') });
        return reply({ success: true, total: 0, page: 1, page_size: 20, models: [] });
    }
    return reply({ success: true });
};

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
await import(`file:///${ROOT}/javascript/civitai_browser.mjs`);
await import(`file:///${ROOT}/javascript/generations.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));
const { call } = await import(`file:///${ROOT}/javascript/shared/calls.mjs`);
const selected = () => bar.querySelector('button.selected')?.id;

// ------------------------------------------ the Civitai Browser, asked for
call('civitaiBrowser.showModel', 'model:12345');
await waitFor('the Civitai Browser\'s search', () => searches.some((s) => s.tab === 'civitaiBrowser'), 30);
check('a model asked of the Civitai Browser switches to its tab', selected(), 'tab_civitai_browser_tab-button');
check('and is searched for once that tab shows - not while it is hidden',
      searches.filter((s) => s.tab === 'civitaiBrowser'), [{ tab: 'civitaiBrowser', showing: true }]);

// ------------------------------- the Model Manager, from the browser's button
await new Promise((r) => setTimeout(r, SHOW_AFTER + 50));
call('civitaiBrowser.showInModelManager', { modelId: 12345 });     // the details' button, not drawn here
await waitFor('the Model Manager\'s search', () => searches.some((s) => s.tab === 'modelManager'), 30);
check('"Show in Model Manager" switches to the Model Manager', selected(), 'tab_model_manager_tab-button');
check('and searches once it shows',
      searches.filter((s) => s.tab === 'modelManager'), [{ tab: 'modelManager', showing: true }]);

// ----------------------------------------- a translated, reordered tab bar
await new Promise((r) => setTimeout(r, SHOW_AFTER + 50));
const translated = { 'Model Manager': 'Modellverwaltung', 'Civitai Browser': 'Civitai-Browser', Generations: 'Generierungen' };
bar.querySelectorAll('button').forEach((b) => { b.textContent = translated[b.textContent] || b.textContent; });
bar.prepend(bar.querySelector('#tab_civitai_browser_tab-button'));
searches.length = 0;
call('civitaiBrowser.showModel', 'model:12345');
await waitFor('the search, with the labels translated', () => searches.length > 0, 30);
check('a translated label and another order find the same tab', selected(), 'tab_civitai_browser_tab-button');

// ------------------------------------------- a tab that never shows
// Nothing waits for ever: past TIMING.tabShown the search runs anyway.
await new Promise((r) => setTimeout(r, SHOW_AFTER + 50));
gradioStuck = true;
searches.length = 0;
const asked = Date.now();
call('modelManager.showModel', 'model:12345');
await waitFor('the search, though the tab never showed', () => searches.length > 0, 40);
check('a tab that never shows is waited on no longer than TIMING.tabShown, then searched anyway',
      [searches[0]?.showing, Date.now() - asked >= 1000], [false, true]);

// ------------------------------------------------------------- the ids
// The panel ids are the WebUI's "tab_" and the id each tab registers with.
const registered = ['scripts/model_manager_ui.py', 'model_manager/ui/tab_model_manager.py']
    .flatMap((file) => [...readFileSync(`${ROOT}/${file}`, 'utf8').matchAll(/,\s*"(\w+_tab)"\)/g)].map((m) => `tab_${m[1]}`));
let tabsSource = '';
try { tabsSource = readFileSync(`${ROOT}/javascript/shared/tabs.mjs`, 'utf8'); } catch { /* not there */ }
check('the extension\'s four tabs register', registered.sort(),
      ['tab_civitai_browser_tab', 'tab_generations_tab', 'tab_model_manager_tab', 'tab_queue_tab']);
check('and the page finds each by that id', registered.filter((id) => !tabsSource.includes(`'${id}'`)), []);

done();

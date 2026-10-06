// The Civitai Browser's Save Search: one set of filters, kept in the
// database (the server's side: settings_api_test.py). The first time the tab
// shows, the page fills the bar from it and runs it - not at page load, when
// every tab loads and a search would ask Civitai whether or not the tab is
// ever looked at. Save keeps the bar's filters; a right-click forgets them.
//
// The page here does what Gradio does, which the search was lost to (#128):
// it draws the tab after the answers have come, so a bar filled then was
// filled before it existed; and a click on the tab's button replaces that
// button before the click reaches the document, so a listener there never
// saw a click on it. After each change the WebUI runs its after-update
// callbacks, as onAfterUiUpdate does.
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();
const afterUpdate = [];
globalThis.onAfterUiUpdate = (callback) => afterUpdate.push(callback);
const updated = () => afterUpdate.forEach((callback) => callback());

// Forge's tab bar, the Model Manager showing. Clicked, a tab's button is
// replaced by a selected one, as Gradio's Tabs do, before the click goes on.
document.body.insertAdjacentHTML('afterbegin', `
    <div id="tabs">
        <button id="tab_model_manager_tab-button" class="selected" aria-selected="true">Model Manager</button>
        <button id="tab_civitai_browser_tab-button">Civitai Browser</button>
    </div>`);
function selectOnClick(button) {
    button.addEventListener('click', () => {
        for (const other of document.querySelectorAll('#tabs button')) {
            other.classList.remove('selected');
            other.setAttribute('aria-selected', 'false');
        }
        const selected = button.cloneNode(true);
        selected.classList.add('selected');
        selected.setAttribute('aria-selected', 'true');
        button.replaceWith(selected);
        selectOnClick(selected);
    });
}
document.querySelectorAll('#tabs button').forEach(selectOnClick);
const browserTab = () => Array.from(document.querySelectorAll('#tabs button')).find((b) => b.textContent === 'Civitai Browser');
const clickTab = () => {
    browserTab().dispatchEvent(new window.Event('click', { bubbles: true }));
    updated();
};

// The tab not drawn yet: Gradio draws it after the scripts have run.
const app = document.getElementById('civitai_browser_app');
const appPlace = app.parentNode;
app.remove();

const SAVED = {
    query: 'lighthouse', types: 'LORA', checkpoint_type: '', base_models: 'Brand New Base 2', sort: 'Newest',
    period: 'Month', nsfw: true, tag: 'landscape', require_prompt: false, sfw_only: false, min_size: '', max_size: '',
};
const searches = [];
const saves = [];
const asked = [];
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    if (href.includes('/saved-search')) asked.push('saved-search');
    if (href.includes('/civitai/enums')) asked.push('enums');
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/model-manager/saved-search')) {
        if (init.method === 'POST') {
            saves.push(JSON.parse(init.body));
            return reply({ success: true });
        }
        return reply({ success: true, filters: SAVED });
    }
    if (href.includes('/model-manager/civitai/enums')) {
        // Brand New Base 2 is not among the page's own options: it takes only once these are in.
        return reply({ success: true, model_types: ['Checkpoint', 'LORA'], base_models: ['SDXL 1.0', 'Brand New Base 2'] });
    }
    if (href.includes('/model-manager/civitai/models')) {
        searches.push(new URL(href, 'http://webui').searchParams);
        return reply({ success: true, nextCursor: null, pageSize: 20, models: [] });
    }
    return reply({ success: true });
};

await import(`file:///${ROOT}/javascript/civitai_browser.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));

// A moment passes before Gradio draws the tab: time enough for the answers -
// the saved search, Civitai's lists - had the page asked for them.
await new Promise((resolve) => setTimeout(resolve, 300));
appPlace.append(app);
updated();
await waitFor('the saved search to be asked', () => asked.includes('saved-search') && asked.includes('enums'));
await new Promise((resolve) => setTimeout(resolve, 50));
check('the tab drawn but not shown: Civitai is asked nothing', searches.length, 0);

const $ = (id) => document.getElementById(id);
clickTab();
await waitFor('the search', () => searches.length > 0);
const first = searches[0];
check('shown the first time, it searches once, with the saved filters',
      [first?.get('query'), first?.get('types'), first?.get('base_models'), first?.get('sort'), first?.get('tag')],
      ['lighthouse', 'LORA', 'Brand New Base 2', 'Newest', 'landscape']);
check('and the bar shows them - a base model Civitai\'s list brings included - and the tag as a chip',
      [$('cb_search').value, $('cb_type').value, $('cb_base_model').value, $('cb_sort').value, $('cb_period').value,
       $('cb_nsfw').checked, $('cb_tag_chip_name')?.textContent],
      ['lighthouse', 'LORA', 'Brand New Base 2', 'Newest', 'Month', true, 'landscape']);
clickTab();
await new Promise((resolve) => setTimeout(resolve, 50));
check('and not again when the tab is shown again', searches.length, 1);

$('cb_search').value = 'harbour';
$('cb_save_search_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the save', () => saves.length > 0);
check('Save Search keeps the bar as it is, for this tab',
      [saves[0]?.tab, saves[0]?.filters?.query, saves[0]?.filters?.base_models, saves[0]?.filters?.tag],
      ['civitai_browser', 'harbour', 'Brand New Base 2', 'landscape']);
$('cb_save_search_btn').dispatchEvent(new window.Event('contextmenu', { bubbles: true }));
await waitFor('the clearing', () => saves.length > 1);
check('and a right-click forgets it', saves[1], { tab: 'civitai_browser', filters: null });

done();

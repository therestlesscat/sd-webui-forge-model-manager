// The Civitai Browser's Save Search: one set of filters, kept in the
// database (the server's side: settings_api_test.py). The page fills the bar
// from it as soon as Civitai's lists are in, and runs it the first time the
// tab is shown - not at page load, when every tab loads and a search would ask
// Civitai whether or not the tab is ever looked at. Save keeps the bar's
// filters; a right-click forgets them.
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();

// Forge's tab bar, the Model Manager showing.
document.body.insertAdjacentHTML('afterbegin', `
    <div id="tabs">
        <button id="tab_model_manager_tab-button" class="selected" aria-selected="true">Model Manager</button>
        <button id="tab_civitai_browser_tab-button">Civitai Browser</button>
    </div>`);
const browserTab = () => Array.from(document.querySelectorAll('#tabs button')).find((b) => b.textContent === 'Civitai Browser');

const SAVED = {
    query: 'lighthouse', types: 'LORA', checkpoint_type: '', base_models: 'Brand New Base 2', sort: 'Newest',
    period: 'Month', nsfw: true, tag: 'landscape', require_prompt: false, sfw_only: false, min_size: '', max_size: '',
};
const searches = [];
const saves = [];
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
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

const $ = (id) => document.getElementById(id);
await waitFor('the saved search', () => $('cb_search')?.value === 'lighthouse');
check('the saved search fills the bar - a base model Civitai\'s list brings included - and the tag as a chip',
      [$('cb_type').value, $('cb_base_model').value, $('cb_sort').value, $('cb_period').value, $('cb_nsfw').checked,
       $('cb_tag_chip_name')?.textContent],
      ['LORA', 'Brand New Base 2', 'Newest', 'Month', true, 'landscape']);
await new Promise((resolve) => setTimeout(resolve, 50));
check('but asks Civitai nothing while the tab is not shown', searches.length, 0);

browserTab().dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the search', () => searches.length > 0);
const asked = searches[0];
check('shown the first time, it searches once, with the saved filters',
      [asked.get('query'), asked.get('types'), asked.get('base_models'), asked.get('sort'), asked.get('tag')],
      ['lighthouse', 'LORA', 'Brand New Base 2', 'Newest', 'landscape']);
browserTab().dispatchEvent(new window.Event('click', { bubbles: true }));
await new Promise((resolve) => setTimeout(resolve, 50));
check('and not again when the tab is shown again', searches.length, 1);

$('cb_search').value = 'harbour';
$('cb_save_search_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the save', () => saves.length > 0);
check('Save Search keeps the bar as it is, for this tab',
      [saves[0].tab, saves[0].filters.query, saves[0].filters.base_models, saves[0].filters.tag],
      ['civitai_browser', 'harbour', 'Brand New Base 2', 'landscape']);
$('cb_save_search_btn').dispatchEvent(new window.Event('contextmenu', { bubbles: true }));
await waitFor('the clearing', () => saves.length > 1);
check('and a right-click forgets it', saves[1], { tab: 'civitai_browser', filters: null });

done();

// The Model Manager's Base Model filter lists what the library holds.
//
// Its options were written into the markup and named the base models
// installed when they were written: a model on Wan Video 14B t2v, Anima or
// Krea 2 could not be filtered to at all. They now come from the server. A
// saved search is restored without waiting for them, so a base model it names
// has to survive the list arriving after it - and one no longer in the
// library stays selected rather than quietly becoming "All".
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

const LIBRARY = ['Wan Video 14B t2v', 'Other', 'Anima', 'SDXL 1.0'];
let answerFilters;
const filtersAsked = new Promise((resolve) => { answerFilters = resolve; });
const listed = [];
const saves = [];
// The saved search is in the database; this one was left in the browser by
// an earlier version, and is moved there on the way.
let savedOnServer = null;
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    if (href.includes('/model-manager/saved-search')) {
        if (init.method === 'POST') {
            saves.push(JSON.parse(init.body));
            savedOnServer = saves.at(-1).filters;
        }
        return { ok: true, json: async () => ({ success: true, filters: savedOnServer }) };
    }
    if (href.includes('/model-manager/filters')) {
        await filtersAsked;   // held back until the saved search is restored
        return { ok: true, json: async () => ({ success: true, base_models: LIBRARY }) };
    }
    if (href.includes('/model-manager/models?') || href.endsWith('/model-manager/models')) {
        listed.push(new URL(href, 'http://webui').searchParams);
    }
    return { ok: true, json: async () => ({ success: true, models: [], total: 0, page: 1,
        page_size: 20 }) };
};

window.localStorage.setItem('mm_saved_filters', JSON.stringify({ base_model: 'Wan Video 14B t2v' }));
await import(`file:///${ROOT}/javascript/model_manager.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => document.getElementById(id);
const options = () => [...$('mm_base_model').options].map((o) => o.value);

await waitFor('the saved search', () => $('mm_base_model').value === 'Wan Video 14B t2v');
check('the markup names no base model of its own', options(), ['', 'Wan Video 14B t2v']);
check('a saved search is restored before the list arrives',
      $('mm_base_model').value, 'Wan Video 14B t2v');
check('one this browser kept, from before, is moved to the database, and from the browser',
      [saves.map((s) => [s.tab, s.filters.base_model]), window.localStorage.getItem('mm_saved_filters')],
      [[['model_manager', 'Wan Video 14B t2v']], null]);

answerFilters();
await waitFor('the library\'s base models', () => options().length > 2);
check('the list is the library\'s, alphabetical, Other last',
      options(), ['', 'Anima', 'SDXL 1.0', 'Wan Video 14B t2v', 'Other']);
check('and the saved choice is still chosen', $('mm_base_model').value, 'Wan Video 14B t2v');

const before = listed.length;
$('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the grid request', () => listed.length > before);
check('and is what the grid is asked for', listed[listed.length - 1].get('base_model'),
      'Wan Video 14B t2v');

done();

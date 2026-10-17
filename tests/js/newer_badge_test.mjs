// The New version badge and the Newer Version filter, in the Model Manager
// (#218). The server says which versions Civitai lists before every one held
// (`newer_versions`, mm_newer_test.py); a card shows a badge for them - the
// one the Civitai Browser's cards show (cb_newer_badge_test.mjs) - and its
// tooltip names them, with their base model and what keeps them from a plain
// download, and how old the stored list is. The filter is sent with Load
// Models, kept with Save Search, and loosened when a model is jumped to.
import { checker, mountTab, startTab, openTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

const v = (id, name, extra = {}) => ({ id, name, base_model: 'SDXL 1.0', paid: null, on_site_only: null, ...extra });
const CARD = (id, newer, synced = '2026-10-12T09:00:00') => ({
    id: id * 10, model_id: id, civitai_model_id: id, display_name: `M${id}`, model_type: 'LORA', base_model: 'SDXL 1.0',
    has_civitai_data: true, local_version_count: 1, nsfw_level: 1, newer_versions: newer, versions_synced_at: synced,
});
const MODELS = [
    CARD(1, [v(11, 'v3', { paid: 'Early Access' }), v(12, 'v2', { base_model: 'Illustrious', on_site_only: true })]),
    CARD(2, []),
    CARD(3, [v(31, 'v9')]),
    CARD(4, Array.from({ length: 7 }, (_, n) => v(40 + n, `v${10 - n}`))),
];

const listed = [];
const saves = [];
let savedOnServer = { newer_version: 'available' };
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    if (href.includes('/model-manager/saved-search')) {
        if (init.method === 'POST') {
            saves.push(JSON.parse(init.body));
            savedOnServer = saves.at(-1).filters;
        }
        return { ok: true, json: async () => ({ success: true, filters: savedOnServer }) };
    }
    if (href.includes('/model-manager/models?') || href.endsWith('/model-manager/models')) {
        listed.push(new URL(href, 'http://webui').searchParams);
        return { ok: true, json: async () => ({ success: true, models: MODELS, total: MODELS.length, page: 1, page_size: 20 }) };
    }
    return { ok: true, json: async () => ({ success: true, models: [], total: 0, page: 1, page_size: 20 }) };
};

await startTab('modelManager');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => document.getElementById(id);
const load = async () => {
    const before = listed.length;
    $('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
    await waitFor('the grid request', () => listed.length > before);
    await waitFor('the cards', () => document.querySelectorAll('#mm_grid .model-card').length === MODELS.length);
    return listed.at(-1);
};

// ---------------------------------------------------------------- the filter
const select = $('mm_newer_version');
check('Newer Version is in Advanced filters: Any, or Available',
      [!!select?.closest('#mm_advanced'), Array.from(select?.options || []).map((o) => [o.value, o.textContent])],
      [true, [['', 'Any'], ['available', 'Available']]]);
// A page without the filter has failed the check above; the rest would only crash on it.
if (!select) done();
await waitFor('the saved search', () => select.value === 'available');
check('a saved search restores it', select.value, 'available');
const asked = await load();
check('Load Models asks for it', asked.get('newer_version'), 'available');

// ----------------------------------------------------------------- the badge
const badgeOf = (id) => document.querySelector(`#mm_grid .model-card[data-model-id="${id}"] .badge.newer-badge`);
check('a card with two newer versions says so, among its badges',
      [badgeOf(1)?.textContent, !!badgeOf(1)?.closest('.model-card')?.querySelector('.type-badge')],
      ['2 new versions', true]);
check('its tooltip names each, with its base model and what keeps it from a plain download, and the list\'s age',
      badgeOf(1)?.getAttribute('title'),
      'Newer on Civitai than any version you have: v3 (SDXL 1.0, early access), v2 (Illustrious, on-site only)\n'
      + 'As of the last sync, Oct 12, 2026');
check('one newer version: New version', badgeOf(3)?.textContent, 'New version');
// The badge row keeps to one line (#218, R3): the type is cut short first,
// with an ellipsis, so it says its whole name when held over.
check('the type badge names itself in full, held over',
      document.querySelector('#mm_grid .model-card[data-model-id="1"] .badge.type-badge')?.getAttribute('title'), 'LORA');
check('a card with none has no badge', badgeOf(2), null);
check('seven: the newest five named, then how many more',
      badgeOf(4)?.getAttribute('title')?.split('\n')[0],
      'Newer on Civitai than any version you have: v10 (SDXL 1.0), v9 (SDXL 1.0), v8 (SDXL 1.0), '
      + 'v7 (SDXL 1.0), v6 (SDXL 1.0), and 2 more');

// ------------------------------------------------------- saved, and loosened
select.value = '';
$('mm_save_search_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the save', () => saves.length > 0);
check('Save Search keeps it', saves.at(-1).filters.newer_version, '');
select.value = 'available';
await openTab('modelManager', 'showModel', 'model:1');
check('jumping to a model loosens it, with every other filter', select.value, '');

done();

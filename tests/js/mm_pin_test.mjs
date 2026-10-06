// Pinning a card in the Model Manager's grid, and the grid's two tabs: the
// pinned models, and the rest (the server's side: grid_query_test.py). The
// page opens on Unpinned; the 📌 on a card's corner and beside the bookmark in
// its details both pin it - a Civitai model by its id, a file Civitai does
// not know by its path - and show it pinned where it is, without moving it
// from under the pointer; the tabs' counts follow at once.
import { ROOT, act, checker, mountTab, press, startTab, withGalleryPages } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
// The page first: the registry listens to it when it loads.
const { call } = await import(`file:///${ROOT}/javascript/shared/calls.mjs`);
const { check, waitFor, done } = checker();

const model = (over) => ({
    version_name: 'v1', base_model: 'SDXL 1.0', model_type: 'LORA', file_size: 1, nsfw_level: 1,
    local_version_count: 1, trained_words: [], tags: [], preview_url: '', ...over,
});
const PINNED = model({ id: 501, model_id: 50, name: 'Pinned already', display_name: 'Pinned already',
                       is_pinned: true, has_civitai_data: true, file_path: 'C:/m/a.safetensors',
                       file_name: 'a.safetensors' });
const LOCAL = model({ id: 502, model_id: null, name: 'Local only', display_name: 'Local only', is_pinned: false,
                      has_civitai_data: false, file_path: 'C:/m/b.safetensors', file_name: 'b.safetensors' });
const pins = [];
const asked = [];
// What the server's tabs hold; a section changes it to stand for the library.
let tabs = { pinned: [PINNED], others: [LOCAL] };
globalThis.fetch = withGalleryPages(async (url, init = {}) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/model-manager/pin')) {
        pins.push(Object.fromEntries(new URLSearchParams(String(init.body))));
        return reply({ success: true });
    }
    if (href.includes('/models/details')) {
        return reply({ success: true, model: { ...PINNED, images: [], generations_count: 0,
            images_state: { version_id: null, total_count: 0, filtered_count: 0, offset: 0 } } });
    }
    if (href.includes('/models/versions')) return reply({ success: true, versions: [PINNED] });
    if (href.includes('/model-manager/models')) {
        const params = new URL(href, 'http://webui').searchParams;
        asked.push(params);
        const search = params.get('search') || '';
        const match = (list) => list.filter((m) => !search || m.name.includes(search));
        const pinned = match(tabs.pinned);
        const others = match(tabs.others);
        const shown = params.get('pinned') === 'true' ? pinned : others;
        return reply({ success: true, total: shown.length, page: 1, page_size: 20, models: shown,
                       tab_counts: { pinned: pinned.length, others: others.length } });
    }
    return reply({ success: true });
});

await startTab('modelManager');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const names = () => Array.from(document.querySelectorAll('#mm_grid .model-card-name')).map((n) => n.textContent);
const tab = (which) => document.querySelector(`#mm_grid_tabs [data-grid-tab="${which}"]`);
const tabText = (which) => tab(which)?.textContent.replace(/\s+/g, ' ').trim();
const cardPin = (i) => document.querySelector(`#mm_grid .model-card[data-index="${i}"] .mm-pin-btn`);
const click = (element) => element.dispatchEvent(new window.Event('click', { bubbles: true }));

// A tab changes what the loaded grid shows; before Load Models it loads nothing.
click(tab('pinned'));
await new Promise((resolve) => setTimeout(resolve, 50));
click(tab('others'));
await new Promise((resolve) => setTimeout(resolve, 50));
check('a tab clicked before Load Models only switches, and loads nothing',
      [asked.length, document.querySelectorAll('#mm_grid .model-card').length, tab('others').classList.contains('active')],
      [0, 0, true]);
check('the tabs are the gallery\'s tabs', [tab('pinned').className, tab('others').className],
      ['mm-gallery-tab', 'mm-gallery-tab active']);
document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the grid', () => document.querySelectorAll('#mm_grid .model-card').length === 1);

check('the grid opens on Unpinned: the models not pinned, asked for as such',
      [names(), asked.at(-1)?.get('pinned'), tab('others').classList.contains('active')],
      [['Local only'], 'false', true]);
check('each tab says how many match the filters', [tabText('pinned'), tabText('others')],
      ['📌 Pinned (1)', 'Unpinned (1)']);
check('every card has a pin, whose click is its own, not the card\'s',
      [cardPin(0)?.className, cardPin(0)?.dataset.action, cardPin(0)?.dataset.index],
      ['mm-pin-btn', 'modelManager.togglePin', '0']);

await press(cardPin(0));
check('a file Civitai does not know is pinned by its path',
      pins.at(-1), { pinned: 'true', file_path: 'C:/m/b.safetensors' });
check('and its card shows it pinned, where it was, and the counts follow',
      [cardPin(0)?.className, names(), tabText('pinned'), tabText('others')],
      ['mm-pin-btn pinned', ['Local only'], '📌 Pinned (2)', 'Unpinned (0)']);

click(tab('pinned'));
await waitFor('the Pinned tab', () => names()[0] === 'Pinned already');
check('the Pinned tab asks for the pinned models, and is the one lit',
      [asked.at(-1)?.get('pinned'), tab('pinned').classList.contains('active'),
       tab('others').classList.contains('active')], ['true', true, false]);

await act('modelManager.togglePin', { index: 0 });
check('a model is unpinned by its id', pins.at(-1), { pinned: 'false', model_id: '50' });
check('and its card no longer shows it, still where it was', [cardPin(0)?.className, names()],
      ['mm-pin-btn', ['Pinned already']]);
await act('modelManager.togglePin', { index: 0 });

await act('modelManager.selectModel', { index: 0 });
await waitFor('the details', () => document.querySelector('#mm_details .detail-header'));
const detailsPin = () => document.querySelector('#mm_details .mm-pin-toggle');
check('the details panel has the pin beside the bookmark, as the card shows it',
      [detailsPin()?.classList.contains('pinned'), detailsPin()?.dataset.action, detailsPin()?.dataset.index],
      [true, 'modelManager.togglePin', '0']);
await press(detailsPin());
check('which unpins it there and on the card together',
      [detailsPin()?.classList.contains('pinned'), cardPin(0)?.className, pins.at(-1)],
      [false, 'mm-pin-btn', { pinned: 'false', model_id: '50' }]);

// Nothing pinned: the tab says how to pin.
tabs = { pinned: [], others: [LOCAL] };
click(tab('others'));
await waitFor('Unpinned', () => tab('others').classList.contains('active') && names()[0] === 'Local only');
click(tab('pinned'));
await waitFor('an empty Pinned tab', () => document.querySelector('#mm_grid .model-grid-empty'));
check('an empty Pinned tab says how to pin',
      document.querySelector('#mm_grid .model-grid-empty')?.textContent.trim(),
      'No pinned models match your filters. Pin a model with the 📌 on its card to keep it in this tab.');

// "Show model in Model Manager" finds a model in whichever tab holds it.
tabs = { pinned: [PINNED], others: [LOCAL] };
click(tab('others'));
await waitFor('Unpinned', () => names()[0] === 'Local only');
await call('modelManager.showModel', 'Pinned already');
check('a model shown from elsewhere is found in the Pinned tab if it is pinned, and opened',
      [tab('pinned').classList.contains('active'), names(), !!document.querySelector('#mm_details .detail-header')],
      [true, ['Pinned already'], true]);

done();

// Pinning a card in the Model Manager's grid: it then comes first whenever it
// matches the filters (the server's order: grid_query_test.py). The 📌 on a
// card's corner and beside the bookmark in its details both pin it - a
// Civitai model by its id, a file Civitai does not know by its path - and
// both show it pinned, without moving the card from under the pointer.
import { ROOT, checker, mountTab, withGalleryPages } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

const model = (over) => ({
    version_name: 'v1', base_model: 'SDXL 1.0', model_type: 'LORA', file_size: 1, nsfw_level: 1,
    local_version_count: 1, trained_words: [], tags: [], preview_url: '', ...over,
});
const MODELS = [
    model({ id: 501, model_id: 50, name: 'Pinned already', display_name: 'Pinned already', is_pinned: true,
            has_civitai_data: true, file_path: 'C:/m/a.safetensors', file_name: 'a.safetensors' }),
    model({ id: 502, model_id: null, name: 'Local only', display_name: 'Local only', is_pinned: false,
            has_civitai_data: false, file_path: 'C:/m/b.safetensors', file_name: 'b.safetensors' }),
];
const pins = [];
globalThis.fetch = withGalleryPages(async (url, init = {}) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/model-manager/pin')) {
        pins.push(Object.fromEntries(new URLSearchParams(String(init.body))));
        return reply({ success: true });
    }
    if (href.includes('/models/details')) {
        return reply({ success: true, model: { ...MODELS[1], images: [], generations_count: 0,
            images_state: { version_id: null, total_count: 0, filtered_count: 0, offset: 0 } } });
    }
    if (href.includes('/models/versions')) return reply({ success: true, versions: [MODELS[1]] });
    if (href.includes('/model-manager/models')) {
        return reply({ success: true, total: 2, page: 1, page_size: 20, models: MODELS });
    }
    return reply({ success: true });
});

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));
document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the grid', () => document.querySelectorAll('#mm_grid .model-card').length === 2);

const cardPin = (i) => document.querySelector(`#mm_grid .model-card[data-index="${i}"] .mm-pin-btn`);
check('every card has a pin, marked on the one pinned',
      [cardPin(0)?.className, cardPin(1)?.className], ['mm-pin-btn pinned', 'mm-pin-btn']);
check('a click on it is its own, not the card\'s',
      cardPin(1)?.getAttribute('onclick'), 'event.stopPropagation(); window.mmTogglePin(1)');

await window.mmTogglePin(1);
check('a file Civitai does not know is pinned by its path',
      pins.at(-1), { pinned: 'true', file_path: 'C:/m/b.safetensors' });
check('and its card shows it pinned, where it was',
      [cardPin(1)?.className, document.querySelector('#mm_grid .model-card[data-index="1"] .model-card-name')?.textContent],
      ['mm-pin-btn pinned', 'Local only']);

await window.mmTogglePin(0);
check('a model is unpinned by its id', pins.at(-1), { pinned: 'false', model_id: '50' });
check('and its card no longer shows it', cardPin(0)?.className, 'mm-pin-btn');

await window.mmSelectModel(1);
await waitFor('the details', () => document.querySelector('#mm_details .detail-header'));
const detailsPin = () => document.querySelector('#mm_details .mm-pin-toggle');
check('the details panel has the pin beside the bookmark, as the card shows it',
      [detailsPin()?.classList.contains('pinned'), detailsPin()?.getAttribute('onclick')],
      [true, 'window.mmTogglePin(1)']);
await window.mmTogglePin(1);
check('which unpins it there and on the card together',
      [detailsPin()?.classList.contains('pinned'), cardPin(1)?.className, pins.at(-1)],
      [false, 'mm-pin-btn', { pinned: 'false', file_path: 'C:/m/b.safetensors' }]);

done();

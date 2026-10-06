// "Select" on a model's Your generations (#21), as in the Generations tab
// (generations_select_test.mjs): a tick on every card - its generation whole,
// as its Delete - shift-click for a range, Select all loaded, and one Delete
// for all, asked once. Select and Rate are not on together.
import { ROOT, act, checker, mountTab, startTab, tick, withGalleryPages } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

const MODEL = {
    id: 5001, model_id: 4001, name: 'A Model', display_name: 'A Model', version_name: 'v1',
    base_model: 'SDXL 1.0', model_type: 'Checkpoint', file_path: 'C:/models/a.safetensors',
    file_name: 'a.safetensors', file_size: 1, nsfw_level: 1, has_civitai_data: true, local_version_count: 1,
    trained_words: [], tags: [],
};
const image = (id, generation) => ({
    id, generation_id: generation, position: 0, width: 832, height: 1216, meta: { prompt: `p ${id}` },
    infotext: `p ${id}`, url: `/model-manager/generations/images/${id}/file`, exists: true, mm_level: 1,
});
// Three generations: the second has one image of its three hidden by the NSFW filter.
let cards = [
    { id: 1, created_at: '2026-09-28T15:00:00', mode: 'txt2img', image_count: 2, matching_count: 2,
      images: [image(11, 1), image(12, 1)] },
    { id: 2, created_at: '2026-09-28T14:00:00', mode: 'txt2img', image_count: 3, matching_count: 2,
      images: [image(21, 2), image(22, 2)] },
    { id: 3, created_at: '2026-09-28T13:00:00', mode: 'txt2img', image_count: 1, matching_count: 1,
      images: [image(31, 3)] },
];
const deletes = [];
globalThis.fetch = withGalleryPages(async (url, init = {}) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/generations/delete-many')) {
        const body = Object.fromEntries(new URLSearchParams(String(init.body)));
        deletes.push(body);
        const gone = body.generation_ids.split(',').map(Number);
        cards = cards.filter((c) => !gone.includes(c.id));
        return reply({ success: true, images: 5, deleted_files: 0, failed: [] });
    }
    if (href.includes('/model-manager/generations/page')) {
        const shown = cards.reduce((n, c) => n + c.matching_count, 0);
        return reply({ success: true, generations: cards,
                       page: { number: 1, size: 100, generations: cards.length, count: shown, shown, more: false },
                       state: { offset: 0, generation_count: cards.length, total: 6, filtered: shown, hidden_nsfw: 1,
                                stored_generations: cards.length } });
    }
    if (href.includes('/models/details')) {
        return reply({ success: true, model: { ...MODEL, images: [], generations_count: cards.length,
            images_state: { version_id: 5001, total_count: 0, filtered_count: 0, offset: 0 } } });
    }
    if (href.includes('/models/versions')) return reply({ success: true, versions: [MODEL] });
    if (href.includes('/model-manager/models')) {
        return reply({ success: true, total: 1, page: 1, page_size: 20, models: [MODEL] });
    }
    return reply({ success: true });
});

await startTab('modelManager');
document.dispatchEvent(new window.Event('DOMContentLoaded'));
document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the grid', () => document.querySelector('#mm_grid .model-card'));
await act('modelManager.selectModel', { index: 0 });
await waitFor('the gallery', () => document.querySelector('#mm_images .mm-gallery-tab'));
await act('modelManager.showGalleryTab', { tab: 'generations' });
const cardEls = () => document.querySelectorAll('#mm_images .mm-generation-card');
await waitFor('the cards', () => cardEls().length === 3);

const ticks = () => Array.from(document.querySelectorAll('#mm_images [data-mm-pick]'));
const count = () => document.querySelector('#mm_images .mm-select-bar .mm-select-count')?.textContent;
// The tick's click reaches the page's listener, which counts it: no markup
// holds a handler that could stop it (check_js_references.mjs).
const pick = (i, shift = false) => {
    const box = ticks()[i];
    box.checked = !box.checked;
    box.dispatchEvent(Object.assign(new window.Event('click', { bubbles: true }), { shiftKey: shift }));
};

check('Select is beside Rate, off: no ticks', [!!document.getElementById('mm_select_generations'), ticks().length],
      [true, 0]);
tick('modelManager.selectGenerations', true);
check('on: a tick on every card, and the bar', [ticks().length, count()], [3, '0 images selected']);
pick(1);
check('a card\'s tick is its generation whole - its hidden image too', count(), '3 images selected');
pick(2, true);
check('shift-click ticks the range', [ticks().map((b) => b.checked), count()], [[false, true, true], '4 images selected']);
act('modelManager.clearGenerationPicks');
cardEls()[0].querySelector('[data-view-generation-image]').dispatchEvent(new window.Event('click', { bubbles: true }));
check('a click on a card\'s image ticks the card, and opens no viewer',
      [ticks()[0].checked, count(), !!document.querySelector('.mm-viewer')], [true, '2 images selected', false]);
act('modelManager.selectAllGenerations');
check('Select all loaded ticks every card', count(), '6 images selected');

const deleting = act('modelManager.deletePickedGenerations');
await waitFor('the question', () => document.querySelector('.mm-delete-dialog h3'));
check('Delete asks once, counting what the filter hides',
      document.querySelector('.mm-delete-dialog h3')?.textContent,
      'Delete 6 images of 3 generations? (1 of them hidden by the NSFW filter)');
document.querySelector('.mm-delete-dialog [data-confirm]').dispatchEvent(new window.Event('click', { bubbles: true }));
await deleting;
check('in one request, the generations whole, the files kept - as not asked',
      deletes, [{ generation_ids: '1,2,3', image_ids: '', delete_files: 'false' }]);
check('and the cards go', cardEls().length, 0);

tick('modelManager.rateGenerations', true);
check('Rate turns Select off', [document.getElementById('mm_select_generations')?.checked, ticks().length],
      [false, 0]);

done();

// The Civitai Images tab's grid setting (#240): Fast, placed by the tab, or
// Classic, the browser's grid - its own, apart from the Generations tab's.
//
// The tab opens as ui-options says, follows the setting as it is saved, and
// draws the same tiles, in the same order, either way.
import { checker, gridLayout, mountTab, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_gallery.py');
const { check, waitFor, done } = checker();

const tile = (id) => ({
    kind: 'image',
    image: { id, url: `https://image.civitai.com/x/original=true/${id}.jpeg`, width: id % 3 ? 1024 : 1600,
             height: id % 3 ? 1536 : 900, mm_level: 1, meta: { prompt: `a cat ${id}`, Model: 'm' } },
    model: { id: 40, name: 'A LoRA', civitai_type: 'LORA', model_type: 'LORA', base_model: 'SDXL 1.0' },
    version: { id: 400, name: 'v1', file_path: 'C:/models/Lora/a.safetensors', file_type: 'LORA', base_model: 'SDXL 1.0' },
});
let grid = 'Classic';
let otherGrid = 'Fast';
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (href.includes('/model-manager/gallery/browse')) {
        const page = Number(new URL(href, 'http://webui').searchParams.get('page'));
        const tiles = Array.from({ length: 100 }, (_, i) => tile((page - 1) * 100 + i + 1));
        return reply({ success: true, seed: 1, more: page < 2, scope: { count: 200 }, tiles,
                       state: { total: 200, filtered: 200, hidden_nsfw: 0, nsfw_count: 0 } });
    }
    if (href.includes('/model-manager/ui-options')) {
        return reply({ success: true, samplers: [], schedulers: [], gallery_hide_nsfw: true,
                       gallery_grid: grid, generations_grid: otherGrid });
    }
    return reply({ success: true });
};

const view = gridLayout(window, { top: 0, height: 1000 });
const gridEl = () => document.getElementById('gal_grid');
const ids = () => [...gridEl().querySelectorAll('.gen-tile img')].map((img) => img.getAttribute('data-src'));
const settle = () => new Promise((resolve) => setTimeout(resolve, 60));

await startTab('gallery');
await waitFor('both parts', () => gridEl().querySelectorAll('.gen-set').length === 200);
check('Classic saved before: the browser\'s grid, every tile on the page',
      [gridEl().classList.contains('gen-placed'), gridEl().style.height], [false, '']);
view({ height: 100000 });
const classic = ids();

async function saved(choice, key = 'model_manager_gallery_grid') {
    grid = choice;
    window.dispatchEvent(new window.CustomEvent('mm-settings-saved', { detail: { changed: [key], settings: {} } }));
    await settle();
    await settle();
}
await saved('Fast');
check('Fast saved: the tab\'s grid', gridEl().classList.contains('gen-placed'), true);
check('the same tiles, in the same order', ids(), classic);
view({ height: 1000 });
window.dispatchEvent(new window.Event('scroll'));
await settle();
check('only the rows near the view on the page', gridEl().querySelectorAll('.gen-set').length < 100, true);

// The Generations tab's setting is not this tab's.
otherGrid = 'Classic';
await saved('Fast', 'model_manager_generations_grid');
check('the Generations tab\'s setting leaves this grid as it was', gridEl().classList.contains('gen-placed'), true);
await saved('Classic');
check('Classic again: every tile on the page, no height of the tab\'s',
      [gridEl().classList.contains('gen-placed'), gridEl().style.height, gridEl().querySelectorAll('.gen-set').length],
      [false, '', 200]);

done();

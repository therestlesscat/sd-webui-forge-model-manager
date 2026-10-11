// A model's gallery in the Model Manager waits its turn for Civitai's images
// too (#213): drawn by the tab, through the image card's own markup, and not
// only the loader on its own. Every other gallery suite has a watcher that
// never says an image came into view, so none of their images ever starts.
import { act, checker, mountTab, startTab, withGalleryPages } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

// Says which images are in view, as the suite tells it - put in before the
// tab starts, so the loader's one watcher is this one.
let watcher = null;
globalThis.IntersectionObserver = class {
    constructor(callback) { this.callback = callback; this.watched = new Set(); watcher = this; }
    observe(el) { this.watched.add(el); }
    unobserve(el) { this.watched.delete(el); }
    disconnect() { this.watched.clear(); }
    show(els) { this.callback(els.filter((el) => this.watched.has(el)).map((target) => ({ target, isIntersecting: true }))); }
};

const C = 'https://image.civitai.com/acct/1234-abcd';
const MODEL = {
    id: 20937, model_id: 11718, name: 'Many images', display_name: 'Many images',
    version_name: 'v1', base_model: 'SD 1.5', model_type: 'Checkpoint',
    file_path: 'C:/m/a.safetensors', file_name: 'a.safetensors', file_size: 1, nsfw_level: 1,
    has_civitai_data: true, local_version_count: 1, trained_words: [], tags: [],
    preview_url: `${C}/original=true/cover.jpeg`,
};
const COUNT = 100;
const GALLERY = Array.from({ length: COUNT }, (_, i) => ({
    id: i + 1, url: `${C}/original=true/${i + 1}.jpeg`, width: 1024, height: 1536, type: 'image',
    nsfw: false, mm_level: 1, meta: { prompt: `a lighthouse by the sea, number ${i + 1}` },
}));
globalThis.fetch = withGalleryPages(async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/models/details')) {
        return reply({ success: true, model: { ...MODEL, images: GALLERY, generations_count: 0,
            images_state: { version_id: 20937, total_count: COUNT, filtered_count: COUNT, offset: 0,
                            hide_nsfw_images: false, hide_promptless_images: false } } });
    }
    if (href.includes('/models/versions')) return reply({ success: true, versions: [MODEL] });
    if (href.includes('/model-manager/models')) {
        return reply({ success: true, total: 1, page: 1, page_size: 20, models: [MODEL] });
    }
    if (href.includes('/model-manager/ui-options')) return reply({ success: true, images_at_once: 64 });
    return reply({ success: true });
});

await startTab('modelManager');
document.dispatchEvent(new window.Event('DOMContentLoaded'));
document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the card', () => document.querySelector('#mm_grid .model-card'));
await act('modelManager.selectModel', { index: 0 });
await waitFor('the gallery', () => document.querySelectorAll('#mm_images .mm-image-card img').length === COUNT);

const images = () => [...document.querySelectorAll('#mm_images .mm-image-card img')];
const asked = () => images().filter((img) => (img.getAttribute('src') || '').startsWith(C));
check('the gallery\'s images wait for the watcher', asked().length, 0);
watcher?.show(images());
check('100 of the gallery\'s images in view: 64 asked for', asked().length, 64);
// A load's event does not bubble; linkedom hands it to the page's capture
// listener only if it does.
asked()[0].dispatchEvent(new window.Event('load', { bubbles: true }));
check('one loads: the 65th is asked for', asked().length, 65);

done();

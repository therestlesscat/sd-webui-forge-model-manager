// A model's images in the Civitai Browser wait their turn for Civitai too
// (#213), drawn by the tab itself - as mm_gallery_queue_test.mjs shows for
// the Model Manager's gallery. Every other gallery suite has a watcher that
// never says an image came into view, so none of their images ever starts.
import { act, browserGalleryAnswer, checker, mountTab, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
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

const C = 'https://image.civitai.com/acct/5678-efgh';
const COUNT = 100;
const GALLERY = Array.from({ length: COUNT }, (_, i) => ({
    id: i + 1, url: `${C}/original=true/${i + 1}.jpeg`, width: 1024, height: 1536, type: 'image',
    nsfwLevel: 1, mm_level: 1, mm_level_from_prompt: false, meta: { prompt: `a lighthouse, number ${i + 1}` },
}));
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/ui-options')) return reply({ success: true, images_at_once: 64 });
    if (href.includes('/versions/')) return reply(browserGalleryAnswer(href, GALLERY));
    if (!href.includes('/model-manager/civitai/models')) return reply({ success: true });
    return reply({ success: true, nextCursor: null, pageSize: 20,
        models: [{ id: 1, name: 'Many images', type: 'Checkpoint', stats: {}, creator: {},
                   modelVersions: [{ id: 10, images: [], files: [] }] }] });
};

await startTab('civitaiBrowser');
document.dispatchEvent(new window.Event('DOMContentLoaded'));
document.getElementById('cb_status').textContent = '';
act('civitaiBrowser.search');
await waitFor('the grid', () => document.getElementById('cb_status').textContent.startsWith('Showing'));
act('civitaiBrowser.openModel', { index: 0 });
await waitFor('the gallery', () => document.querySelectorAll('#cb_images .mm-image-card img').length === COUNT);

const images = () => [...document.querySelectorAll('#cb_images .mm-image-card img')];
const asked = () => images().filter((img) => (img.getAttribute('src') || '').startsWith(C));
check('the gallery\'s images wait for the watcher', asked().length, 0);
watcher?.show(images());
check('100 of the gallery\'s images in view: 64 asked for', asked().length, 64);
// A load's event does not bubble; linkedom hands it to the page's capture
// listener only if it does.
asked()[0].dispatchEvent(new window.Event('load', { bubbles: true }));
check('one loads: the 65th is asked for', asked().length, 65);

done();

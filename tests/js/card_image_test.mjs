// The Civitai Browser card's image, with NSFW models included or not.
//
// A card shows its version's first showcase image. With NSFW models not
// included, Civitai sends PG images only, so that is safe as it comes - but
// the card no longer depends on it: an image above PG-13 is passed over for
// the first PG or PG-13 one, and a version with none shows no image at all.
// With NSFW models included, the first image is shown whatever it is.
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();

const img = (name, level) => ({ url: `https://example.invalid/${name}.jpeg`, nsfwLevel: level });
const MODELS = [
    { id: 1, name: 'Safe first', showcase: [img('pg', 1), img('r', 4)] },
    { id: 2, name: 'Unsafe first', showcase: [img('x', 8), img('r', 4), img('pg13', 2), img('pg', 1)] },
    { id: 3, name: 'Nothing safe', showcase: [img('r', 4), img('xxx', 16)] },
];

globalThis.fetch = async (url) => {
    if (!String(url).includes('/model-manager/civitai/models')) {
        return { ok: true, json: async () => ({ success: true }) };
    }
    return { ok: true, json: async () => ({ success: true, nextCursor: null, pageSize: 20,
        models: MODELS.map((m) => ({ id: m.id, name: m.name, type: 'Checkpoint', stats: {},
            creator: {}, modelVersions: [{ id: m.id * 10, images: m.showcase, files: [] }] })) }) };
};

await import(`file:///${ROOT}/javascript/civitai_browser.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => document.getElementById(id);
function previews() {
    return Array.from(document.querySelectorAll('#cb_grid .model-card')).map((card) => {
        const media = card.querySelector('.model-card-image img, .model-card-image video, img, video');
        const src = media?.getAttribute('src') || '';
        const name = (src.match(/example\.invalid\/([a-z0-9]+)\.jpeg/) || [])[1];
        return name || 'none';
    });
}
async function search() {
    $('cb_status').textContent = '';
    window.cbSearch();
    await waitFor('the grid', () => $('cb_status').textContent.startsWith('Showing'));
}

$('cb_nsfw').checked = false;
await search();
check('NSFW models not included: a safe first image is shown as it is, an unsafe one is passed over '
      + 'for the first PG or PG-13, and a version with none shows no image',
      previews(), ['pg', 'pg13', 'none']);

$('cb_nsfw').checked = true;
await search();
check('NSFW models included: the first image, whatever it is', previews(), ['pg', 'x', 'r']);


done();

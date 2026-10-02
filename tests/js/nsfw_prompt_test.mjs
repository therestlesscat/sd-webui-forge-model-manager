// An image rated PG whose prompt asks for something explicit is not PG - and
// the page takes the server's word for it.
//
// The Civitai Browser used to judge the images it was sent itself, with a
// copy of nsfw.py's rule in common.mjs and the words fetched to feed it. Every
// image it shows passes through the server, which now stamps its level on it
// (nsfw.stamp_levels(); the rule itself is tested in nsfw_prompt_test.py). What
// is checked here is that the page reads the stamp, in the places it matters:
// a card passes over a flagged image as over any unsafe one, and the gallery
// hides it with NSFW hidden and badges it "X · prompt" when shown. The words
// are made up.
import { ROOT, browserGalleryAnswer, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();

// Rated PG by Civitai; the server says X, because of the prompt.
const flagged = { id: 1, url: 'https://example.invalid/flagged.jpeg', nsfwLevel: 1, browsingLevel: 1,
                  mm_level: 8, mm_level_from_prompt: true,
                  meta: { prompt: 'a zorp by the sea', steps: 20, sampler: 'Euler', cfgScale: 7 } };
const clean = { id: 2, url: 'https://example.invalid/clean.jpeg', nsfwLevel: 1, browsingLevel: 1,
                mm_level: 1, mm_level_from_prompt: false,
                meta: { prompt: 'a lighthouse by the sea', steps: 20, sampler: 'Euler', cfgScale: 7 } };
const asked = [];

globalThis.fetch = async (url) => {
    const href = String(url);
    asked.push(href);
    if (href.includes('/images')) {
        return { ok: true, json: async () => browserGalleryAnswer(href, [flagged, clean]) };
    }
    if (href.includes('/model-manager/civitai/models')) {
        return { ok: true, json: async () => ({ success: true, nextCursor: null, pageSize: 20,
            models: [{ id: 7, name: 'A Model', type: 'Checkpoint', stats: {}, creator: {},
                       modelVersions: [{ id: 70, images: [flagged, clean], files: [] }] }] }) };
    }
    return { ok: true, json: async () => ({ success: true }) };
};

const shared = await import(`file:///${ROOT}/javascript/shared/nsfw.mjs`);
await import(`file:///${ROOT}/javascript/civitai_browser.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));

// ---------------------------------------------------- the server's verdict
check('an image\'s level is the one the server stamped', shared.nsfwImageLevel(flagged), 8);
check('whatever Civitai rated it', flagged.browsingLevel, 1);
check('an image with no stamp is Unknown - hidden - not judged here on less',
      [shared.nsfwImageLevel({ browsingLevel: 1 }), shared.isImageSafe({ browsingLevel: 1 })], [64, false]);

// ------------------------------------------------------------------ a card
const $ = (id) => document.getElementById(id);
$('cb_nsfw').checked = false;
$('cb_status').textContent = '';
window.cbSearch();
await waitFor('the grid', () => $('cb_status').textContent.startsWith('Showing'));
check('a card passes over a PG image whose prompt is explicit, for the next safe one',
      document.querySelector('#cb_grid .model-card img')?.getAttribute('src'),
      'https://example.invalid/clean.jpeg');

// --------------------------------------------------------------- the gallery
window.cbOpenModel(0);
await waitFor('the gallery', () => document.querySelectorAll('#cb_images .mm-image-card').length > 0);
const shown = () => Array.from(document.querySelectorAll('#cb_images .mm-image-card img'))
    .map((img) => (img.getAttribute('data-src') || img.getAttribute('src') || '').split('/').pop());
check('with NSFW hidden, the gallery leaves it out', shown(), ['clean.jpeg']);
await window.cbToggleShowAllImages(true);
check('shown, it is badged for why', document.querySelector('#cb_images .mm-nsfw-badge')?.textContent,
      'X · prompt');

check('and the page never asks for the words: it does not judge',
      asked.some((u) => u.includes('nsfw-prompt-words')), false);

done();

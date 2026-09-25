// An image rated PG whose prompt asks for something explicit is not PG - in
// the browser as on the server.
//
// The Civitai Browser judges the images Civitai sends it itself, with
// nsfwImageLevel() in shared/common.mjs, so it must reach the verdict the
// server's image_level() does: the same prompt cases as the server's test
// (tests/nsfw_prompt_cases.json) are checked here. Then the places it is
// used: a card passes over a flagged image as over any unsafe one, and the
// gallery hides it with NSFW hidden and badges it "X · prompt" when shown.
// The words are made up.
import { readFileSync } from 'node:fs';
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();
const CASES = JSON.parse(readFileSync(`${ROOT}/tests/nsfw_prompt_cases.json`, 'utf8'));

const flagged = { id: 1, url: 'https://example.invalid/flagged.jpeg', nsfwLevel: 1,
                  meta: { prompt: 'a zorp by the sea', steps: 20, sampler: 'Euler', cfgScale: 7 } };
const clean = { id: 2, url: 'https://example.invalid/clean.jpeg', nsfwLevel: 1,
                meta: { prompt: 'a lighthouse by the sea', steps: 20, sampler: 'Euler', cfgScale: 7 } };
let wordsAsked = 0;

globalThis.fetch = async (url) => {
    const href = String(url);
    if (href.includes('/model-manager/nsfw-prompt-words')) {
        wordsAsked += 1;
        return { ok: true, json: async () => ({ success: true, words: CASES.words }) };
    }
    if (href.includes('/images')) {
        return { ok: true, json: async () => ({ success: true, images: [flagged, clean],
            nextCursor: null }) };
    }
    if (href.includes('/model-manager/civitai/models')) {
        return { ok: true, json: async () => ({ success: true, nextCursor: null, pageSize: 20,
            models: [{ id: 7, name: 'A Model', type: 'Checkpoint', stats: {}, creator: {},
                       modelVersions: [{ id: 70, images: [flagged, clean], files: [] }] }] }) };
    }
    return { ok: true, json: async () => ({ success: true }) };
};

const shared = await import(`file:///${ROOT}/javascript/shared/common.mjs`);
await import(`file:///${ROOT}/javascript/civitai_browser.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));

// ------------------------------------------------ the rule, as the server's
await shared.loadNsfwPromptWords();
for (const c of CASES.cases) check(c.why, shared.nsfwImageLevel(c.image), c.level);
check('the words are asked for once, however many callers', (await shared.loadNsfwPromptWords(), wordsAsked), 1);

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
window.cbToggleShowAllImages(true);
check('shown, it is badged for why', document.querySelector('#cb_images .mm-nsfw-badge')?.textContent,
      'X · prompt');

done();

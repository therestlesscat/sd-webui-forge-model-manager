// Civitai content is written by strangers, and this page runs as the WebUI.
//
// Prompts, trigger words, tags, resource names and model descriptions all come
// from whoever uploaded them, and the page that shows them has the WebUI's own
// origin - it can call any WebUI endpoint, including this extension's file
// delete. So each place a hostile value lands is checked here with the kind of
// value that used to get through:
//
//   - a quote, which closed an attribute escapeHtml had left open, and added
//     an event handler of its own
//   - ${...}, which ran inside a Copy button's template literal
//   - raw markup in a resource's type, which went into every image card
//   - a description carrying script, handlers and javascript: links
//
// linkedom does not run inline handlers, so the checks are on what the markup
// *is* rather than on whether something fired: no hostile value may end up in
// an event attribute, and what is copied must be the text itself.
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

const MARK = '__pwned';
const QUOTE_BREAKOUT = `nice girl" onmouseover="window.${MARK}=1" x="`;
const TEMPLATE_PAYLOAD = 'a cat ${window.' + MARK + '=1} sitting';
const TAG_PAYLOAD = `<img src=x onerror="window.${MARK}=1">`;
const WORD_PAYLOAD = `it's" onmouseover="window.${MARK}=1`;
const DESCRIPTION = `<p>Hello <b>there</b></p>`
    + `<script>window.${MARK}=1</script>`
    + `<img src="x" onerror="window.${MARK}=1">`
    + `<a href="javascript:window.${MARK}=1">click</a>`
    + `<a href="https://civitai.com/models/1" onclick="window.${MARK}=1">fine</a>`
    + `<iframe src="https://example.invalid"></iframe>`
    + `<style>body{display:none}</style>`;

const MODEL = {
    id: 5001, model_id: 4001, name: 'A Model', display_name: 'A Model',
    version_name: 'v1', base_model: 'SDXL 1.0', model_type: 'LORA',
    file_path: 'C:/models/a.safetensors', file_name: 'a.safetensors',
    file_size: 1, nsfw_level: 1, has_civitai_data: true, local_version_count: 1,
    trained_words: [WORD_PAYLOAD], tags: [],
};

const IMAGES = [
    { id: 1, url: 'https://example.invalid/1.jpeg', browsingLevel: 1,
      meta: { prompt: QUOTE_BREAKOUT, steps: 20, sampler: 'Euler', cfgScale: 7,
              resources: [{ type: TAG_PAYLOAD, name: 'n', weight: TAG_PAYLOAD }] } },
    { id: 2, url: 'https://example.invalid/2.jpeg', browsingLevel: 1,
      meta: { prompt: TEMPLATE_PAYLOAD, steps: 20, sampler: 'Euler', cfgScale: 7 } },
];

globalThis.fetch = async (url) => {
    const href = String(url);
    if (href.includes('/ui-options')) {
        return { ok: true, json: async () => ({ success: true, samplers: [], schedulers: [],
            has_api_key: true, image_browsing: 'continuous' }) };
    }
    if (href.includes('/models/details')) {
        return { ok: true, json: async () => ({ success: true, model: {
            ...MODEL, images: IMAGES, civitai_model: { description: DESCRIPTION },
            images_state: { version_id: 5001, total_count: 2, hidden_nsfw: 0,
                            hidden_promptless: 0, hide_nsfw_images: false,
                            hide_promptless_images: false } } }) };
    }
    if (href.includes('/models/versions')) {
        return { ok: true, json: async () => ({ success: true, versions: [MODEL] }) };
    }
    if (href.includes('/model-manager/models')) {
        return { ok: true, json: async () => ({ success: true, total: 1, page: 1,
            page_size: 10, models: [MODEL] }) };
    }
    return { ok: true, json: async () => ({ success: true }) };
};

const copied = [];
Object.defineProperty(globalThis, 'navigator', { configurable: true,
    value: { clipboard: { writeText: (text) => { copied.push(text); return Promise.resolve(); } } } });

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));
document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the grid', () => document.querySelectorAll('#mm_grid .model-card').length > 0);
await window.mmSelectModel(0);
await waitFor('the gallery', () => document.querySelectorAll('.mm-image-card').length === 2);
await waitFor('the description', () => document.querySelector('.mm-description'));

// --- nothing hostile reached an event attribute ------------------------------
const planted = [];
for (const el of document.querySelectorAll('*')) {
    for (const attr of Array.from(el.attributes)) {
        if (attr.name.startsWith('on') && attr.value.includes(MARK)) {
            planted.push(`<${el.tagName.toLowerCase()} ${attr.name}>`);
        }
    }
}
check('no hostile value ends up in an event handler anywhere on the page', planted, []);

const prompt = document.querySelector('.mm-prompt-text');
check('a quote in a prompt stays inside its attribute', prompt?.hasAttribute('onmouseover'), false);
check('and the prompt still reads as written', prompt?.getAttribute('title'), QUOTE_BREAKOUT);

// --- resource chips, on every card --------------------------------------------
const chip = document.querySelector('.mm-resource');
check('markup in a resource type is shown as text, not built',
      chip?.querySelectorAll('img').length, 0);
check('the type reads literally', chip?.querySelector('.mm-resource-type')?.textContent, TAG_PAYLOAD);

// --- copying ------------------------------------------------------------------
const copyButtons = Array.from(document.querySelectorAll('button[data-copy]'));
check('the Copy Prompt buttons carry their text as data', copyButtons.length >= 2, true);
check('and no copy button carries it as code',
      document.querySelectorAll('[onclick*="clipboard"]').length, 0);

const templateButton = copyButtons.find((b) => b.getAttribute('data-copy') === TEMPLATE_PAYLOAD);
check('a prompt with ${...} in it is stored as it was written', !!templateButton, true);
templateButton?.dispatchEvent(new window.Event('click', { bubbles: true }));
check('and copied as text, not run', copied.pop(), TEMPLATE_PAYLOAD);
check('the page was not touched by it', (globalThis[MARK] ?? window[MARK]) === 1, false);

const word = document.querySelector('.trigger-word');
check('a trigger word with quotes in it is data', word?.getAttribute('data-copy'), WORD_PAYLOAD);
word?.dispatchEvent(new window.Event('click', { bubbles: true }));
check('and copies exactly', copied.pop(), WORD_PAYLOAD);

// --- the description ------------------------------------------------------------
const description = document.querySelector('.mm-description');
check('formatting survives', !!description.querySelector('p b'), true);
check('script does not', description.querySelectorAll('script').length, 0);
check('nor style', description.querySelectorAll('style').length, 0);
check('nor frames', description.querySelectorAll('iframe').length, 0);
const pictures = Array.from(description.querySelectorAll('img'));
check('an image keeps its picture but loses its handler',
      pictures.every((img) => !img.hasAttribute('onerror')), true);
check('and its source is an absolute https URL',
      pictures.every((img) => (img.getAttribute('src') || '').startsWith('https://')), true);
const links = Array.from(description.querySelectorAll('a'));
check('a javascript: link loses its target',
      links.filter((a) => (a.getAttribute('href') || '').startsWith('javascript')).length, 0);
check('an ordinary link keeps it', links.some((a) => a.getAttribute('href') === 'https://civitai.com/models/1'), true);
check('but not its handler', links.every((a) => !a.hasAttribute('onclick')), true);
check('and opens somewhere else, without a way back', links.every((a) => a.getAttribute('rel') === 'noopener noreferrer'), true);

// --- opening an image -------------------------------------------------------------
const media = document.querySelector('.mm-image-card img[data-open-url]');
check('an image opens from data, not from a handler', !!media && !media.hasAttribute('onclick'), true);

done();

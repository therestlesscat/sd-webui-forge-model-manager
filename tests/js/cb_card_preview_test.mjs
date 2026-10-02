// The Civitai Browser's card preview, for the settings window: its own cards,
// from the results it already shows when there are enough, and otherwise
// exactly as many models from Civitai as the preview's one row holds - every
// model asked for there is a request Civitai counts.
// (The window's side - how many fit, never a second row - is in
// settings_window_test.mjs.)
import { ROOT, checker, mountTab } from './harness.mjs';
const { call, ready } = await import(`file:///${ROOT}/javascript/shared/calls.mjs`);

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();

const model = (id) => ({ id, name: `Model ${id}`, type: 'Checkpoint', stats: {}, creator: {},
                         modelVersions: [{ id: id * 10, images: [], files: [] }] });
const searches = [];

globalThis.fetch = async (url) => {
    const href = String(url);
    if (href.includes('/model-manager/civitai/models')) {
        const limit = Number(new URL(href, 'http://webui').searchParams.get('limit')) || 5;
        searches.push(limit);
        return { ok: true, json: async () => ({ success: true, nextCursor: null, pageSize: limit,
            models: Array.from({ length: limit }, (_, i) => model(i + 1)) }) };
    }
    return { ok: true, json: async () => ({ success: true }) };
};

await import(`file:///${ROOT}/javascript/civitai_browser.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));
check('the tab offers the settings window a preview of its cards', ready('cardPreview.model_manager_civitai_card_size'), true);
const preview = (count) => call('cardPreview.model_manager_civitai_card_size', count);

const cards = (html) => (html.match(/class="model-card[ "]/g) || []).length;
let html = await preview(3);
check('before any search, it asks Civitai for exactly as many as the row holds', searches, [3]);
check('and draws them as this tab\'s cards', cards(html), 3);
html = await preview(2);
check('fewer needs nothing more from Civitai', [searches, cards(html)], [[3], 2]);

searches.length = 0;
document.getElementById('cb_status').textContent = '';
window.cbSearch();
await waitFor('the grid', () => document.getElementById('cb_status').textContent.startsWith('Showing'));
searches.length = 0;
html = await preview(4);
check('with a page of results shown, it draws from them and asks for nothing', [searches, cards(html)], [[], 4]);

done();

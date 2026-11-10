// The Civitai Browser's details show Civitai's answer as text (S2): the
// Model ID, Version ID, Type and Base Model cells put it into markup as it
// came, and its counts went through formatNumber, which passed a value that
// was not a number through as it was. Civitai sends numbers and fixed names
// there today; the cells no longer rely on it.
//
// A marker element in a value shows a fault: drawn as markup it becomes an
// element; escaped, it reads as its characters. Nothing in it runs.
import { browserGalleryAnswer, checker, mountTab, openTab, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();

const MARKER = '<i data-mm-marker></i>';
const thrown = [];
process.on('unhandledRejection', (e) => thrown.push(String(e?.message || e)));

const MODEL = {
    id: `7 ${MARKER}`, name: 'Marked', type: `LORA ${MARKER}`, creator: { username: 'someone' },
    stats: { downloadCount: `5 ${MARKER}`, favoriteCount: `6 ${MARKER}`, commentCount: `7 ${MARKER}` },
    owned_locally: false, listed_locally: false, owned_versions: [],
    modelVersions: [{ id: `70 ${MARKER}`, name: 'v1', baseModel: `SDXL ${MARKER}`, images: [], paid_access: null,
                      owned_locally: false, owned_files: [],
                      files: [{ id: 71, name: 'm.safetensors', sizeKB: 1024, primary: true }] }],
};

globalThis.fetch = async (url) => {
    const href = String(url);
    const answer = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/ui-options')) return answer({ success: true, webui_short_name: 'Neo' });
    if (href.includes('/civitai/owned')) return answer({ success: true, models: {}, versions: {} });
    if (href.includes('/civitai/download/progress')) return answer({ success: true, downloads: [] });
    if (href.includes('/versions/') || href.includes('/images')) return answer(browserGalleryAnswer(href, []));
    if (/\/civitai\/models\/\d+/.test(href)) return answer({ success: true, model: structuredClone(MODEL) });
    return answer({ success: true });
};

window.mmTiming = { poll: 60 };
await startTab('civitaiBrowser');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const details = () => document.getElementById('cb_details');
const row = (label) => Array.from(details()?.querySelectorAll('.detail-table tr') || [])
    .find((tr) => tr.querySelector('td')?.textContent.trim() === label)?.querySelectorAll('td')[1]?.textContent.trim();

await openTab('civitaiBrowser', 'showModel', 'model:7');
await waitFor('the details', () => details()?.textContent.includes('Marked') && row('Type') !== undefined);
// The last thing the details draw: the image count, once the gallery has answered.
await waitFor('the image count', () => row('Images') !== undefined && row('Images') !== '...');

check('nothing went wrong while the details drew', thrown, []);
check('nothing in the details is drawn as markup', details().querySelectorAll('[data-mm-marker]').length, 0);
check('ids that are not numbers read Unknown', [row('Model ID'), row('Version ID')], ['Unknown', 'Unknown']);
check('the type and base model read as written', [row('Type'), row('Base Model')],
      [`LORA ${MARKER}`, `SDXL ${MARKER}`]);
check('counts that are not numbers read 0',
      [row('Downloads'), row('Favorites'), row('Comments')], ['0', '0', '0']);

done();

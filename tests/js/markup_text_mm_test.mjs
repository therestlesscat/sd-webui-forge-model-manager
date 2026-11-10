// The Model Manager's details panel shows what the library stored as text,
// whatever characters it holds (S2). A record file beside a model - a
// .civitai.info or another tool's - is stored as it says when Civitai knows
// neither the file nor its model (_identify_by_sidecar), and the panel put its
// base model and its licence's commercial use into markup as they were; a
// remote version's download count, through formatNumber, the same.
//
// A marker element in a value shows a fault: drawn as markup it becomes an
// element; escaped, it reads as its characters. Nothing in it runs.
import { act, checker, mountTab, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

const MARKER = '<i data-mm-marker></i>';
const markers = () => document.getElementById('mm_details').querySelectorAll('[data-mm-marker]').length;

const MODEL = {
    id: 5001, model_id: 4001, name: 'A Model', display_name: 'A Model',
    version_name: 'v1', base_model: `SDXL ${MARKER}`, model_type: 'LORA', civitai_type: 'LORA',
    file_path: 'C:/models/a.safetensors', file_name: 'a.safetensors',
    file_size: 1, nsfw_level: 1, has_civitai_data: true, local_version_count: 1,
    trained_words: [], tags: [], download_count: `12 ${MARKER}`,
};
let model = MODEL;
let commercial = `{Image,${MARKER}}`;

globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/ui-options')) return reply({ success: true, samplers: [], schedulers: [], has_api_key: true });
    if (href.includes('/models/versions')) {
        return reply({ success: true, versions: [model], versions_synced_at: '2026-09-01T10:00:00',
            civitai_versions: [
                { id: 5002, name: 'v2', baseModel: 'SDXL 1.0', publishedAt: '2026-02-01', local: false,
                  files: [{ id: 9002, name: 'v2.safetensors', sizeKB: 10, type: 'Model', primary: true }] },
                { id: 5001, name: 'v1', baseModel: 'SDXL 1.0', publishedAt: '2026-01-01', local: true, files: [] }] });
    }
    if (href.includes('/models/details')) {
        return reply({ success: true, model: { images: [],
            civitai_model: { description: '<p>About it</p>', allow_commercial_use: commercial,
                             allow_derivatives: true, allow_different_license: false } } });
    }
    if (href.includes('/model-manager/models')) {
        // The licence is the grid's: the panel draws it from the model's entry.
        return reply({ success: true, total: 1, page: 1, page_size: 10, models: [{ ...model,
            civitai_model: { allow_commercial_use: commercial, allow_derivatives: true, allow_different_license: false } }] });
    }
    return reply({ success: true });
};

await startTab('modelManager');
document.dispatchEvent(new window.Event('DOMContentLoaded'));
document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the grid', () => document.querySelectorAll('#mm_grid .model-card').length > 0);

const row = (label) => Array.from(document.querySelectorAll('#mm_details .detail-table tr'))
    .find((tr) => tr.querySelector('td')?.textContent.trim() === label)?.querySelectorAll('td')[1]?.textContent.trim();
const commercialRow = () => Array.from(document.querySelectorAll('#mm_details .detail-table td'))
    .find((td) => td.textContent.trim().startsWith('Commercial:'))?.textContent.trim();
async function open() {
    // Loaded again, so the grid's entry carries the licence as it now stands;
    // the grid and the panel emptied, so each wait is for the new one.
    document.getElementById('mm_details').innerHTML = '';
    document.getElementById('mm_grid').innerHTML = '';
    document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
    await waitFor('the grid again', () => document.querySelectorAll('#mm_grid .model-card').length > 0);
    // What drawing the panel threw, if it did: a check, not the suite's end.
    try {
        await act('modelManager.selectModel', { index: 0 });
    } catch (e) {
        return e.message;
    }
    await waitFor('the details', () => !!commercialRow());
    return null;
}

// ------------------------------------------------- the details panel
await open();
check('nothing the record said is drawn as markup', markers(), 0);
check('its base model reads as written', row('Base Model'), `SDXL ${MARKER}`);
check('a commercial use the page has no words for reads as written',
      commercialRow(), `Commercial: Sell generated images, ${MARKER}`);

// Guard: the five known values still turn into words, and a value with & in
// it shows once, never as &amp;.
commercial = '{Image,R&D}';
await open();
check('known values become words; one holding & reads as written, once',
      commercialRow(), 'Commercial: Sell generated images, R&D');
commercial = 'Sell';
await open();
check('a single known value too', commercialRow(), 'Commercial: Sell model allowed');

// Hardening: the column is text, so no library sends anything else; a value
// that is not text no longer stops the panel from drawing.
commercial = 3;
check('a commercial use that is not text does not stop the panel', await open(), null);
check('it is drawn, as itself', commercialRow(), 'Commercial: 3');

// Ids that are not numbers read Unknown, never null.
model = { ...MODEL, model_id: `4001 ${MARKER}`, id: `5001 ${MARKER}` };
commercial = 'None';
await open();
check('a model id and a version id that are not numbers read Unknown',
      [row('Model ID'), row('Version ID')], ['Unknown', 'Unknown']);
check('and draws nothing as markup', markers(), 0);

// ------------------------------------------------- a version not downloaded
model = MODEL;
await open();
const remote = Array.from(document.querySelectorAll('#mm_details .mm-version-pill'))
    .findIndex((pill) => pill.textContent.trim().startsWith('v2'));
check('the model lists a version not downloaded', remote >= 0, true);
await act('modelManager.selectPill', { index: remote });
await waitFor('the version not downloaded', () => row('Downloads') !== undefined);
check('its download count, not a number, says 0', row('Downloads'), '0');
check('and nothing in its view is drawn as markup', markers(), 0);

done();

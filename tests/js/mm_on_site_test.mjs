// Versions Civitai allows only for generating on its site, in the Model
// Manager (#229): its panel reads what the last sync stored - each version's
// on_site_only, in the versions answer - and asks Civitai nothing. A version
// not downloaded that is on-site only shows ☁ on its pill, says why, and
// picked, its Download is disabled, saying why. One not known is not marked.
// The server's side: version_records_test.py.
import { act, checker, mountTab, press, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

const ON_SITE = 'The creator allows this version only for generating on Civitai.';
const local = {
    id: 701, model_id: 7001, name: 'A Model', display_name: 'A Model', version_name: 'v1',
    base_model: 'SDXL 1.0', model_type: 'LORA', civitai_type: 'LORA', file_path: 'C:/models/v1.safetensors',
    file_name: 'v1.safetensors', file_size: 1, nsfw_level: 1, has_civitai_data: true, local_version_count: 1,
    trained_words: [], tags: [], creator: 'someone', rating: 4.5, thumbs_up: 9, thumbs_down: 1, download_count: 12,
};
const file = (id) => [{ id, name: `f${id}.safetensors`, sizeKB: 2048, type: 'Model', primary: true }];
const listed = [
    { id: 704, name: 'v4', baseModel: 'SDXL 1.0', files: file(7040), local: false, paid_access: null, on_site_only: null },
    { id: 703, name: 'v3', baseModel: 'SDXL 1.0', files: file(7030), local: false, paid_access: null, on_site_only: true },
    { id: 702, name: 'v2', baseModel: 'SDXL 1.0', files: file(7020), local: false,
      paid_access: { permanent: true, ends_at: null, owned: false }, on_site_only: false },
    { id: 701, name: 'v1', baseModel: 'SDXL 1.0', files: file(7010), local: true, paid_access: null, on_site_only: false },
];
const asked = [];
globalThis.fetch = async (url) => {
    const href = String(url);
    asked.push(href);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/civitai/download/progress')) return reply({ success: true, downloads: [] });
    if (href.includes('/model-manager/models/versions')) {
        return reply({ success: true, versions: [local], civitai_versions: structuredClone(listed),
                       versions_synced_at: '2026-10-16T10:00:00' });
    }
    if (href.includes('/model-manager/models/details')) {
        return reply({ success: true, model: { images: [], civitai_model: { description: '' } } });
    }
    if (href.includes('/model-manager/models')) {
        return reply({ success: true, total: 1, page: 1, page_size: 20, models: [local] });
    }
    return reply({ success: true });
};

await startTab('modelManager');
document.dispatchEvent(new window.Event('DOMContentLoaded'));
document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the grid', () => document.querySelectorAll('#mm_grid .model-card').length > 0);

const details = () => document.getElementById('mm_details');
const pills = () => Array.from(details()?.querySelectorAll('.mm-version-pill') || []);
const pill = (name) => pills().find((p) => p.textContent.trim().startsWith(name));
const onSiteButton = () => Array.from(details()?.querySelectorAll('button') || [])
    .find((b) => b.textContent.trim() === 'On-site only');
const download = () => details()?.querySelector('[data-action="modelManager.downloadRemote"], [data-download-version]');

await act('modelManager.selectModel', { index: 0 });
await waitFor('the pills', () => pills().length === 4);
check('the stored answer marks the on-site-only version with ☁; one not known, nothing',
      pills().map((p) => p.textContent.trim()), ['v4', 'v3 \u2601\uFE0E', 'v2 ⬥', 'v1 ✓']);
check('and its tooltip says why', pill('v3')?.title.includes('On-site only: the creator allows'), true);
press(pill('v3'));
await waitFor('v3 shown', () => details()?.textContent.includes('v3'));
await new Promise((resolve) => setTimeout(resolve, 30));
check('picked, its Download reads On-site only, disabled, saying why',
      [onSiteButton()?.disabled, onSiteButton()?.title.startsWith(ON_SITE), Boolean(download())], [true, true, false]);
press(pill('v4'));
await new Promise((resolve) => setTimeout(resolve, 30));
check('one not known offers Download as today', [Boolean(onSiteButton()), Boolean(download())], [false, true]);
check('and nothing asked Civitai: no usage request', asked.filter((u) => u.includes('/civitai/usage')), []);

done();

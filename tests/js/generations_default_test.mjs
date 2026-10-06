// The Generations tab opens as its own setting says: it followed the Model
// Manager's image gallery setting. Here the gallery's hides explicit images
// and the tab's shows them; the tab's first page must ask for them shown.
import { ROOT, checker, mountTab, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
const { check, waitFor, done } = checker();

const browsed = [];
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/model-manager/ui-options')) {
        return reply({ success: true, samplers: [], schedulers: [], has_api_key: true,
                       gallery_hide_nsfw: true, generations_hide_nsfw: false, generations_enabled: true });
    }
    if (href.includes('/model-manager/generations/browse')) {
        browsed.push(new URL(href, 'http://webui').searchParams.get('hide_nsfw_images'));
        return reply({ success: true, tiles: [], groups: [], more: false,
                       state: { total: 0, filtered: 0, hidden_nsfw: 0, nsfw_count: 0 } });
    }
    return reply({ success: true });
};

await startTab('generations');
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await waitFor('the first page', () => browsed.length);
check('the Generations tab asks for its explicit images shown, as its own setting says',
      browsed[0], 'false');

done();

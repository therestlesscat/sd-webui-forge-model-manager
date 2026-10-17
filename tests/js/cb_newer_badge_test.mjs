// The New version badge on the Civitai Browser's cards (#218): an Owned model
// whose search answer lists versions before every one held here. The server
// names them (`newer_versions`, browser_api_test.py); the card draws the
// badge the Model Manager's cards draw (newer_badge_test.mjs), and adds "on-site
// only" from the page's own marks, which the server does not know of here.
import { act, checker, mountTab, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();

const version = (id, name, extra = {}) => ({ id, name, baseModel: 'SDXL 1.0', images: [], files: [], ...extra });
const newer = (id, name, extra = {}) => ({ id, name, base_model: 'SDXL 1.0', paid: null, on_site_only: null, ...extra });
const MODELS = [
    // Owned, two newer versions, the newest marked on-site only by the page.
    { id: 1, name: 'Owned, newer', type: 'LORA', stats: {}, creator: {}, owned_locally: true, owned_versions: [12],
      modelVersions: [version(10, 'v3', { on_site_only: true }), version(11, 'v2'), version(12, 'v1')],
      newer_versions: [newer(10, 'v3'), newer(11, 'v2', { paid: 'Paid' })] },
    // Owned, the newest held.
    { id: 2, name: 'Owned, newest', type: 'LORA', stats: {}, creator: {}, owned_locally: true, owned_versions: [20],
      modelVersions: [version(20, 'v2'), version(21, 'v1')], newer_versions: [] },
    // Not owned.
    { id: 3, name: 'Not owned', type: 'LORA', stats: {}, creator: {}, owned_locally: false, owned_versions: [],
      modelVersions: [version(30, 'v1')], newer_versions: [] },
];

globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/model-manager/civitai/models?') || href.endsWith('/model-manager/civitai/models')) {
        return reply({ success: true, models: MODELS, nextCursor: null, pageSize: 20,
                       cardWidth: 200, cardHeight: 280, filterStats: null });
    }
    return reply({ success: true });
};

await startTab('civitaiBrowser');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => document.getElementById(id);
act('civitaiBrowser.search');
await waitFor('the cards', () => $('cb_grid').querySelectorAll('.model-card').length === MODELS.length);

const badgeOf = (index) => $('cb_grid').querySelectorAll('.model-card')[index]?.querySelector('.badge.newer-badge');
check('an Owned card with newer versions says so, among its badges, as the Model Manager\'s do',
      [badgeOf(0)?.textContent, !!badgeOf(0)?.closest('.model-card')?.querySelector('.type-badge')],
      ['2 new versions', true]);
check('its tooltip names them, on-site only from the page\'s own marks, paid from the server; no list age here',
      badgeOf(0)?.getAttribute('title'),
      'Newer on Civitai than any version you have: v3 (SDXL 1.0, on-site only), v2 (SDXL 1.0, paid)');
check('an Owned card whose newest is held has none', badgeOf(1), null);
check('the type badge names itself in full, held over, as the Model Manager\'s does',
      $('cb_grid').querySelectorAll('.model-card')[0]?.querySelector('.badge.type-badge')?.getAttribute('title'), 'LORA');
check('nor a card not owned', badgeOf(2), null);

done();

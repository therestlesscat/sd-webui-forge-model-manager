// The shared card renderer draws what each tab's own renderer drew.
//
// Historical: it proves one change - both tabs' cards moved to
// renderModelCard() - by drawing the same models through the code before it
// (PARITY_COMMIT, default 0a9d4e0) and through the code now, and comparing
// the markup, whitespace aside. Run it by hand:
//
//     node tests/js/card_parity_test.mjs
//
// Two differences are meant, and are left out of the models here: the
// Browser's type badge is now escaped, and a name is cut before it is
// escaped. The Browser's Prev and Next are now shown disabled at the ends
// rather than left out; its page strip is compared with that allowed for.
import { execFileSync } from 'child_process';
import { mkdirSync, rmSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, '..', '..');
const [mode, tab] = process.argv.slice(2);

// ---------------------------------------------------------------- the models
const MM_MODELS = [
    { id: 1, civitai_model_id: 11, display_name: 'Plain Model', model_type: 'LORA', base_model: 'SDXL 1.0',
      preview_url: 'https://image.civitai.com/x/abc/original=true/1.jpeg', has_civitai_data: true,
      nsfw_level: 1, thumbs_up: 10, thumbs_down: 1, download_count: 1234, file_size: 1024 * 1024 * 50,
      local_version_count: 1, file_path: 'C:/m/1.safetensors' },
    { id: 2, civitai_model_id: 12, display_name: 'A name that is well over thirty characters long', model_type: 'Checkpoint',
      base_model: '', preview_url: 'https://image.civitai.com/x/abc/original=true/2.mp4', has_civitai_data: true,
      nsfw_level: 8, thumbs_up: 0, thumbs_down: 0, download_count: 0, file_size: 1024 * 1024 * 1024 * 6,
      local_version_count: 3, is_bookmarked: true, file_path: 'C:/m/2.safetensors' },
    { id: 3, civitai_model_id: null, display_name: 'Local only', model_type: 'VAE', preview_url: '',
      has_civitai_data: false, nsfw_level: 0, file_size: 3000, file_path: 'C:/m/3.safetensors' },
    { id: 4, civitai_model_id: 14, display_name: 'Level R', model_type: 'LORA', base_model: 'Pony',
      preview_url: 'https://image.civitai.com/x/abc/original=true/4.jpeg', has_civitai_data: true,
      nsfw_level: 4, thumbs_up: 2, thumbs_down: 0, download_count: 5, file_size: 10, file_path: 'C:/m/4.safetensors' },
    { id: 5, civitai_model_id: 15, display_name: 'Level PG-13 and XXX', model_type: 'LORA', base_model: 'Flux.1 D',
      preview_url: 'https://image.civitai.com/x/abc/original=true/5.jpeg', has_civitai_data: true,
      nsfw_level: 18, download_count: 1500000, file_size: 10, file_path: 'C:/m/5.safetensors' },
];
const image = (id, level, type = 'image') => ({ id, url: `https://image.civitai.com/x/abc/original=true/${id}.jpeg`,
                                                type, nsfwLevel: level, browsingLevel: level, mm_level: level });
const CB_MODELS = [
    { id: 21, name: 'Owned Checkpoint', type: 'Checkpoint', owned_locally: true, creator: {},
      stats: { downloadCount: 25000, thumbsUpCount: 900, thumbsDownCount: 3 },
      modelVersions: [{ id: 210, baseModel: 'SDXL 1.0', images: [image(1, 1)], files: [] }] },
    { id: 22, name: 'Paid, early access, and a name well past thirty characters', type: 'LORA', creator: {},
      stats: { downloadCount: 0 },
      modelVersions: [{ id: 220, baseModel: 'Illustrious', images: [image(2, 8), image(3, 1)], files: [],
                        paid_access: { permanent: false, ends_at: '2026-10-01T00:00:00Z' } }] },
    { id: 23, name: 'Paid for good', type: 'LORA', creator: {}, stats: {},
      modelVersions: [{ id: 230, images: [image(4, 1, 'video')], files: [], paid_access: { permanent: true } }] },
    { id: 24, name: 'No images', type: 'TextualInversion', creator: {}, stats: { downloadCount: 7 },
      modelVersions: [{ id: 240, baseModel: 'SD 1.5', images: [], files: [] }] },
];

// ------------------------------------------------ one tab's grid, from one tree
if (mode === 'dump') {
    const { ROOT, mountTab } = await import('./harness.mjs');
    const quiet = console.log;
    console.log = () => {};
    const file = tab === 'mm' ? 'tab_model_manager.py' : 'tab_civitai_browser.py';
    const { window, document } = mountTab(`model_manager/ui/${file}`);
    globalThis.fetch = async (url) => {
        const href = String(url);
        if (tab === 'mm' && href.includes('/model-manager/models') && !href.includes('/versions')) {
            return { ok: true, json: async () => ({ success: true, models: MM_MODELS, total: 60, page: 3,
                                                    page_size: 5, has_more: true }) };
        }
        if (tab === 'cb' && href.includes('/model-manager/civitai/models')) {
            return { ok: true, json: async () => ({ success: true, models: CB_MODELS, nextCursor: 'c2', pageSize: 4 }) };
        }
        return { ok: true, json: async () => ({ success: true }) };
    };
    await (await import('./harness.mjs')).startTab(tab === 'mm' ? 'modelManager' : 'civitaiBrowser');
    document.dispatchEvent(new window.Event('DOMContentLoaded'));
    const gridId = tab === 'mm' ? 'mm_grid' : 'cb_grid';
    if (tab === 'mm') {
        document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
    } else {
        document.getElementById('cb_nsfw').checked = false;
        window.cbSearch();
    }
    for (let i = 0; i < 100 && !document.querySelector(`#${gridId} .model-card`); i++) {
        await new Promise((r) => setTimeout(r, 50));
    }
    const grid = document.getElementById(gridId);
    quiet('@@' + JSON.stringify({
        cards: grid.querySelector('.model-grid-inner')?.innerHTML || '',
        pagination: grid.querySelector('.mm-pagination')?.outerHTML || '',
    }));
    process.exit(0);
}

// --------------------------------------------------------------- the comparison
const COMMIT = process.env.PARITY_COMMIT || '0a9d4e0';
const OLD = resolve(REPO, 'tests', 'work', 'card_parity_old');
rmSync(OLD, { recursive: true, force: true });
mkdirSync(OLD, { recursive: true });
const TAR = resolve(OLD, '..', 'card_parity_old.tar');
execFileSync('git', ['archive', '--format=tar', '-o', TAR, COMMIT], { cwd: REPO });
execFileSync('tar', ['-xf', TAR, '-C', OLD]);
rmSync(TAR, { force: true });

function dump(which, root) {
    const out = execFileSync(process.execPath, [fileURLToPath(import.meta.url), 'dump', which],
                             { env: { ...process.env, MM_ROOT: root.replace(/\\/g, '/') }, encoding: 'utf8' });
    return JSON.parse(out.split('\n').find((l) => l.startsWith('@@')).slice(2));
}

// Whitespace between tags, at the ends of a text, and within a class list, is
// not what a card is - a browser draws them alike.
const normal = (html) => html
    .replace(/\s+/g, ' ')
    .replace(/>\s+/g, '>')
    .replace(/\s+</g, '<')
    .replace(/class="([^"]*)"/g, (_, c) => `class="${c.trim().split(/\s+/).join(' ')}"`)
    .replace(/\s+>/g, '>')
    .trim();

const fails = [];
function same(label, a, b) {
    if (normal(a) !== normal(b)) {
        const x = normal(a), y = normal(b);
        let i = 0;
        while (i < x.length && x[i] === y[i]) i++;
        fails.push(`${label}\n     before ...${x.slice(Math.max(0, i - 80), i + 120)}\n     now    ...${y.slice(Math.max(0, i - 80), i + 120)}`);
    }
}

for (const which of ['mm', 'cb']) {
    const before = dump(which, OLD);
    const now = dump(which, REPO);
    if (!before.cards || !now.cards) fails.push(`${which}: no cards drawn (before ${before.cards.length}, now ${now.cards.length})`);
    same(`${which}: the cards are the same`, before.cards, now.cards);
    if (which === 'mm') {
        same('mm: the page strip is the same', before.pagination, now.pagination);
    } else {
        // The one meant change: on page 1, Prev is shown disabled, not left out.
        const shown = now.pagination.replace(/<button class="mm-btn mm-page-btn" onclick="window\.cbPrevPage\(\)"\s+disabled>\s*← Prev\s*<\/button>/, '');
        same('cb: the page strip is the same, but for a disabled Prev on page 1',
             before.pagination, shown);
    }
}
rmSync(OLD, { recursive: true, force: true });
console.log(fails.map((f) => 'FAIL ' + f).join('\n') || 'All checks passed.');
process.exit(fails.length ? 1 : 0);

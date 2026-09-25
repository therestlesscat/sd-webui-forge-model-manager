// The details panel's Type row says what the file is, read from the file.
//
// Civitai lists "Qwen-Image - GGUF" as a Checkpoint, and its local versions
// are a VAE and a text encoder. The row shows the file's own type, notes what
// Civitai calls it where that differs, says what decided it on hover - and
// follows the version picked, since versions of one model need not be alike.
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

const BASE = {
    model_id: 4001, name: 'Qwen-Image - GGUF', display_name: 'Qwen-Image - GGUF',
    base_model: 'Other', file_size: 1, nsfw_level: 1, has_civitai_data: true,
    local_version_count: 2, trained_words: [], tags: [], civitai_type: 'Checkpoint',
};
const VAE = { ...BASE, id: 2089517, version_name: 'VAE', file_type: 'VAE', model_type: 'VAE',
              identified_by: 'a vae_wan21 by its shapes',
              file_path: 'C:/models/VAE/qwen_image_vae.safetensors', file_name: 'qwen_image_vae.safetensors' };
const ENCODER = { ...BASE, id: 2089462, version_name: 'TE', file_type: 'Text Encoder',
                  model_type: 'Text Encoder', identified_by: 'a qwen25_7b by its shapes',
                  file_path: 'C:/models/text_encoder/qwen_2.5_vl_7b.safetensors',
                  file_name: 'qwen_2.5_vl_7b.safetensors' };

globalThis.fetch = async (url) => {
    const href = String(url);
    if (href.includes('/ui-options')) {
        return { ok: true, json: async () => ({ success: true, samplers: [], schedulers: [],
            has_api_key: true, image_browsing: 'continuous' }) };
    }
    if (href.includes('/models/details')) {
        return { ok: true, json: async () => ({ success: true, model: { ...VAE, images: [],
            images_state: { version_id: VAE.id, total_count: 0, hidden_nsfw: 0, hidden_promptless: 0 } } }) };
    }
    if (href.includes('/models/versions')) {
        return { ok: true, json: async () => ({ success: true, versions: [VAE, ENCODER] }) };
    }
    if (href.includes('/model-manager/models')) {
        return { ok: true, json: async () => ({ success: true, total: 1, page: 1, page_size: 20,
            models: [VAE] }) };
    }
    return { ok: true, json: async () => ({ success: true }) };
};

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));
document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the grid', () => document.querySelectorAll('#mm_grid .model-card').length > 0);

check('the card\'s badge is the file\'s type',
      document.querySelector('#mm_grid .type-badge')?.textContent, 'VAE');

await window.mmSelectModel(0);
await waitFor('the details', () => document.querySelector('.mm-type-cell'));
const cell = () => document.querySelector('.mm-type-cell');
check('the Type row gives the file\'s type, and what Civitai lists it as',
      cell().textContent.replace(/\s+/g, ' ').trim(), 'VAE (listed on Civitai as Checkpoint)');
check('with what decided it on hover', cell().getAttribute('title'),
      'Read from the file: a vae_wan21 by its shapes');

await waitFor('the version pills', () => document.querySelectorAll('.mm-version-pill').length === 2);
await window.mmSelectVersion(1);
check('picking the other version shows that file\'s type',
      cell().textContent.replace(/\s+/g, ' ').trim(), 'Text Encoder (listed on Civitai as Checkpoint)');
check('and what decided it', cell().getAttribute('title'), 'Read from the file: a qwen25_7b by its shapes');

done();

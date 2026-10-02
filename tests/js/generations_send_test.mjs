// The Generations tab sends with nothing but the shared code (#91). Send -
// Forge's VAE / Text Encoder control, the UI preset, the paste, the chips -
// lived in the Model Manager's script, and the Generations tab reached it
// through that tab: without its script loaded, nothing could be sent.
//
// Here the Generations tab is loaded alone. Its Send pastes the generation's
// infotext into the tab it was made in and presses paste, shows that tab,
// and leaves Forge's scheduler set; the Model Manager's script never loads.
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
const { check, waitFor, done } = checker();

// ------------------------------------------- Forge's generation tabs
document.body.insertAdjacentHTML('afterbegin', `
    <div id="tabs">
        <button id="tab_txt2img-button">txt2img</button>
        <button id="tab_img2img-button">img2img</button>
        <button id="tab_generations_tab-button" class="selected" aria-selected="true">Generations</button>
    </div>
    <div id="txt2img_prompt"><textarea></textarea></div>
    <div id="txt2img_tools"><button id="paste"></button></div>
    <div id="txt2img_scheduler"><input></div>
    <div id="img2img_prompt"><textarea></textarea></div>
    <div id="img2img_tools"><button id="paste"></button></div>`);
const pasted = { txt2img: 0, img2img: 0 };
for (const tab of ['txt2img', 'img2img']) {
    document.querySelector(`#${tab}_tools #paste`).addEventListener('click', () => { pasted[tab] += 1; });
}
const shown = [];
document.querySelectorAll('#tabs button').forEach((b) => b.addEventListener('click', () => shown.push(b.id)));

// ------------------------------------------------------------- the server
const INFOTEXT = 'a lighthouse at dusk\nSteps: 20, Sampler: Euler, Schedule type: Karras, Seed: 7';
const image = {
    id: 11, generation_id: 1, position: 0, seed: 7, width: 832, height: 1216,
    meta: { prompt: 'a lighthouse at dusk', steps: 20, sampler: 'Euler', 'Schedule type': 'Karras' },
    infotext: INFOTEXT, url: '/model-manager/generations/images/11/file', exists: true,
    mm_level: 1, mm_level_from_prompt: false, user_level: null, prompt_level: 1, loras: [],
};
const generation = { id: 1, mode: 'txt2img', created_at: '2026-10-02T10:00:00', image_count: 1 };
const asked = [];
globalThis.fetch = async (url) => {
    const href = String(url);
    asked.push(href);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/ui-options')) {
        return reply({ success: true, samplers: ['Euler', 'Euler a'], schedulers: ['Automatic', 'Karras'],
                       gallery_hide_nsfw: true, generations_hide_nsfw: true, generations_enabled: true });
    }
    if (href.includes('/generations/browse')) {
        return reply({ success: true, more: false,
                       tiles: [{ kind: 'generation', generation, matching_count: 1, images: [image], loras: [],
                                 level: 1, user_level: null }],
                       state: { total: 1, filtered: 1, hidden_nsfw: 0, nsfw_count: 0, hide_nsfw_images: true,
                                stored_generations: 1 },
                       scope: { count: 1 } });
    }
    if (href.includes('/send-plan')) return reply({ success: false });
    return reply({ success: true });
};

await import(`file:///${ROOT}/javascript/generations.mjs`);
const { ready } = await import(`file:///${ROOT}/javascript/shared/calls.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await waitFor('the grid', () => document.querySelectorAll('#gen_grid .gen-tile').length === 1);

// ------------------------------------------------------------------ Send
await window.genSend(0);
await waitFor('the paste', () => pasted.txt2img > 0);
check('the Model Manager\'s script is not loaded', ready('modelManager.sendImage'), false);
check('Send pastes the generation\'s infotext into the tab it was made in',
      document.querySelector('#txt2img_prompt textarea').value, INFOTEXT);
check('and presses that tab\'s paste, once', [pasted.txt2img, pasted.img2img], [1, 0]);
check('and shows the tab', shown, ['tab_txt2img-button']);
check('having asked how the generation was made', asked.some((href) => href.includes('/generations/1/send-plan')), true);

done();

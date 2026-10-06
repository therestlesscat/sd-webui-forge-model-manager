// The Generations tab sends with nothing but the shared code (#91). Send -
// Forge's VAE / Text Encoder control, the UI preset, the paste, the chips -
// lived in the Model Manager's script, and the Generations tab reached it
// through that tab: without its script loaded, nothing could be sent.
//
// Here the Generations tab is loaded alone. Its Send pastes the generation's
// infotext into the tab it was made in and presses paste, shows that tab,
// and leaves Forge's scheduler set; the Model Manager's script never loads.
import { ROOT, act, checker, mountTab, startTab } from './harness.mjs';

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

await startTab('generations');
const { ready } = await import(`file:///${ROOT}/javascript/shared/calls.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await waitFor('the grid', () => document.querySelectorAll('#gen_grid .gen-tile').length === 1);

// ------------------------------------------------------------------ Send
await act('generations.send', { tile: 0 });
await waitFor('the paste', () => pasted.txt2img > 0);
check('the Model Manager\'s script is not loaded', ready('modelManager.sendImage'), false);
check('Send pastes the generation\'s infotext into the tab it was made in',
      document.querySelector('#txt2img_prompt textarea').value, INFOTEXT);
check('and presses that tab\'s paste, once', [pasted.txt2img, pasted.img2img], [1, 0]);
check('and shows the tab', shown, ['tab_txt2img-button']);
check('having asked how the generation was made', asked.some((href) => href.includes('/generations/1/send-plan')), true);

// A LoRA the prompt names by its alias - as Forge writes it, "Alias from
// file" chosen - is pasted under its file's name, as a Civitai image's Send
// does: its chip names the file, and is lit only by a tag with that name.
// Image 1031's chip named the file, and its prompt the alias. Nor are its
// Lora hashes pasted: Forge's paste renames each LoRA they list to its own
// choice of name - the alias again (image 1006).
const ALIASED = 'a flower, <lora:training_6485327-20260725085836447:1>\n'
    + 'Steps: 20, Seed: 7, Lora hashes: "training_6485327-20260725085836447: 426e6c6522db", Version: neo';
Object.assign(image, {
    infotext: ALIASED,
    meta: { prompt: 'a flower, <lora:training_6485327-20260725085836447:1>', steps: 20,
            resources: [{ type: 'lora', name: 'training_6485327-20260725085836447', hash: '426e6c6522db', weight: 1 }] },
});
const fetchBefore = globalThis.fetch;
globalThis.fetch = async (url, ...rest) => (String(url).includes('/model-manager/image-resources')
    ? { ok: true, json: async () => ({ success: true, versions: {}, names: {},
        hashes: { '426e6c6522db': { version_id: 5, file_stem: 'Anime_Girl-Flower_ill_epoch_10', file_type: 'LORA' } } }) }
    : fetchBefore(url, ...rest));
await act('generations.send', { tile: 0 });
await waitFor('the second paste', () => pasted.txt2img > 1);
check('a LoRA its prompt names by alias is pasted under its file\'s name, weight kept, and no Lora hashes',
      document.querySelector('#txt2img_prompt textarea').value,
      'a flower, <lora:Anime_Girl-Flower_ill_epoch_10:1>\nSteps: 20, Seed: 7, Version: neo');
globalThis.fetch = fetchBefore;

done();

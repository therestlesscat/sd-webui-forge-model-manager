// Send with several checkpoints ticked (#400, shared/send.mjs's
// sendThenSeveral): the image is sent with the first, as made, and only once
// that send has landed in txt2img does several mode take them all. A send
// that fails, or stops for its checkpoint, has said why, and the mode is not
// entered; one that lands in img2img says the mode is txt2img's. Several
// mode refusing - its setting off, or not started in this page - is said.
// And each Send line says the tab it sends into, which the dialog ticks for.
import { checker, mountTab, sendLoaders, sharedModule, startServices } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
window.mmTiming = { poll: 20, pasteMax: 50, frame: 5 };
const { check, waitFor, done } = checker();

// Forge's generation tabs, and the hidden loader each takes a source by.
document.body.insertAdjacentHTML('afterbegin', `
    <div id="tabs">
        <button id="tab_txt2img-button">txt2img</button>
        <button id="tab_img2img-button">img2img</button>
        <button id="tab_generations_tab-button" class="selected" aria-selected="true">Generations</button>
    </div>
    <div id="img2img_modes"><button id="img2img_img2img_tab-button"></button></div>
    <div id="txt2img_prompt"><textarea></textarea></div>
    <div id="img2img_prompt"><textarea></textarea></div>`);
let loaderAnswer = () => ({ pasted: true });
const loaded = [];
sendLoaders(document, { onAsk: (tab, request) => loaded.push({ tab, ...request }),
                        answer: (tab, request) => loaderAnswer(tab, request) });

// The server: a generation's plan, as send.generation_plan answers it.
let plan = { success: true, preset: null, checkpoint: null, target: [], modules_missing: [] };
const planAsks = [];
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, status: 200, json: async () => structuredClone(body) });
    if (href.includes('/ui-options')) return reply({ success: true, samplers: [], schedulers: [] });
    if (href.includes('/send/plan')) {
        planAsks.push(Object.fromEntries(new URL(href, 'http://x').searchParams));
        return reply(plan);
    }
    return reply({ success: true, versions: {}, hashes: {}, other_files: {}, names: {}, embeddings: [] });
};
await startServices('core.mjs', 'calls.mjs', 'send.mjs');
const send = await sharedModule('send.mjs');
const calls = await sharedModule('calls.mjs');
// Several mode, stood in: what it is asked to hold, and what it answers.
const entered = [];
let enterAnswer = true;
const enter = async (args) => { entered.push(args); return enterAnswer; };
calls.provide('several.enter', enter);

const notices = () => [...document.querySelectorAll('.mm-notice')].map((n) => n.textContent.trim());
const clearNotices = () => document.querySelectorAll('.mm-notice').forEach((n) => n.remove());
const closeDialogs = () => document.querySelectorAll('#mm_meta_modal').forEach((n) => n.close());
const generation = (mode = 'txt2img') => send.generationResourcesLine({
    infotext: 'a lighthouse\nSteps: 20, Sampler: Euler a', mode, meta: { prompt: 'a lighthouse' },
    generationId: 1, imageId: 11 });
const NAMES = ['anime_v12.safetensors [a1]', 'real_v2.safetensors [b2]'];
const ENTERING = { source: { image: { kind: 'generation', generation: 1, image: 11, image_model: 81 } },
                   labels: { [NAMES[0]]: 'Anime Mix v12', [NAMES[1]]: 'Real v2' }, listParams: { generation: 1 } };

check('each Send line says the tab it sends into: a txt2img generation\'s txt2img, an img2img one\'s img2img',
      [generation('txt2img').tab, generation('img2img').tab], ['txt2img', 'img2img']);

// --------------------------------------------------------------- it lands
await generation().pickSeveral(NAMES, 81, ENTERING);
check('sent with the first ticked, as made: no usual settings asked with it',
      [planAsks.at(-1)?.use_checkpoint, planAsks.at(-1)?.usual, loaded.at(-1)?.tab], [NAMES[0], undefined, 'txt2img']);
check('landed in txt2img: several mode holds them all, with where they came from, their names and the list\'s',
      entered, [{ names: NAMES, ...ENTERING }]);
check('and nothing said', notices(), []);
entered.length = 0;
// Right after a send that landed: a Civitai image in a LoRA's gallery, its send stopped for its checkpoint -
// a gallery's send answers nothing either way, so the stop is told by no paste begun.
const image = { id: 7002, url: 'https://image.civitai.com/x/a.jpeg', meta: { prompt: 'a lighthouse', civitaiResources: [
    { type: 'checkpoint', modelVersionId: 8002, modelId: 81, name: 'A Checkpoint', modelVersionName: 'v1' }] } };
const civitai = send.gallerySendLine({ img: image, model: { id: 90, type: 'LORA', base_model: 'SDXL 1.0' },
                                       version: { id: 9002, base_model: 'SDXL 1.0', file_path: 'style.safetensors' } });
check('a Civitai image\'s Send line sends into txt2img', civitai?.tab, 'txt2img');
plan = { success: true, preset: null, checkpoint: null, target: [], modules_missing: [],
         checkpoint_problem: { reason: 'missing', name: NAMES[0] } };
await civitai.pickSeveral(NAMES, 81, ENTERING);
await new Promise((resolve) => setTimeout(resolve, 30));
check('a Civitai image\'s send stopped for its checkpoint, the Resources dialog open: several mode is not entered',
      [entered, Boolean(document.querySelector('.mm-resources-modal'))], [[], true]);
closeDialogs();
plan = { success: true, preset: null, checkpoint: null, target: [], modules_missing: [] };

// ------------------------------------------------------- it fails, it stops
entered.length = 0;
loaderAnswer = () => ({ error: 'the tab is busy' });
await generation().pickSeveral(NAMES, 81, ENTERING);
check('the send fails: it says so, and several mode is not entered',
      [entered, notices()], [[], ['Could not send: the tab is busy.']]);
clearNotices();
loaderAnswer = () => ({ pasted: true });
plan = { ...plan, checkpoint_missing: NAMES[0] };
await generation().pickSeveral(NAMES, 81, ENTERING);
await new Promise((resolve) => setTimeout(resolve, 30));
check('the send stops for its checkpoint, the Resources dialog open: several mode is not entered',
      [entered, Boolean(document.querySelector('.mm-resources-modal'))], [[], true]);
closeDialogs();
plan = { success: true, preset: null, checkpoint: null, target: [], modules_missing: [] };

// ----------------------------------------------------- it lands elsewhere
clearNotices();
await generation('img2img').pickSeveral(NAMES, 81, ENTERING);
check('it lands in img2img: several mode is not entered, and it says, last, that the mode is txt2img\'s',
      [entered, notices().at(-1)], [[], 'Sent with Anime Mix v12 into img2img: several checkpoints are queued from txt2img alone.']);

// ----------------------------------------------------- several mode refuses
clearNotices();
calls.withdraw('several.enter', enter);
await generation().pickSeveral(NAMES, 81, ENTERING);
check('several mode not started in this page: said, with what to do', notices(),
      ['Sent with Anime Mix v12. Queuing several checkpoints needs a reload of this page: the Queue was switched off '
       + 'and on in it.']);

done();

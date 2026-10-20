// The Generations tab sends with nothing but the shared code (#91). Send -
// Forge's VAE / Text Encoder control, the UI preset, the paste, the chips -
// lived in the Model Manager's script, and the Generations tab reached it
// through that tab: without its script loaded, nothing could be sent.
//
// Here the Generations tab is loaded alone. Its Send hands the generation to
// the tab's hidden button as its source (#302) - the server pastes its
// infotext, or sets its kept press back (#7), and says which - and shows the
// tab it was made in; the Model Manager's script never loads. What the server
// does with the source is send_text_test.py's and img2img_send_test.py's.
import { ROOT, act, checker, mountTab, sendLoaders, sharedModule, startTab } from './harness.mjs';

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
    <div id="img2img_tools"><button id="paste"></button></div>
    <div id="txt2img_hr-checkbox"><input type="checkbox" checked></div>`);
const pasted = { txt2img: 0, img2img: 0 };
const buttonPastes = { txt2img: 0, img2img: 0 };
for (const tab of ['txt2img', 'img2img']) {
    document.querySelector(`#${tab}_tools #paste`).addEventListener('click', () => { buttonPastes[tab] += 1; });
}
// What the server's button answers: a paste, unless a test says otherwise.
let loaderAnswer = () => ({ pasted: true });
let loaderDelay = 0;
const loaderAsked = [];
const timeline = [];
sendLoaders(document, { onAsk: (tab, request) => {
    loaderAsked.push({ tab, ...request });
    if (request.source !== undefined) pasted[tab] += 1;
    timeline.push(['answered', performance.now() + loaderDelay]);
}, answer: (tab, request) => loaderAnswer(tab, request), delay: () => loaderDelay,
   // A pasted source's text is the server's: the image's own, here.
   sourceText: () => image.infotext });
document.querySelector('#txt2img_hr-checkbox input').addEventListener('change',
    () => timeline.push(['hires off', performance.now()]));
const lastSource = () => [...loaderAsked].reverse().find((r) => r.source !== undefined)?.source;
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
// Send's plan for a generation (#302): nothing to set up, unless a section says otherwise.
const NO_PLAN = { success: true, inputs: false, preset: null, checkpoint: null, target: [], modules_missing: [] };
let planAnswer = NO_PLAN;
let tiles = [{ kind: 'generation', generation, matching_count: 1, images: [image], loras: [], level: 1, user_level: null }];
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
                       tiles,
                       state: { total: 1, filtered: 1, hidden_nsfw: 0, nsfw_count: 0, hide_nsfw_images: true,
                                stored_generations: 1 },
                       scope: { count: 1 } });
    }
    if (href.includes('/model-manager/send/plan')) return reply(planAnswer);
    return reply({ success: true });
};

await startTab('generations');
const { ready } = await import(`file:///${ROOT}/javascript/shared/calls.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await waitFor('the grid', () => document.querySelectorAll('#gen_grid .gen-tile').length === 1);

// ------------------------------------------------------------------ Send
// Where the page is asked to scroll: Send lands at the page's top, where the
// WebUI's header shows the checkpoint and modules it may have set - not at
// the scroll the Generations tab had (#263). Its tab bar is 120 px down here.
const scrolls = [];
let pageY = 5000;
Object.defineProperty(window, 'scrollY', { get: () => pageY, configurable: true });
window.scrollTo = (x, y) => { pageY = typeof x === 'object' ? x.top : y; scrolls.push(pageY); };
document.getElementById('tabs').getBoundingClientRect = () => ({ top: 120 - pageY, bottom: 160 - pageY, height: 40, width: 800 });
await act('generations.send', { tile: 0 });
await waitFor('the paste', () => pasted.txt2img > 0);
check('the Model Manager\'s script is not loaded', ready('modelManager.sendImage'), false);
check('Send hands the tab it was made in the generation and its image, as the source (#302)',
      lastSource(), { kind: 'generation', generation: 1, image: 11, renames: [] });
check('through that tab\'s hidden button, once, and not Forge\'s paste button',
      [pasted.txt2img, pasted.img2img, buttonPastes.txt2img], [1, 0, 0]);
check('and shows the tab', shown, ['tab_txt2img-button']);
await waitFor('the landing', () => scrolls.length > 1);
check('and lands at the page\'s top, the checkpoint and modules in view (#263): the tab bar, then 0',
      scrolls, [120, 0]);
check('having asked how the generation was made, on Send\'s one route',
      asked.some((href) => href.includes('/model-manager/send/plan') && href.includes('kind=generation')
                           && href.includes('generation=1')), true);

// A LoRA the prompt names by its alias - as Forge writes it, "Alias from
// file" chosen - is pasted under its file's name, as a Civitai image's Send
// does: its chip names the file, and is lit only by a tag with that name.
// Image 1031's chip named the file, and its prompt the alias. The page works
// out the rename from the chips and sends it with the source; the server
// applies it, and leaves the Lora hashes out (send_text_test.py, #302).
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
check('a LoRA its prompt names by alias: its rename to the file\'s name goes with the source',
      lastSource()?.renames, [{ from: 'training_6485327-20260725085836447', to: 'Anime_Girl-Flower_ill_epoch_10' }]);
globalThis.fetch = fetchBefore;

// ------------------------------------------ what follows the paste waits for it
// The scheduler and Hires fix are the loader's, in the paste's own event
// (#302): the page leaves Hires fix as the loader left it. What follows - the
// modules - waits for the answer, never a fixed time: 100 ms was shorter than
// every paste measured on Neo (58 of 58).
Object.assign(image, { infotext: INFOTEXT, meta: { prompt: 'a lighthouse at dusk', steps: 20 } });
const { whenSendSettled } = await sharedModule('send.mjs');
await whenSendSettled();                      // the last send's own steps done
loaderDelay = 400;
timeline.length = 0;
document.querySelector('#txt2img_hr-checkbox input').checked = true;
const started = performance.now();
await act('generations.send', { tile: 0 });
await whenSendSettled();
check('the Send settles only once the loader has answered, 400 ms on, and leaves Hires fix to it',
      [performance.now() - started >= 395, timeline.some(([what]) => what === 'hires off')], [true, false]);
loaderDelay = 0;

// ---------------------------------------------- a press that was kept (#7)
// A generation recorded with what its press was sent is set back by the
// hidden button as Load to UI sets a task, for its image's own seed and
// prompts - the server decides, and says so; what kept what was on screen is said.
planAnswer = { ...NO_PLAN, inputs: true };
loaderAnswer = () => ({ replayed: true, generation: 1, skipped: ['ControlNet: 0'], notes: [] });
document.querySelectorAll('.mm-notice').forEach((n) => n.remove());
let before = loaderAsked.length;
await act('generations.send', { tile: 0 });
await waitFor('the load', () => loaderAsked.length > before);
await whenSendSettled();
check('a generation whose press was kept: one request, the generation and its image as the source',
      loaderAsked.slice(before).map(({ tab, source }) => [tab, source?.generation, source?.image]), [['txt2img', 1, 11]]);
check('and its tab is shown', shown[shown.length - 1], 'tab_txt2img-button');
check('what kept what was on screen is said, the replay\'s own words',
      document.querySelector('.mm-notice')?.textContent, 'These keep what was on screen, or their defaults: ControlNet: 0.');
document.querySelectorAll('.mm-notice').forEach((n) => n.remove());

// A replay the server cannot make - a script gone whose choice it kept - is
// pasted by the server in the same event (img2img_send_test.py): the page
// asks once, and goes on as for a paste.
loaderAnswer = () => ({ pasted: true, missing: [] });
before = loaderAsked.length;
await act('generations.send', { tile: 0 });
await whenSendSettled();
check('a replay the server turned into a paste: the page asks once, and says nothing of what kept its value',
      [loaderAsked.slice(before).length, document.querySelector('.mm-notice')], [1, null]);
loaderAnswer = () => ({ pasted: true });

// A plan the server cannot give stops the Send, saying so (#302) - it sent
// the infotext as it was before.
planAnswer = { success: false };
before = loaderAsked.length;
await act('generations.send', { tile: 0 });
await waitFor('the notice', () => document.querySelector('.mm-notice'));
check('no plan: nothing sent, and said',
      [loaderAsked.length - before, document.querySelector('.mm-notice')?.textContent],
      [0, 'Could not send: the server did not answer.']);
document.querySelectorAll('.mm-notice').forEach((n) => n.remove());

// Files this WebUI lacks - the hires checkpoint an infotext names - are said.
planAnswer = NO_PLAN;
loaderAnswer = () => ({ pasted: true, missing: ['gone_model [abc123]'] });
await act('generations.send', { tile: 0 });
await waitFor('the notice', () => document.querySelector('.mm-notice'));
check('a file the paste names that this WebUI lacks is said',
      document.querySelector('.mm-notice')?.textContent,
      'gone_model [abc123] is not in this WebUI: the current choice is kept for it.');
document.querySelectorAll('.mm-notice').forEach((n) => n.remove());

// A sampler, upscaler or detector this WebUI lacks is said with its kind,
// promising nothing kept: Forge's paste is left as it is (#307).
loaderAnswer = () => ({ pasted: true, unavailable: [{ name: 'DPM2 a', kind: 'sampler' }, { name: '4x-UltraSharpV2', kind: 'Hires upscaler' }],
                        missing: ['sdxl_vae.safetensors'] });
await act('generations.send', { tile: 0 });
await waitFor('the notice', () => document.querySelector('.mm-notice'));
check('names this WebUI lacks, each with its kind, then the files kept as they were - in one notice',
      [...document.querySelectorAll('.mm-notice')].map((n) => n.textContent),
      ['DPM2 a (sampler) and 4x-UltraSharpV2 (Hires upscaler) are not in this WebUI. '
       + 'sdxl_vae.safetensors is not in this WebUI: the current choice is kept for it.']);
document.querySelectorAll('.mm-notice').forEach((n) => n.remove());
loaderAnswer = () => ({ pasted: true, unavailable: [{ name: 'beta57', kind: 'schedule type' }] });
await act('generations.send', { tile: 0 });
await waitFor('the notice', () => document.querySelector('.mm-notice'));
check('one name alone', document.querySelector('.mm-notice')?.textContent, 'beta57 (schedule type) is not in this WebUI.');
loaderAnswer = () => ({ pasted: true });

// An image Sync images brought with no generation text (#233): Send has
// nothing to paste. It did nothing at all, the button enabled; it is
// disabled now, saying why, on the tile and in the viewer.
const bare = { ...image, id: 12, infotext: null, meta: {}, url: '/model-manager/generations/images/12/file' };
tiles = [...tiles, { kind: 'generation', generation: { ...generation, id: 2 }, matching_count: 1, images: [bare],
                     loras: [], level: 1, user_level: null }];
await act('generations.refresh');
await waitFor('the second tile', () => document.querySelectorAll('#gen_grid .gen-tile').length === 2);
const sendOf = (n) => document.querySelector(`#gen_grid [data-action="generations.send"][data-tile="${n}"]`);
check('an image with no text: its Send is disabled, saying why; one with text is not',
      [sendOf(1)?.disabled, (sendOf(1)?.title || '').includes('no infotext'), sendOf(0)?.disabled],
      [true, true, false]);
await act('generations.view', { tile: 1 });
await waitFor('the viewer', () => document.querySelector('[data-gen-send]'));
check('and in the viewer', document.querySelector('[data-gen-send]')?.disabled, true);
(await sharedModule('viewer.mjs')).closeViewer();

// ------------------------------------------------- into img2img's modes (#299)
// An image tile's ⋯ sends its picture into one of img2img's modes: the
// loader is asked with the mode and the image's own file, the settings as
// Send sets them - any image, with no infotext too, and a missing checkpoint
// said rather than a stop.
for (const id of ['img2img_img2img_tab', 'img2img_img2img_sketch_tab', 'img2img_inpaint_tab',
                  'img2img_inpaint_sketch_tab', 'img2img_inpaint_upload_tab']) {
    document.getElementById('tabs').insertAdjacentHTML('beforeend', `<button id="${id}-button"></button>`);
    document.getElementById(`${id}-button`).addEventListener('click', () => shown.push(`${id}-button`));
}
const gone = { ...image, id: 13, exists: false, url: '/model-manager/generations/images/13/file' };
const batch = { kind: 'generation', generation: { ...generation, id: 4 }, matching_count: 2,
                images: [{ ...image, id: 41 }, { ...image, id: 42 }], loras: [], level: 1, user_level: null };
tiles = [...tiles, { kind: 'generation', generation: { ...generation, id: 3 }, matching_count: 1, images: [gone],
                     loras: [], level: 1, user_level: null }, batch];
await act('generations.refresh');
await waitFor('four tiles', () => document.querySelectorAll('#gen_grid .gen-tile').length === 4);
const menuItems = () => [...document.querySelectorAll('.gen-menu button')].map((b) => [b.textContent.trim(), b.disabled]);
const menuOf = (n) => document.querySelector(`#gen_grid [data-action="generations.menu"][data-tile="${n}"]`);
const press = async (n, label) => {
    await act('generations.menu', { tile: n });
    const item = [...document.querySelectorAll('.gen-menu button')].find((b) => b.textContent.trim() === label);
    item?.dispatchEvent(new window.Event('click', { bubbles: true }));
    return item;
};
// What a send asks: the settings button, then - img2img's canvases set apart -
// the mode's canvas button with the picture.
const settingsAsked = (from) => loaderAsked.slice(from).filter((r) => r.canvas === undefined);
const canvasAsked = (from) => loaderAsked.slice(from).filter((r) => r.canvas !== undefined)
    .map(({ canvas, picture, generation: g, task }) => ({ canvas, ...(picture ? { picture } : {}),
                                                           ...(g !== undefined ? { generation: g } : {}),
                                                           ...(task !== undefined ? { task } : {}) }));
const SEND_LABELS = ['Send to img2img', 'Send to Sketch', 'Send to Inpaint', 'Send to Inpaint sketch',
                     'Send to Inpaint upload'];
try {
check('an image tile\'s menu starts with the five sends into img2img, in Forge\'s order',
      (await act('generations.menu', { tile: 0 }), menuItems().slice(0, 5)), SEND_LABELS.map((l) => [l, false]));
document.body.dispatchEvent(Object.assign(new window.Event('keydown', { bubbles: true }), { key: 'Escape' }));
check('a batch of several images has none - which image would go? - nor a ⋯ at all here', !!menuOf(3), false);
await act('generations.menu', { tile: 2 });
check('a tile whose file is gone has them greyed, saying so',
      [menuItems().slice(0, 5).every(([, off]) => off),
       document.querySelector('.gen-menu button')?.getAttribute('title')], [true, 'The image file is gone: deleted or moved']);
document.body.dispatchEvent(Object.assign(new window.Event('keydown', { bubbles: true }), { key: 'Escape' }));

planAnswer = NO_PLAN;
let at = loaderAsked.length;
await press(0, 'Send to Inpaint');
await waitFor('the send into Inpaint', () => canvasAsked(at).length);
await new Promise((resolve) => setTimeout(resolve, 50));
check('Send to Inpaint: img2img\'s settings button asked with the generation as its source, the mode and the picture\'s size',
      settingsAsked(at).map(({ tab, source, into }) => [tab, source?.generation, source?.image, into]),
      [['img2img', 1, 11, { mode: 2, picture: { generation_image: 11 }, width: 832, height: 1216 }]]);
check('then Inpaint\'s canvas button, with the image\'s own file - the canvases are never the settings button\'s',
      canvasAsked(at), [{ canvas: 2, picture: { generation_image: 11 } }]);
check('img2img shown, on Inpaint', shown.slice(-2), ['tab_img2img-button', 'img2img_inpaint_tab-button']);

at = loaderAsked.length;
await press(1, 'Send to Sketch');
await waitFor('the picture alone', () => canvasAsked(at).length);
await new Promise((resolve) => setTimeout(resolve, 50));
check('an image with no infotext goes too: its source - nothing for the server to paste - the mode, the picture',
      [settingsAsked(at).map(({ tab, source, into }) => [tab, source?.image, into?.mode]), canvasAsked(at)],
      [[['img2img', 12, 1]], [{ canvas: 1, picture: { generation_image: 12 } }]]);
check('and img2img shown on Sketch', shown.slice(-2), ['tab_img2img-button', 'img2img_img2img_sketch_tab-button']);

// Whether a kept press goes into img2img is the server's (send.replays): a
// txt2img generation's is pasted there, an img2img one's replayed, with this
// send's mode, then its picture into the mode's canvas.
planAnswer = { ...NO_PLAN, inputs: true };
generation.mode = 'img2img';
loaderAnswer = (tab, request) => ({ replayed: true, mode: request.into?.mode, skipped: [], notes: [] });
at = loaderAsked.length;
await press(0, 'Send to Inpaint upload');
await waitFor('the replay', () => canvasAsked(at).length);
await new Promise((resolve) => setTimeout(resolve, 50));
check('an img2img generation\'s kept press: replayed, with the mode, then the picture into Inpaint upload',
      [settingsAsked(at).map(({ tab, source, into }) => [tab, source?.generation, source?.image, into?.mode]),
       canvasAsked(at), shown[shown.length - 1]],
      [[['img2img', 1, 11, 4]], [{ canvas: 4, picture: { generation_image: 11 } }], 'img2img_inpaint_upload_tab-button']);
generation.mode = 'txt2img';
loaderAnswer = () => ({ pasted: true });

// A checkpoint the library lacks: said, the picture sent with the one loaded - no stop, no Resources.
planAnswer = { ...NO_PLAN, checkpoint_missing: 'gone_checkpoint.safetensors' };
document.querySelectorAll('.mm-notice').forEach((n) => n.remove());
at = loaderAsked.length;
await press(0, 'Send to Inpaint sketch');
await waitFor('the send with the checkpoint missing', () => canvasAsked(at).length);
check('a missing checkpoint: the send goes on, into Inpaint sketch',
      [settingsAsked(at).map(({ tab, into }) => [tab, into?.mode]), canvasAsked(at).map((r) => r.canvas)],
      [[['img2img', 3]], [3]]);
check('saying which, and opening no Resources',
      [[...document.querySelectorAll('.mm-notice')].some((n) => /sent with the checkpoint loaded instead of gone_checkpoint/
       .test(n.textContent)), !!document.querySelector('.mm-resources-modal')], [true, false]);
planAnswer = NO_PLAN;

// Send's own button asks nothing of the sort.
at = loaderAsked.length;
await act('generations.send', { tile: 0 });
await waitFor('Send', () => loaderAsked.length > at);
await new Promise((resolve) => setTimeout(resolve, 50));
check('Send\'s own button: into its own tab, no mode or picture, no canvas button',
      loaderAsked.slice(at).map(({ tab, into, canvas }) => [tab, into, canvas]), [['txt2img', undefined, undefined]]);
} catch (error) {
    check('into img2img\'s modes: the items, what they ask, what they show', String(error), null);
}

done();

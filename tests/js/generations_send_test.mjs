// The Generations tab sends with nothing but the shared code (#91). Send -
// Forge's VAE / Text Encoder control, the UI preset, the paste, the chips -
// lived in the Model Manager's script, and the Generations tab reached it
// through that tab: without its script loaded, nothing could be sent.
//
// Here the Generations tab is loaded alone. Its Send pastes the generation's
// infotext into the tab it was made in - through the tab's hidden button,
// which runs Forge's paste - shows that tab, and leaves Forge's scheduler
// set; the Model Manager's script never loads. A generation whose press was
// kept is set back by that button instead, as Load to UI sets a task (#7).
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
    if (request.paste !== undefined) pasted[tab] += 1;
    timeline.push(['answered', performance.now() + loaderDelay]);
}, answer: (tab, request) => loaderAnswer(tab, request), delay: () => loaderDelay });
document.querySelector('#txt2img_hr-checkbox input').addEventListener('change',
    () => timeline.push(['hires off', performance.now()]));
const lastPaste = () => [...loaderAsked].reverse().find((r) => r.paste !== undefined)?.paste;
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
let planAnswer = { success: false };
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
    if (href.includes('/send-plan')) return reply(planAnswer);
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
check('Send pastes the generation\'s infotext into the tab it was made in', lastPaste(), INFOTEXT);
check('through that tab\'s hidden button, once, naming the generation for its corrections',
      [pasted.txt2img, pasted.img2img, loaderAsked[0]?.generation, buttonPastes.txt2img], [1, 0, 1, 0]);
check('and shows the tab', shown, ['tab_txt2img-button']);
await waitFor('the landing', () => scrolls.length > 1);
check('and lands at the page\'s top, the checkpoint and modules in view (#263): the tab bar, then 0',
      scrolls, [120, 0]);
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
      lastPaste(), 'a flower, <lora:Anime_Girl-Flower_ill_epoch_10:1>\nSteps: 20, Seed: 7, Version: neo');
globalThis.fetch = fetchBefore;

// ------------------------------------------ what follows the paste waits for it
// The scheduler, the modules and Hires fix are set once the paste has
// answered, never after a fixed wait: 100 ms was shorter than every paste
// measured on Neo (58 of 58), so they were set before it had landed.
Object.assign(image, { infotext: INFOTEXT, meta: { prompt: 'a lighthouse at dusk', steps: 20 } });
const { whenSendSettled } = await sharedModule('send.mjs');
await whenSendSettled();                      // the last send's own steps done
loaderDelay = 400;
timeline.length = 0;
document.querySelector('#txt2img_hr-checkbox input').checked = true;
await act('generations.send', { tile: 0 });
await waitFor('Hires fix turned off', () => timeline.some(([what]) => what === 'hires off'));
const at = Object.fromEntries(timeline);
check('Hires fix is turned off only once the paste has answered, 400 ms on',
      at['hires off'] >= at.answered - 5, true);
loaderDelay = 0;
await whenSendSettled();

// ---------------------------------------------- a press that was kept (#7)
// A generation recorded with what its press was sent is set back by the
// hidden button as Load to UI sets a task: the generation and the image -
// for its own seed and prompts - and nothing pasted.
planAnswer = { success: true, inputs: true, preset: null, checkpoint: null, target: [], modules_missing: [] };
let before = loaderAsked.length;
await act('generations.send', { tile: 0 });
await waitFor('the load', () => loaderAsked.length > before);
await new Promise((resolve) => setTimeout(resolve, 50));
check('a generation whose press was kept is loaded for its image, not pasted',
      loaderAsked.slice(before).map(({ tab, generation, image: id, paste }) => [tab, generation, id, paste]),
      [['txt2img', 1, 11, undefined]]);
check('and its tab is shown', shown[shown.length - 1], 'tab_txt2img-button');

// A load the server refuses - a script gone whose choice it kept - falls
// back to the paste, corrected from the generation's record.
loaderAnswer = (tab, request) => (request.paste === undefined ? { error: 'Script "X" is gone' } : { pasted: true });
before = loaderAsked.length;
await act('generations.send', { tile: 0 });
await waitFor('the paste after the failed load', () => loaderAsked.slice(before).some((r) => r.paste !== undefined));
check('a load that fails is followed by the paste, naming the generation',
      loaderAsked.slice(before).map((r) => [r.paste === undefined ? 'load' : 'paste', r.generation]),
      [['load', 1], ['paste', 1]]);
loaderAnswer = () => ({ pasted: true });

// Files this WebUI lacks - the hires checkpoint an infotext names - are said.
planAnswer = { success: false };
loaderAnswer = () => ({ pasted: true, missing: ['gone_model [abc123]'] });
await act('generations.send', { tile: 0 });
await waitFor('the notice', () => document.querySelector('.mm-notice'));
check('a file the paste names that this WebUI lacks is said',
      document.querySelector('.mm-notice')?.textContent,
      'gone_model [abc123] is not in this WebUI: the current choice is kept for it.');
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

planAnswer = { success: false };
let at = loaderAsked.length;
await press(0, 'Send to Inpaint');
await waitFor('the send into Inpaint', () => canvasAsked(at).length);
await new Promise((resolve) => setTimeout(resolve, 50));
check('Send to Inpaint: img2img\'s settings button asked to paste the infotext, with the mode and the picture\'s size',
      settingsAsked(at).map(({ tab, paste, generation: g, into }) => [tab, paste, g, into]),
      [['img2img', INFOTEXT, 1, { mode: 2, picture: { generation_image: 11 }, width: 832, height: 1216 }]]);
check('then Inpaint\'s canvas button, with the image\'s own file - the canvases are never the settings button\'s',
      canvasAsked(at), [{ canvas: 2, picture: { generation_image: 11 } }]);
check('img2img shown, on Inpaint', shown.slice(-2), ['tab_img2img-button', 'img2img_inpaint_tab-button']);

at = loaderAsked.length;
await press(1, 'Send to Sketch');
await waitFor('the picture alone', () => canvasAsked(at).length);
await new Promise((resolve) => setTimeout(resolve, 50));
check('an image with no infotext goes too: nothing to paste - the mode and the picture alone',
      [settingsAsked(at).map(({ tab, paste, into }) => [tab, paste, into?.mode]), canvasAsked(at)],
      [[['img2img', undefined, 1]], [{ canvas: 1, picture: { generation_image: 12 } }]]);
check('and img2img shown on Sketch', shown.slice(-2), ['tab_img2img-button', 'img2img_img2img_sketch_tab-button']);

// A txt2img generation's kept press cannot go into img2img: its infotext is pasted.
planAnswer = { success: true, inputs: true, preset: null, checkpoint: null, target: [], modules_missing: [] };
at = loaderAsked.length;
await press(0, 'Send to img2img');
await waitFor('the send', () => canvasAsked(at).length);
await new Promise((resolve) => setTimeout(resolve, 50));
check('a txt2img generation\'s kept press: not replayed into img2img, its infotext pasted',
      settingsAsked(at).map((r) => [r.paste === undefined ? 'load' : 'paste', r.into?.mode]), [['paste', 0]]);

// An img2img generation's kept press is replayed, with this send's mode and picture.
generation.mode = 'img2img';
at = loaderAsked.length;
await press(0, 'Send to Inpaint upload');
await waitFor('the replay', () => canvasAsked(at).length);
await new Promise((resolve) => setTimeout(resolve, 50));
check('an img2img generation\'s kept press: replayed, with the mode, then the picture into Inpaint upload',
      [settingsAsked(at).map(({ tab, generation: g, image: i, paste, into }) => [tab, g, i, paste, into?.mode]),
       canvasAsked(at)], [[['img2img', 1, 11, undefined, 4]], [{ canvas: 4, picture: { generation_image: 11 } }]]);
generation.mode = 'txt2img';

// A checkpoint the library lacks: said, the picture sent with the one loaded - no stop, no Resources.
planAnswer = { success: true, checkpoint_missing: 'gone_checkpoint.safetensors', preset: null, checkpoint: null,
               target: [], modules_missing: [] };
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
planAnswer = { success: false };

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

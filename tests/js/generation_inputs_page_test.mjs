// The images an img2img generation started from, on the page (#34). Send on
// a generation whose press was kept opens img2img on the mode the press was
// made in, as Load to UI does a task's - it opened img2img's plain mode
// whatever the press's was - and says its source is not kept only when the
// server's answer says it did not come back. The viewer offers the source,
// and the source with its layer, where the generation kept them.
import { act, checker, mountTab, sendLoaders, sharedModule, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
const { check, waitFor, done } = checker();

// ------------------------------------------- Forge's generation tabs
const MODES = ['img2img_img2img_tab', 'img2img_img2img_sketch_tab', 'img2img_inpaint_tab',
               'img2img_inpaint_sketch_tab', 'img2img_inpaint_upload_tab', 'img2img_batch_tab'];
document.body.insertAdjacentHTML('afterbegin', `
    <div id="tabs">
        <button id="tab_txt2img-button">txt2img</button>
        <button id="tab_img2img-button">img2img</button>
        <button id="tab_queue_tab-button">Queue</button>
        <button id="tab_generations_tab-button" class="selected" aria-selected="true">Generations</button>
    </div>
    <div id="img2img_modes">${MODES.map((id) => `<button id="${id}-button"></button>`).join('')}</div>
    <div id="txt2img_prompt"><textarea></textarea></div>
    <div id="img2img_prompt"><textarea></textarea></div>
    <div id="img2img_tools"><button id="paste"></button></div>`);
const shown = [];
document.querySelectorAll('#tabs button, #img2img_modes button')
    .forEach((b) => b.addEventListener('click', () => shown.push(b.id)));
let loaderAnswer = () => ({ pasted: true });
// Whether the mode's canvas button put the kept source back (#299: the
// canvases are no longer the settings button's).
let canvasSource = true;
const loaderAsked = [];
sendLoaders(document, { onAsk: (tab, request) => loaderAsked.push({ tab, ...request }),
                        answer: (tab, request) => loaderAnswer(tab, request),
                        canvasAnswer: () => ({ source: canvasSource }) });
const canvasAsks = (from) => loaderAsked.slice(from).filter((r) => r.canvas !== undefined)
    .map(({ canvas, generation, task }) => [canvas, generation ?? null, task ?? null]);

// ------------------------------------------------------------- the server
const kept = { source: '/model-manager/generations/1/input/init_img_with_mask',
               layer: '/model-manager/generations/1/input/init_img_with_mask_fg', layer_kind: 'mask' };
const image = (id, inputs) => ({
    id, generation_id: id, position: 0, seed: 7, width: 64, height: 48, meta: { prompt: 'a lighthouse', steps: 20 },
    infotext: 'a lighthouse\nSteps: 20', url: `/model-manager/generations/images/${id}/file`, exists: true,
    mm_level: 1, mm_level_from_prompt: false, user_level: null, loras: [], ...(inputs ? { inputs } : {}),
});
const tile = (id, inputs) => ({ kind: 'generation', generation: { id, mode: 'img2img', created_at: '2026-10-18T10:00:00',
                                                                  image_count: 1 },
                                matching_count: 1, images: [image(id, inputs)], loras: [], level: 1, user_level: null });
const tiles = [tile(1, kept), tile(2, null)];
let planAnswer = { success: true, inputs: true, preset: null, checkpoint: null, target: [], modules_missing: [] };
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/ui-options')) {
        return reply({ success: true, samplers: ['Euler'], schedulers: ['Automatic'], gallery_hide_nsfw: true,
                       generations_hide_nsfw: true, generations_enabled: true });
    }
    if (href.includes('/generations/browse')) {
        return reply({ success: true, more: false, tiles,
                       state: { total: 2, filtered: 2, hidden_nsfw: 0, nsfw_count: 0, hide_nsfw_images: true,
                                stored_generations: 2 },
                       scope: { count: 2 } });
    }
    // Send's one plan route (#302): a task's, else a generation's.
    if (href.includes('/send/plan') && href.includes('kind=task')) {
        return reply({ success: true, mode: 'img2img', preset: null, checkpoint: null, target: [], modules_missing: [] });
    }
    if (href.includes('/send/plan')) return reply(planAnswer);
    return reply({ success: true });
};

await startTab('generations');
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await waitFor('the tiles', () => document.querySelectorAll('#gen_grid .gen-tile').length === 2);
const notice = () => document.querySelector('.mm-notice')?.textContent || '';
const clearNotices = () => document.querySelectorAll('.mm-notice').forEach((n) => n.remove());

// ============================================= Send, its source put back
loaderAnswer = () => ({ replayed: true, mode: 2, source: true, skipped: [], notes: [] });
let before = loaderAsked.length;
clearNotices();
await act('generations.send', { tile: 0 });
await waitFor('the load', () => loaderAsked.length > before);
await new Promise((resolve) => setTimeout(resolve, 80));
check('Send opens img2img on the mode the press was made in: Inpaint',
      shown.slice(-2), ['tab_img2img-button', 'img2img_inpaint_tab-button']);
check('and, its source put back, does not say it is not kept', notice().includes('drop an image in'), false);
check('the press\'s canvases asked of Inpaint\'s own canvas button, by the generation (#299)',
      canvasAsks(before), [[2, 1, null]]);

// ======================================= Send, its source not put back
loaderAnswer = () => ({ replayed: true, mode: 4, source: false, skipped: [], notes: [] });
canvasSource = false;
before = loaderAsked.length;
clearNotices();
await act('generations.send', { tile: 1 });
await waitFor('the load', () => loaderAsked.length > before);
await waitFor('the notice', () => notice());
check('a press whose source did not come back: its mode, Inpaint upload, and the notice',
      [shown[shown.length - 1], notice().includes('drop an image in')], ['img2img_inpaint_upload_tab-button', true]);

// ======================================================== Load to UI
const { loadTask } = await sharedModule('send.mjs');
loaderAnswer = () => ({ mode: 3, skipped: [], notes: [] });
canvasSource = true;
before = loaderAsked.length;
await loadTask(5);
check('Load to UI opens the task\'s mode too: Inpaint sketch', shown[shown.length - 1], 'img2img_inpaint_sketch_tab-button');
check('and asks Inpaint sketch\'s canvas button for the task\'s canvases', canvasAsks(before), [[3, null, 5]]);

// ========================================================= the viewer
const viewer = () => document.querySelector('.mm-viewer');
const views = () => Array.from(viewer()?.querySelectorAll('.mm-viewer-views [data-view]') || [])
    .map((b) => [b.textContent.trim(), b.classList.contains('active')]);
await act('generations.view', { tile: 0 });
await waitFor('the viewer', () => viewer());
check('the viewer offers the source and the source with its mask, the result first',
      views(), [['Result', true], ['Source', false], ['Source with its mask', false]]);
viewer()?.querySelector('[data-view="1"]')?.dispatchEvent(new window.Event('click', { bubbles: true }));
check('Source shows the kept source',
      viewer().querySelector('.mm-viewer-frame img')?.getAttribute('src'), `http://localhost:7860${kept.source}`);
viewer()?.querySelector('[data-view="2"]')?.dispatchEvent(new window.Event('click', { bubbles: true }));
const layered = Array.from(viewer().querySelectorAll('.mm-viewer-layered img'))
    .map((img) => [img.getAttribute('src'), img.getAttribute('data-layer-kind')]);
check('and the source with its mask, the mask drawn over it',
      layered, [[`http://localhost:7860${kept.source}`, null], [`http://localhost:7860${kept.layer}`, 'mask']]);
document.dispatchEvent(Object.assign(new window.Event('keydown'), { key: 'ArrowRight' }));
check('an image whose generation kept nothing: no switch', [views(), !!viewer()?.querySelector('.mm-viewer-layered')],
      [[], false]);
document.dispatchEvent(Object.assign(new window.Event('keydown'), { key: 'ArrowLeft' }));
check('back to the first, it opens as the result again', views()[0], ['Result', true]);

done();

// Send with a checkpoint the library has, whose drive or folder is not there (#418).
//
// Since #389 a sync keeps such a checkpoint's row, so Send's answer for it
// stays the same until the drive is back: "unseen". It used to be taken for
// "not in your library" or "Forge does not list it yet", and the dialog
// waited on a timer for what no wait would bring. Now the stop says where the
// file was and that its drive or folder is not there; the dialog's Check again
// is there from the start and asks once a press; and once the drive is back -
// Forge not having listed the file since - the check refreshes Forge's list,
// once, and Send works.
import { act, call, checker, forgeRefreshButtons, mountTab, sendLoaders, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
window.mmTiming = { poll: 20, sendRecheck: 20, sendRecheckMax: 200 };
const { check, waitFor, done } = checker();

document.body.insertAdjacentHTML('afterbegin', `
    <div id="tabs">
        <button id="tab_txt2img-button">txt2img</button>
        <button id="tab_img2img-button">img2img</button>
        <button id="tab_generations_tab-button" class="selected" aria-selected="true">Generations</button>
    </div>
    <div id="txt2img_prompt"><textarea></textarea></div>
    <div id="txt2img_tools"><button id="paste"></button></div>
    <div id="img2img_prompt"><textarea></textarea></div>
    <div id="img2img_tools"><button id="paste"></button></div>`);
const loaderAsked = [];
sendLoaders(document, { onAsk: (tab, request) => loaderAsked.push({ tab, ...request }),
                        answer: () => ({ pasted: true }), sourceText: () => 'a lighthouse\nSteps: 20, Seed: 7' });
const refreshed = forgeRefreshButtons(document, window);

// ------------------------------------------------------------- the server
const PATH = 'X:\\sd\\away.safetensors';
const image = { id: 11, generation_id: 1, position: 0, seed: 7, width: 832, height: 1216,
                meta: { prompt: 'a lighthouse', steps: 20 }, infotext: 'a lighthouse\nSteps: 20, Seed: 7',
                url: '/model-manager/generations/images/11/file', exists: true, mm_level: 1,
                mm_level_from_prompt: false, user_level: null, prompt_level: 1, loras: [] };
const generation = { id: 1, mode: 'txt2img', created_at: '2026-10-02T10:00:00', image_count: 1 };
const NO_PLAN = { success: true, inputs: false, preset: null, checkpoint: null, target: [], modules_missing: [] };
// The plan's answer: the drive away; back, Forge not listing the file; or listed.
let drive = 'away';
const planFor = () => (drive === 'away'
    // The reason alone, as the server answers when Forge still lists the file
    // (#418, question 5): a check that read only checkpoint_missing called it ready.
    ? { ...NO_PLAN, checkpoint_problem: { reason: 'unseen', name: 'away.safetensors', path: PATH } }
    : drive === 'listed' ? { ...NO_PLAN, checkpoint: 'away.safetensors [ab]' }
    : { ...NO_PLAN, checkpoint_missing: 'away.safetensors',
        checkpoint_problem: { reason: 'not_listed', name: 'away.safetensors', path: PATH } });
let plansAsked = 0;
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => structuredClone(body) });
    if (href.includes('/ui-options')) {
        return reply({ success: true, samplers: ['Euler'], schedulers: ['Automatic'], generations_enabled: true });
    }
    if (href.includes('/generations/browse')) {
        return reply({ success: true, more: false,
                       tiles: [{ kind: 'generation', generation, matching_count: 1, images: [image], loras: [],
                                 level: 1, user_level: null }],
                       state: { total: 1, filtered: 1, hidden_nsfw: 0, nsfw_count: 0, nsfw_images: 'safe',
                                stored_generations: 1 }, scope: { count: 1 } });
    }
    if (href.includes('/model-manager/send/plan')) {
        plansAsked += 1;
        return reply(planFor());
    }
    if (href.includes('/model-manager/send/checkpoints')) {
        return reply({ success: true, checkpoints: [], suggested: [], picked: null, loaded: null,
                       same_base: { base_model: null, names: [] }, family: null });
    }
    return reply({ success: true });
};

await startTab('generations');
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await waitFor('the grid', () => document.querySelectorAll('#gen_grid .gen-tile').length === 1);

const dialog = () => document.querySelector('.mm-resources-modal');
const line = () => (dialog()?.querySelector('.mm-res-send-status')?.textContent || '').replace(/\s+/g, ' ').trim();
const checkAgain = () => dialog()?.querySelector('[data-action="resources.checkAgain"]');
const dialogSend = () => dialog()?.querySelector('[data-action="resources.sendAgain"]');
const setChoose = (on) => {
    const box = dialog()?.querySelector('[data-action="resources.chooseTick"]');
    if (!box) return;
    box.checked = on;
    box.dispatchEvent(new window.Event('change', { bubbles: true }));
};

// ------------------------------------------------------ the drive away
await act('generations.send', { tile: 0 });
await waitFor('the stop\'s dialog', () => dialog());
check('the stop says where the checkpoint was, and that its drive or folder is not there',
      dialog()?.textContent.includes(`is in your library at ${PATH}, on a drive or in a folder that is not there now. `
                                     + 'Connect it, or pick one of yours below.'), true);
setChoose(false);
await waitFor('the line', () => line());
check('its own checkpoint: the line says why, Check again at once, Send waiting, nothing sent',
      [line(), Boolean(checkAgain()), dialogSend()?.disabled, loaderAsked.length],
      ['The checkpoint\'s drive or folder is not there now.', true, true, 0]);
const before = plansAsked;
await new Promise((resolve) => setTimeout(resolve, 120));
check('nothing asked on a timer while the drive is away', plansAsked, before);
await call('resources.checkAgain');
await waitFor('the press\'s answer', () => plansAsked > before);
await waitFor('Check again back', () => checkAgain());
await new Promise((resolve) => setTimeout(resolve, 120));
check('Check again, still away: asked once, Send still waiting, Check again offered again',
      [plansAsked - before, dialogSend()?.disabled, Boolean(checkAgain())], [1, true, true]);

// ------------------------------------- the drive back, Forge not listing it
drive = 'back';
check('no refresh of Forge\'s list so far', refreshed, []);
await call('resources.checkAgain');
await waitFor('Forge\'s list refreshed', () => refreshed.includes('checkpoints'));
await waitFor('the dialog to stop asking', () => checkAgain());
check('the drive back: Forge\'s list refreshed once, Forge still not listing it', 
      [refreshed.filter((r) => r === 'checkpoints').length, dialogSend()?.disabled], [1, true]);
await call('resources.checkAgain');
await waitFor('Check again after asking', () => checkAgain());
check('asked again, Forge still not listing it: no second refresh - that is Forge\'s to do',
      refreshed.filter((r) => r === 'checkpoints').length, 1);
drive = 'listed';
await call('resources.checkAgain');
await waitFor('Send ready', () => dialogSend() && !dialogSend().disabled);
check('once Forge lists it, Send works', dialogSend()?.disabled, false);

done();

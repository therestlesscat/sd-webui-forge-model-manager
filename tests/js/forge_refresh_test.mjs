// Forge's refreshes, one at a time (#321). The page pressed Forge's checkpoint
// refresh and the extra networks' hidden refresh in the same instant: both
// rebuild Forge's checkpoint list on the server, and the first could answer
// it half filled - 3 of 10 pairs on Neo, the Checkpoint box then empty while
// Forge still held the checkpoint. Now each press waits for the one before:
// the checkpoint refresh for its answer, the extra networks refresh for the
// step Forge chains after it; and every refresh - a batch of downloads, a
// sync's end, a delete, Send's own - waits in one line. The stand-in buttons
// answer as Gradio makes Forge's (harness.mjs, forgeRefreshButtons).
import { FORGE_REFRESH_EVENTS, checker, forgeRefreshButtons, mountTab, sharedModule } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
// The time a press is waited for, and a frame, shortened: a Forge that never
// answers is given up on within the suite's time.
window.mmTiming = { refreshMax: 300, frame: 10 };
const { check, done } = checker();

const standIn = async () => ({ ok: true, status: 200, json: async () => ({ success: true }) });
globalThis.fetch = standIn;
const warned = [];
const realWarn = console.warn;
console.warn = (...args) => { warned.push(args.join(' ')); };

const { useServices, leaveServices } = await sharedModule('loading.mjs');
const forge = await sharedModule('forge.mjs');
// Functions compare as JSON here, which says nothing of them: compared as booleans.
check('importing forge.mjs leaves the page\'s fetch as it was', globalThis.fetch === standIn, true);
await useServices(['forge.mjs'], 'a tab');
check('started by a tab that uses it, it watches the page\'s calls to Forge (#321)',
      [globalThis.fetch !== standIn, globalThis.fetch.mmWatched === true], [true, true]);

/** Forge's buttons, as a test needs them: the old ones taken off first. */
function buttons(options) {
    document.getElementById('forge_refresh_checkpoint')?.remove();
    document.getElementById('txt2img_lora_extra_refresh_internal')?.remove();
    window.gradio_config = {};
    return forgeRefreshButtons(document, window, options);
}
const { chained } = FORGE_REFRESH_EVENTS;
const posted = () => forge.forgeCalls.queued.map((call) => call.fn);

// ------------------------------------------------ one refresh of both
// The extra networks refresh only once Forge has answered the checkpoint one.
let pressed = buttons({ delay: 60 });
const callsBefore = forge.forgeCalls.started;
const batch = forge.refreshWebUiModelLists();
await new Promise((resolve) => setTimeout(resolve, 30));
check('a batch lands: the checkpoint refresh first, alone while Forge answers it', [...pressed], ['checkpoints']);
await batch;
check('then the extra networks refresh, after the answer', pressed, ['checkpoints', 'extra networks']);
check('and the refresh ends with the step Forge chains after it', posted().includes(chained), true);
// Send's preset waits count Forge's straight-to-server calls alone: the
// queue's posts are kept apart, so their waits are as they were.
check('Forge\'s calls as the preset waits count them: the checkpoint refresh\'s alone',
      forge.forgeCalls.started - callsBefore, 1);

// ------------------------------------------------ refreshes in line
// Two batches, a sync and a batch, Send's refresh while a batch's runs: each
// presses only once the one before has ended - the extra networks refresh's
// chained step posted.
pressed = buttons({ delay: 40 });
const queuedAtPress = [];
document.getElementById('forge_refresh_checkpoint')
    .addEventListener('click', () => queuedAtPress.push(posted().filter((fn) => fn === chained).length));
const before = posted().filter((fn) => fn === chained).length;
const first = forge.refreshWebUiModelLists();
const second = forge.refreshWebUiModelLists();
const sends = forge.refreshWebUiModelList();
await Promise.all([first, second, sends]);
check('three refreshes asked at once go one after the other',
      pressed, ['checkpoints', 'extra networks', 'checkpoints', 'extra networks', 'checkpoints']);
check('each checkpoint refresh pressed only after the one before had ended',
      queuedAtPress, [before, before + 1, before + 2]);

// ------------------------------------------------ Forge never answers
// The checkpoint refresh's answer never comes: the extra networks refresh
// is not pressed, the console says why, and the line moves on.
pressed = buttons({ answer: false });
warned.length = 0;
await forge.refreshWebUiModelLists();
check('no answer to the checkpoint refresh: the extra networks refresh is not pressed', pressed, ['checkpoints']);
check('and the console says so', warned.some((w) => w.includes('did not answer')), true);
pressed = buttons({ delay: 10 });
await forge.refreshWebUiModelLists();
check('the next refresh goes as ever', pressed, ['checkpoints', 'extra networks']);

// ------------------------------------------------ the end never comes
// The extra networks refresh's chained step never posts: the turn ends at
// the time limit, said, and the next refresh goes after it.
pressed = buttons({ chained: false, delay: 10 });
warned.length = 0;
const started = Date.now();
await forge.refreshWebUiModelLists();
check('no end to the extra networks refresh: the turn ends at the limit, said',
      [Date.now() - started >= 300, warned.some((w) => w.includes('did not finish'))], [true, true]);
pressed = buttons({ delay: 10 });
await forge.refreshWebUiModelLists();
check('and the next refresh goes after it', pressed, ['checkpoints', 'extra networks']);

// ------------------------------------------------ not Forge
// No refresh buttons on the page: said, as ever, and nothing pressed.
document.getElementById('forge_refresh_checkpoint')?.remove();
document.getElementById('txt2img_lora_extra_refresh_internal')?.remove();
warned.length = 0;
await forge.refreshWebUiModelLists();
check('no refresh buttons: each said, nothing waited for',
      [warned.some((w) => w.includes('checkpoint refresh button')), warned.some((w) => w.includes('extra networks refresh'))],
      [true, true]);

// ------------------------------------------------ stopped
leaveServices('a tab');
check('with the last tab that uses it, the watcher is taken off', globalThis.fetch === standIn, true);

console.warn = realWarn;
done();

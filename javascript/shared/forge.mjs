/**
 * What the page does with Forge's own page (#321) - the page's counterpart of
 * the server's forge_host.py: the calls Gradio makes to Forge, watched, and
 * Forge's refresh buttons, pressed one at a time. Send's helpers for Forge's
 * controls move here in #325.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { TIMING } = await shared('core.mjs');

/**
 * The calls Gradio makes to the server for a control's events. They go to
 * <root>/run/<event> through the page's fetch - in both WebUIs' Gradio 4.40 -
 * so wrapping fetch sees each one start and finish: `done`, in order, each
 * that came back - its event (`fn_index`), and whether it answered `ok`.
 * Apart from them, `queued`: each event posted to Gradio's queue
 * (<root>/queue/join), in order - a queued event's answer comes back through
 * Gradio's own stream, which fetch never sees, but the step chained after it
 * is posted only once it has finished (#321). Send's preset waits read the
 * first four alone.
 */
export const forgeCalls = { started: 0, inFlight: 0, last: 0, done: [], queued: [] };

function watchForgeCalls(scope) {
    if (globalThis.fetch?.mmWatched) return;
    const original = globalThis.fetch;
    const watched = function(resource, ...rest) {
        let path = '';
        try {
            path = new URL(typeof resource === 'string' ? resource : resource?.url || String(resource),
                           window.location.origin).pathname;
        } catch { /* not a URL we can read: not one of Gradio's */ }
        if (!watched.live || !(path.includes('/run/') || path.includes('/queue/join'))) {
            return original.call(this, resource, ...rest);
        }
        let fn = null;
        try {
            fn = JSON.parse(rest[0]?.body ?? '{}').fn_index ?? null;
        } catch { /* a body that is not JSON: an event we cannot name */ }
        if (path.includes('/queue/join')) {
            if (fn !== null) forgeCalls.queued.push({ fn });
            return original.call(this, resource, ...rest);
        }
        forgeCalls.started++;
        forgeCalls.inFlight++;
        forgeCalls.last = Date.now();
        const settle = (ok) => {
            forgeCalls.inFlight--;
            forgeCalls.last = Date.now();
            if (fn !== null) forgeCalls.done.push({ fn, ok });
        };
        const call = original.call(this, resource, ...rest);
        call.then((response) => settle(response?.ok !== false), () => settle(false));
        return call;
    };
    watched.mmWatched = true;
    watched.live = true;
    globalThis.fetch = watched;
    // Taken off with the last tab that uses it. Another wrapper put on since
    // would go with a plain restore, so then this one only stops watching.
    scope.onStop(() => {
        watched.live = false;
        if (globalThis.fetch === watched) globalThis.fetch = original;
    });
}

/**
 * The call watcher, put on when the first tab that uses Forge's controls
 * starts - Send, the downloads, the sync, the Model Manager - and taken off
 * with the last (#186). Every refresh waits on what it sees.
 */
export function start(scope) {
    watchForgeCalls(scope);
    line = Promise.resolve();
}

// ------------------------------------------------------- Forge's refreshes
// Forge's checkpoint refresh (#forge_refresh_checkpoint) answers the
// Checkpoint and VAE / Text Encoder dropdowns' choices, straight from the
// server. The extra networks' hidden refresh refreshes every extra-networks
// page - the LoRA cards, and the Checkpoints page, whose refresh empties
// Forge's checkpoint list and fills it again. Pressed together, the first
// could read the list half filled, and the Checkpoint box went empty while
// Forge still held its checkpoint: 3 of 10 pairs on Neo, 313 checkpoints
// (#321). So the page presses them one at a time, each waited for, and
// every refresh - a batch of downloads, a sync's end, a delete, Send's -
// waits in one line for the one before.

// How long a press is waited for: about 0.2 s for the checkpoint refresh and
// 1.0-1.4 s for the extra networks one on Neo. A suite shortens it with
// window.mmTiming, as every wait in TIMING.
const REFRESH_MAX = TIMING.refreshMax ?? 30000;

let line = Promise.resolve();

/** `turn` run once every refresh asked before it has ended; resolves with it. */
function inLine(turn) {
    const run = line.then(turn, turn);
    line = run.catch(() => {});
    return run;
}

function forgeApp() {
    return typeof gradioApp === 'function' ? gradioApp() : document;
}

/**
 * The events Gradio's config of the page names: a control's `trigger` (by its
 * elem_id), and the step chained after an event (`trigger_after`). Empty
 * where the config cannot say.
 */
function eventsOf(elemId, trigger = 'click') {
    const config = window.gradio_config;
    const component = (config?.components || []).find((c) => c?.props?.elem_id === elemId);
    if (!component) return [];
    return dependencies().filter((d) => (d.targets || []).some((target) => (Array.isArray(target)
        ? target[0] === component.id && target[1] === trigger : target === component.id))).map((d) => d.fn);
}

function chainedAfter(fns) {
    return dependencies().filter((d) => fns.includes(d.trigger_after)).map((d) => d.fn);
}

function dependencies() {
    return (window.gradio_config?.dependencies || []).map((d, at) => ({ ...d, fn: d.id ?? at }));
}

/** Until `came()` answers, or the time limit: what it answered, or null. */
async function until(came) {
    const end = Date.now() + REFRESH_MAX;
    for (;;) {
        const answer = came();
        if (answer) return answer;
        if (Date.now() >= end) return null;
        await new Promise((resolve) => setTimeout(resolve, TIMING.frame));
    }
}

/**
 * Press Forge's checkpoint refresh and wait for its answer: true once it has
 * come back, false when it failed or never came - and then nothing more is
 * pressed. A page without the button (not Forge) is said, as ever, and the
 * extra networks refresh may still go: nothing of ours races it then.
 */
async function refreshCheckpoints() {
    const button = forgeApp().querySelector('#forge_refresh_checkpoint');
    if (!button) {
        console.warn('[ModelManager] Could not find the checkpoint refresh button; '
            + 'the new model may need a manual refresh');
        return true;
    }
    const events = eventsOf('forge_refresh_checkpoint');
    const from = forgeCalls.done.length;
    button.click();
    const answer = await until(() => forgeCalls.done.slice(from)
        .find((call) => !events.length || events.includes(call.fn)));
    if (!answer || !answer.ok) {
        console.warn(`[ModelManager] Forge's checkpoint refresh ${answer ? 'failed' : 'did not answer'}; `
            + 'the extra networks refresh is left out');
        return false;
    }
    console.log('[ModelManager] Refreshed the WebUI model list');
    return true;
}

/**
 * Press the extra networks' hidden refresh - LoRAs, embeddings, their cards -
 * and wait for it to finish: the step Forge chains after it is posted to the
 * queue only then. Where the config names none, the first other event posted
 * after it.
 */
async function refreshExtraNetworks() {
    const button = forgeApp().querySelector('#txt2img_lora_extra_refresh_internal');
    if (!button) {
        console.warn('[ModelManager] Could not find the extra networks refresh; LoRAs may need a manual refresh');
        return;
    }
    const own = eventsOf('txt2img_lora_extra_refresh_internal');
    const next = chainedAfter(own);
    const from = forgeCalls.queued.length;
    button.click();
    const ended = await until(() => forgeCalls.queued.slice(from)
        .find((call) => (next.length ? next.includes(call.fn) : !own.includes(call.fn))));
    if (!ended) console.warn('[ModelManager] Forge\'s extra networks refresh did not finish in time; going on');
}

/**
 * Tell Forge its checkpoint list changed: its own refresh, which hands back
 * only new choices, so the current selection is left alone - in line, after
 * any refresh asked before. Its VAE / text encoder list is read again with
 * it. Resolves true once Forge has answered, false when the press is given
 * up.
 */
export function refreshWebUiModelList() {
    return inLine(() => refreshCheckpoints());
}

/**
 * Tell Forge its model files changed - downloaded, moved, forgotten,
 * deleted (#193): its checkpoint and VAE / text encoder lists, then its
 * extra networks - LoRAs, embeddings - through their hidden refresh, which
 * rescans every page on the server, the LoRAs a prompt's <lora:...> loads
 * included. A downloaded or moved LoRA was not loadable until then. One at
 * a time, in line (#321). The same buttons in both WebUIs. Nothing refreshes
 * upscalers: Forge reads them once, at startup.
 */
export function refreshWebUiModelLists() {
    return inLine(async () => {
        if (await refreshCheckpoints()) await refreshExtraNetworks();
    });
}

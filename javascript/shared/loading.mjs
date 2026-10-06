/**
 * The loading module (#183): which of the extension's tabs run, and the one
 * place that starts and stops them.
 *
 * The WebUI loads one script of ours, javascript/loader.mjs, which asks the
 * server for the shared version and calls boot() here. boot() asks
 * ui-options once which tabs are on, and which this start built (tabs.py),
 * and loads only those: a tab switched off is never imported, and none of
 * its code runs. The WebUI used to load every tab's script, whatever the
 * switches said - Generations off, its script still offered its actions and
 * added its listeners. A tab's script, in javascript/tabs/ - a folder the
 * WebUI does not list - does nothing as it is imported. It exports start(scope),
 * and whatever it adds outside its own markup goes through the scope: a
 * listener on the document or the window, a timer, an after-update hook, an
 * observer, an action offered. Listeners on its own elements hide with it.
 *
 * Switched off mid-session, a tab stops at once: its scope takes all of that
 * back, its button hides, and the page leaves it if it showed. Switched on
 * again, a tab built at this start and not started yet starts at once; one
 * stopped earlier comes back with a page reload, as its state went with it;
 * one not built, with a restart. The shared services a tab started keep
 * running for now (#186). Once for the page: the tabs share this copy.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { TIMING, escapeHtml, onReady, once } = await shared('core.mjs');
const { provide, withdraw } = await shared('calls.mjs');
const { showTab, tabButton, tabShowing } = await shared('tabs.mjs');
const { uiOptions, fetchUiOptions } = await shared('ui_options.mjs');

/**
 * Each tab, by the name tabs.mjs knows it by, in the order the WebUI shows
 * them: its script in javascript/tabs/; its name in ui-options (tabs.py); its
 * switch, if it has one yet (#185); the element that says Gradio has drawn
 * its markup; where the page goes when it hides while showing; what else
 * hides with it; and the event that tells the other tabs.
 */
export const TABS = {
    queue: { file: 'queue.mjs', server: 'queue', setting: 'model_manager_queue_enabled', markup: 'queue_active',
             elsewhere: 'txt2img', also: ['txt2img_queue', 'img2img_queue'], event: 'mm-queue-enabled' },
    generations: { file: 'generations.mjs', server: 'generations', setting: 'model_manager_record_generations',
                   markup: 'gen_grid', elsewhere: 'modelManager', also: [], event: 'mm-generations-enabled' },
    modelManager: { file: 'model_manager.mjs', server: 'model_manager', setting: null, markup: 'mm_load_btn',
                    elsewhere: 'txt2img', also: [], event: null },
    civitaiBrowser: { file: 'civitai_browser.mjs', server: 'civitai_browser', setting: null, markup: 'cb_search_btn',
                      elsewhere: 'txt2img', also: [], event: null },
};

// What a disabled link says each tab is (tabs.py's NAMES).
const LABELS = { queue: 'The Queue', generations: 'Your generations', modelManager: 'The Model Manager tab',
                 civitaiBrowser: 'The Civitai Browser tab' };

// Each tab: whether it is on and built, as the server last said - undefined
// until it has - its running scope and script, whether its start() has been
// called, and whether it ran and stopped.
const state = Object.fromEntries(Object.keys(TABS).map((name) => [name, { on: undefined, built: undefined,
                                                                         scope: null, module: null,
                                                                         started: false, stopped: false }]));

/** Whether your generations are shown: false only once the server said so. */
export function generationsEnabled() {
    return state.generations.on !== false;
}

/** Whether the queue is on: false only once the server said so. */
export function queueEnabled() {
    return state.queue.on !== false;
}

// ------------------------------------------------------- between tabs
// A tab reaches another only through here (#184): whether it is available,
// and open it at one of its entries - what its script offers the others. It
// called the other's actions by name, after checking ready() its own way,
// and drew its link whether that tab was there or not.

/** Whether a tab is there for the others: on, and started in this page. */
export function available(name) {
    const now = state[name];
    return Boolean(now && now.on !== false && now.started && now.scope?.live);
}

/** Why a tab is not available, as a link to it says. */
export function unavailableReason(name) {
    const now = state[name];
    const label = LABELS[name] || name;
    if (now?.on === false) return `${label} is turned off in the settings`;
    if (now?.built === false) return `${label} was turned on after the WebUI started: it comes with a restart`;
    if (now?.stopped) return `${label} was turned off in this page: it comes back with a reload`;
    return `${label} has not started yet`;
}

/**
 * The attributes of a link to another tab: its own title while that tab is
 * available; else disabled, saying why - as every control that would do
 * nothing. `disabled`: disabled for a reason of its own as well. The page's
 * one rule keeps it so as tabs come and go (applyLinks).
 */
export function linkTo(name, title, { disabled = false } = {}) {
    const on = available(name);
    return ` data-needs-tab="${escapeHtml(name)}" data-title-available="${escapeHtml(title)}"`
        + `${disabled ? ' data-disabled-own' : ''} title="${escapeHtml(on ? title : unavailableReason(name))}"`
        + `${on && !disabled ? '' : ' disabled'}`;
}

/**
 * Show a tab and open it at one of its entries, with these arguments.
 * Answers false, doing nothing, when it is not available.
 */
export async function open(name, entry, ...args) {
    if (!available(name)) return false;
    const fn = state[name].module?.entries?.[entry];
    if (typeof fn !== 'function') throw new Error(`The ${name} tab offers no ${entry}`);
    await showTab(name);
    await fn(...args);
    return true;
}

/** Every link to another tab, as that tab is now - writing only what differs: this runs after every update. */
function applyLinks() {
    if (typeof document === 'undefined') return;
    for (const link of document.querySelectorAll('[data-needs-tab]')) {
        const name = link.dataset.needsTab;
        const on = available(name);
        const disabled = !on || 'disabledOwn' in link.dataset;
        if (link.disabled !== disabled) link.disabled = disabled;
        const title = on ? (link.dataset.titleAvailable ?? '') : unavailableReason(name);
        if (link.title !== title) link.title = title;
    }
}

/** A tab came or went: its links, and the others told. */
function changed(name) {
    applyLinks();
    if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('mm-tabs-changed', { detail: { tab: name } }));
}

// ------------------------------------------------------------- the scope

/**
 * What a tab adds outside its own markup, taken back when it stops. Each
 * call does what its plain form does, and keeps how to undo it.
 */
export function createScope(name) {
    const undo = new Set();
    const keep = (step) => { undo.add(step); return step; };
    const listening = [];
    // A listener is one per target, type, function and capture, as the browser counts them.
    const captures = (options) => Boolean(typeof options === 'object' ? options?.capture : options);
    const scope = {
        name,
        live: true,
        /** target.addEventListener, removed on stop. */
        listen: (target, type, listener, options) => {
            target.addEventListener(type, listener, options);
            const step = keep(() => target.removeEventListener(type, listener, options));
            listening.push({ target, type, listener, capture: captures(options), step });
        },
        /** target.removeEventListener: what the tab takes back itself, no longer to take back on stop. */
        unlisten: (target, type, listener, options) => {
            target.removeEventListener(type, listener, options);
            const at = listening.findIndex((l) => l.target === target && l.type === type && l.listener === listener
                                                  && l.capture === captures(options));
            if (at >= 0) undo.delete(listening.splice(at, 1)[0].step);
        },
        /** setInterval - its arguments in that order - cleared on stop. */
        every: (work, ms) => {
            const id = setInterval(() => scope.live && work(), ms);
            keep(() => clearInterval(id));
            return id;
        },
        /** setTimeout, cleared on stop: what a stopped tab waited for never comes. */
        later: (work, ms) => {
            const step = () => clearTimeout(id);
            const id = setTimeout(() => {
                undo.delete(step);
                if (scope.live) work();
            }, ms);
            keep(step);
            return id;
        },
        /** A promise that settles after `ms` - never, once the tab has stopped. */
        sleep: (ms) => {
            return new Promise((resolve) => scope.later(resolve, ms));
        },
        /** onAfterUiUpdate: the WebUI keeps every callback, so a stopped tab's does nothing. */
        afterUpdate: (work) => {
            if (typeof onAfterUiUpdate === 'function') onAfterUiUpdate(() => { if (scope.live) work(); });
        },
        /** An observer, disconnected on stop. */
        observe: (observer) => {
            keep(() => observer.disconnect());
            return observer;
        },
        /** An action offered (shared/calls.mjs), withdrawn on stop. */
        provide: (action, fn) => {
            provide(action, fn);
            keep(() => withdraw(action, fn));
        },
        /** Anything else to take back: a registration a shared module answered how to undo. */
        onStop: (step) => {
            if (typeof step === 'function') keep(step);
        },
        /**
         * Whether Gradio has drawn the element - after the scripts have run,
         * and later on a slow machine - looked for until it is, for a minute at most.
         */
        markup: (id, tries = 240) => {
            const app = () => (typeof gradioApp === 'function' ? gradioApp() : document);
            return new Promise((resolve) => {
                const look = (left) => {
                    const drawn = Boolean(app().querySelector(`#${id}`));
                    if (drawn || left <= 0 || !scope.live) resolve(drawn && scope.live);
                    else scope.later(() => look(left - 1), TIMING.drawRetry);
                };
                look(tries);
            });
        },
        /** Take back everything, last first. */
        stop: () => {
            if (!scope.live) return;
            scope.live = false;
            for (const step of [...undo].reverse()) {
                try {
                    step();
                } catch (error) {
                    console.error(`[ModelManager] Stopping the ${name} tab:`, error);
                }
            }
            undo.clear();
        },
    };
    return scope;
}

/**
 * What a tab's script does once started, declared at its top level where it
 * belongs - a listener beside its handler, an action beside what it does -
 * and done by its start(scope), through the scope. Declaring does nothing:
 * a tab's script does nothing as it is imported.
 */
export function tabWork() {
    const steps = [];
    return {
        listen: (target, type, listener, options) => {
            steps.push((scope) => scope.listen(target, type, listener, options));
        },
        provide: (action, fn) => steps.push((scope) => scope.provide(action, fn)),
        afterUpdate: (work) => steps.push((scope) => scope.afterUpdate(work)),
        run: (work) => steps.push(work),
        start: (scope) => steps.forEach((step) => step(scope)),
    };
}

// ------------------------------------------------------- starting, stopping

/**
 * Load a tab's script and start it, once its markup is there: the shared
 * modules it uses first (#182). Resolves once its start() has been called -
 * not when it is done, as a tab's start goes on with its first requests.
 */
export async function startTab(name) {
    const tab = TABS[name];
    const now = state[name];
    if (now.scope || now.stopped) return now.scope;
    const scope = createScope(name);
    now.scope = scope;
    const module = await import(new URL(`../tabs/${tab.file}${new URL(import.meta.url).search}`, import.meta.url).href);
    for (const service of module.STARTS) (await shared(service)).start();
    if (!await scope.markup(tab.markup)) {
        if (scope.live) console.warn(`[ModelManager] The ${name} tab never appeared; not loading it`);
        return scope;
    }
    now.module = module;
    now.started = true;
    Promise.resolve().then(() => module.start(scope))
        .catch((error) => console.error(`[ModelManager] Starting the ${name} tab:`, error));
    changed(name);
    return scope;
}

/** Stop a tab: its scope takes back all it added. It starts again only with a page reload. */
export function stopTab(name) {
    const now = state[name];
    if (!now.scope) return;
    now.scope.stop();
    now.scope = null;
    now.started = false;
    now.stopped = true;
    changed(name);
}

/** Show or hide an element - writing only what differs: this runs after every update. */
function showElement(element, shown) {
    const display = shown ? '' : 'none';
    if (element && element.style.display !== display) element.style.display = display;
}

/**
 * Where the page goes when a tab hides while showing: its own fallback,
 * unless that one is not there - off, not built, or stopped; one still
 * starting is, as at the page's load.
 */
function fallbackFor(name) {
    const elsewhere = TABS[name].elsewhere;
    const there = state[elsewhere];
    return there && (there.on === false || there.built === false || there.stopped) ? 'txt2img' : elsewhere;
}

/**
 * A tab's button, shown while it is on and has not stopped, and what else
 * shows with it - the Queue buttons beside Generate, which the server wires,
 * while the queue is on. Off while showing: the page goes elsewhere, rather
 * than stay on a tab whose button is gone.
 */
function apply(name) {
    const tab = TABS[name];
    const now = state[name];
    const on = now.on !== false;
    showElement(tabButton(name), on && !now.stopped);
    const app = typeof gradioApp === 'function' ? gradioApp() : document;
    tab.also.forEach((id) => showElement(app.querySelector(`#${id}`), on));
    if ((!on || now.stopped) && tabShowing(name)) showTab(fallbackFor(name));
}

function applyAll() {
    Object.keys(TABS).forEach(apply);
    applyLinks();
}

/** A new answer for one tab: start or stop it, hide or show it, and tell the other tabs. */
function setOn(name, on) {
    const now = state[name];
    const changed = now.on !== undefined && now.on !== on;
    now.on = on;
    if (changed && !on) stopTab(name);
    if (changed && on) {
        if (now.built && !now.stopped) startTab(name);
        else console.info(`[ModelManager] The ${name} tab comes back with a page reload`
                          + (now.built ? '' : ' after a restart'));
    }
    apply(name);
    const event = TABS[name].event;
    if (changed && event) window.dispatchEvent(new CustomEvent(event, { detail: { enabled: on } }));
}

/** What a ui-options answer says of each tab. */
function takeTabs(data) {
    for (const [name, tab] of Object.entries(TABS)) {
        const said = data?.tabs?.[tab.server];
        if (!said || typeof said.on !== 'boolean') continue;
        state[name].built = said.built !== false;
        setOn(name, said.on);
    }
}

/**
 * Start the page: the tabs that are on and built, once the page is ready -
 * every one when the server cannot say, as before - then follow their
 * switches, saved in the settings window (its answer says each value) or on
 * the Settings page (only which keys changed: asked again).
 */
export const boot = once(() => {
    onReady(async () => {
        const data = await uiOptions();
        for (const [name, tab] of Object.entries(TABS)) {
            const said = data?.tabs?.[tab.server];
            state[name].on = said ? said.on !== false : true;
            state[name].built = said ? said.built !== false : true;
            apply(name);
            if (state[name].on && state[name].built) startTab(name);
        }
        window.addEventListener('mm-settings-saved', (event) => {
            for (const [name, tab] of Object.entries(TABS)) {
                const value = tab.setting && event.detail?.settings?.[tab.setting]?.value;
                if (typeof value === 'boolean') setOn(name, value);
            }
        });
        window.addEventListener('mm-settings-page-applied', (event) => {
            const changed = event.detail?.changed || [];
            if (Object.values(TABS).some((tab) => tab.setting && changed.includes(tab.setting))) {
                fetchUiOptions().then(takeTabs);
            }
        });
        if (typeof onAfterUiUpdate === 'function') onAfterUiUpdate(applyAll);
    });
});

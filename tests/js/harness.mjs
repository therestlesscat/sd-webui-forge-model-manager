/**
 * Enough of a browser, and of Gradio, to load a tab module and drive it.
 *
 * The tab scripts expect a DOM, a handful of globals the WebUI provides, and
 * markup that Gradio renders. This builds all three from the shipped files -
 * the markup is read out of the tab's own Python rather than copied, because a
 * copy goes stale the moment the markup changes and then the test passes
 * against a page that no longer exists.
 *
 * linkedom is close to a browser but not identical, and the differences that
 * matter are patched here once rather than in each suite: `select.value` and
 * `input.checked` are plain properties there, so a module's own reads never
 * see what it set.
 */
import { readFileSync } from 'fs';
import { parseHTML } from 'linkedom';
import { dirname, resolve } from 'path';
import { fileURLToPath } from 'url';

export const ROOT = process.env.MM_ROOT
    ? process.env.MM_ROOT.replace(/\\/g, '/')
    : resolve(dirname(fileURLToPath(import.meta.url)), '..', '..').replace(/\\/g, '/');

/**
 * A shared module (core.mjs, downloads.mjs, settings.mjs, ...) as the tabs loaded it.
 *
 * @param {string} name - the module's file name in javascript/shared/.
 */
export async function sharedModule(name) {
    // The tabs ask for the shared modules under the server's version, or
    // their own when it does not answer - here, with tab scripts imported
    // under none, none. The same URL is the same copy, its state the page's.
    const version = (await globalThis.window?.mmSharedVersion) || '';
    return import(`file:///${ROOT}/javascript/shared/${name}${version}`);
}

/**
 * Start a tab as the page does (shared/loading.mjs, #183): its script, the
 * shared modules it uses, then its start(scope) - once its markup is there,
 * so mount it first. Resolves once start() has been called; the scope, to
 * stop it as the page would.
 *
 * @param {string} name - as tabs.mjs knows it: queue, generations, modelManager, civitaiBrowser.
 */
export async function startTab(name) {
    const { startTab: start } = await sharedModule('loading.mjs');
    return start(name);
}

/**
 * Start shared services as a tab does (useServices in shared/loading.mjs,
 * #186): each once for the page, after what it starts in turn - for the
 * suite, as a user of its own, so no tab stopping stops them.
 *
 * @param {...string} files - their names in javascript/shared/: 'downloads.mjs'.
 */
export async function startServices(...files) {
    const { useServices } = await sharedModule('loading.mjs');
    return useServices(files, 'suite');
}

/**
 * Open a started tab at one of its entries, as another tab does (open in
 * shared/loading.mjs, #184): its tab shown, then the entry called.
 */
export async function openTab(name, entry, ...args) {
    const { open } = await sharedModule('loading.mjs');
    return open(name, entry, ...args);
}

/**
 * A tab's entries - what the others may open it at - as the loading module
 * holds them: one replaced here is what open() calls.
 *
 * @param {string} file - its script's name in javascript/tabs/: 'civitai_browser.mjs'.
 */
export async function tabEntries(file) {
    const version = (await globalThis.window?.mmSharedVersion) || '';
    return (await import(`file:///${ROOT}/javascript/tabs/${file}${version}`)).entries;
}

/**
 * Start the page as loader.mjs does: boot() asks ui-options which tabs are on
 * and built, starts those, and follows their switches as they are saved. A
 * stub's ui-options says which, in `tabs` - tabsAnswer() - else every tab is
 * taken to be on.
 */
export async function bootPage() {
    const { boot } = await sharedModule('loading.mjs');
    boot();
}

/**
 * The `tabs` of a ui-options answer (tabs.py's names): each tab named is
 * built, and on as said; any other, not built.
 */
export function tabsAnswer(on) {
    const names = ['queue', 'generations', 'model_manager', 'civitai_browser'];
    return Object.fromEntries(names.map((name) => [name, name in on ? { on: on[name], built: true }
                                                                    : { on: true, built: false }]));
}

// The WebUI's onOptionsChanged callbacks.
const optionsChanged = [];

/**
 * Apply on the WebUI's Settings page: the WebUI's `opts` take every setting
 * as the server now has it - here, these changed - and it calls each
 * onOptionsChanged callback.
 */
export function settingsPageApplied(values) {
    Object.assign(globalThis.opts, values);
    optionsChanged.forEach((callback) => callback());
}

/**
 * Press `element`, or the nearest around it that names an action: a click on
 * it, or a field's change, which the page's one listener takes (shared/calls.mjs)
 * - and what the action answered, to await. It throws what the action threw,
 * and when the listener did not act at all.
 */
export function press(element) {
    const target = element?.closest?.('[data-action]');
    if (!target) throw new Error(`nothing to press: ${String(element?.outerHTML).slice(0, 120)}`);
    const name = target.dataset.action;
    const offered = globalThis.__mmOffered;
    const action = offered?.get(name);
    if (!action) throw new Error(`${name} is not offered: its tab has not loaded`);
    let acted = false, answer, error;
    offered.set(name, (...args) => {
        acted = true;
        try { answer = action(...args); } catch (e) { error = e; }
        return answer;
    });
    try {
        const field = target.matches('input, select, textarea');
        target.dispatchEvent(new globalThis.window.Event(field ? 'change' : 'click', { bubbles: true, cancelable: true }));
    } finally {
        offered.set(name, action);
    }
    if (error) throw error;
    if (!acted) throw new Error(`the page's listener did not act on ${name}`);
    return answer;
}

/**
 * Press what the markup draws for `action`, with these data where several
 * name it: act('modelManager.selectModel', { index: 0 }) is the grid's first
 * card, as a click on it. Throws when the page draws no such thing.
 */
export function act(action, data = {}) {
    return press(named(action, data));
}

/** Tick or untick the box that names `action`, as a click on it would: its change. */
export function tick(action, on, data = {}) {
    const box = named(action, data);
    box.checked = on;
    return press(box);
}

/** Choose `value` in the picker that names `action`, as a person would: its change. */
export function choose(action, value, data = {}) {
    const picker = named(action, data);
    picker.value = String(value);
    return press(picker);
}

/**
 * Call what one part of the page offers the rest (shared/calls.mjs), as code
 * does - at once, and throwing where the page would only warn: a suite that
 * calls a name nothing offers has a mistake in it.
 */
export function call(name, ...args) {
    const offered = globalThis.__mmOffered?.get(name);
    if (!offered) throw new Error(`${name} is not offered: its tab has not loaded`);
    return offered(...args);
}

function named(action, data) {
    const all = [...globalThis.document.querySelectorAll(`[data-action="${action}"]`)];
    const found = all.find((el) => Object.entries(data).every(([key, value]) => el.dataset[key] === String(value)));
    if (!found) {
        throw new Error(`nothing on the page names ${action} ${JSON.stringify(data)}`
                        + ` (${all.length} name it: ${all.map((el) => JSON.stringify({ ...el.dataset })).join(' ')})`);
    }
    return found;
}

/**
 * A tab's markup, as its Python hands it to Gradio: read from the file, with
 * the header's gear and the downloads panel filled in from ui/header.py's own
 * templates (#85) - the version beside the gear is a stand-in.
 *
 * @param {string} tabFile - the tab's Python file, relative to the extension.
 */
export function tabMarkup(tabFile) {
    const source = readFileSync(`${ROOT}/${tabFile}`, 'utf8');
    const markup = source.match(/gr\.HTML\(\s*("""|''')([\s\S]*?)\1/);
    if (!markup) throw new Error(`could not find the tab markup in ${tabFile}`);
    const header = readFileSync(`${ROOT}/model_manager/ui/header.py`, 'utf8');
    const gear = header.match(/SETTINGS_BUTTON = """([\s\S]*?)"""/)[1];
    const panel = header.match(/def downloads_panel[\s\S]*?return f"""([\s\S]*?)"""/)[1];
    const tab = source.match(/header_actions\("(\w+)"\)/)?.[1];
    const prefix = source.match(/downloads_panel\("(\w+)"\)/)?.[1];
    let html = markup[2];
    if (tab) {
        html = html.replace('<!-- actions -->', '<span class="mm-header-actions"><a class="mm-version" href="https://example.test/CHANGELOG.md" target="_blank"'
                            + ' rel="noopener">v0.0.0</a>'
                            + `${gear.replace('{tab}', tab)}</span>`);
    }
    if (prefix) html = html.replace('<!-- downloads -->', panel.replaceAll('{p}', prefix));
    return html;
}

// A grid's layout as the stylesheet sets it (#240), which linkedom has none of.
export const GRID_LAYOUT = { width: 1000, column: 200, gap: 4, image: 300, sectionGap: 6 };

/**
 * The grids' layout, which linkedom has none of (#240). Fast places a tile
 * by the grid's width and its variables, and draws the rows near the view:
 * here a grid GRID_LAYOUT wide - 4 columns - at the top of a window tall
 * enough that every row is near. A suite moves the view with `view`, as
 * scrolling would: `{top}`, where the grid's top is on the screen, and
 * `{height}`, the window's.
 *
 * MM_TEST_GRID=Classic in the environment runs a suite on the browser's
 * grid instead: ui-options says so, whatever the suite's stand-in answers.
 */
export function gridLayout(window, view = {}) {
    const state = { top: 0, height: 100000, ...view };
    window.innerHeight = state.height;
    const isGrid = (element) => element?.classList?.contains?.('gen-grid');
    const proto = Object.getPrototypeOf(Object.getPrototypeOf(window.document.createElement('div')));
    const rect = proto.getBoundingClientRect;
    proto.getBoundingClientRect = function getBoundingClientRect() {
        if (!isGrid(this)) return rect.call(this);
        const height = parseFloat(this.style?.height) || 0;
        // A page as tall as its grid: measured shorter than the scroll, the
        // browser pulls the scroll back, as it does when a grid collapses.
        const most = Math.max(0, height - state.height);
        if (this.classList.contains('gen-placed') && -state.top > most) {
            state.top = -most;
            window.scrollY = most;
        }
        return { x: 0, y: state.top, left: 0, top: state.top, width: GRID_LAYOUT.width, height,
                 right: GRID_LAYOUT.width, bottom: state.top + height };
    };
    const vars = { '--gen-column-width': `${GRID_LAYOUT.column}px`, '--gen-gap': `${GRID_LAYOUT.gap}px`,
                   '--gen-image-height': `${GRID_LAYOUT.image}px`, '--gen-section-gap': `${GRID_LAYOUT.sectionGap}px` };
    const computed = globalThis.getComputedStyle;
    globalThis.getComputedStyle = (element) => (isGrid(element)
        ? { getPropertyValue: (name) => vars[name] || '' } : computed(element));
    window.getComputedStyle = globalThis.getComputedStyle;
    if (process.env.MM_TEST_GRID === 'Classic') classicGrid();
    return (next) => {
        Object.assign(state, next);
        window.innerHeight = state.height;
    };
}

// Every fetch a suite sets answers ui-options with Classic for both grids.
// Each is wrapped as it is set: a suite that keeps the one before and calls
// it from the next gets that one's wrapper, never the newest again.
function classicGrid() {
    const classic = (fetch) => async (url, ...rest) => {
        const answer = await fetch(url, ...rest);
        if (!String(url?.url ?? url).includes('/model-manager/ui-options')) return answer;
        const data = { ...(await answer.json()), generations_grid: 'Classic', gallery_grid: 'Classic' };
        return { ok: true, status: 200, json: async () => data, text: async () => JSON.stringify(data) };
    };
    // A suite that never asked ui-options, or whose ask failed, ran on Fast:
    // it fails here rather than pass again unseen.
    if (!classicGrid.watching) {
        classicGrid.watching = true;
        process.on('exit', () => {
            if (globalThis.document?.querySelector?.('.gen-grid.gen-placed')) {
                console.log('FAIL MM_TEST_GRID=Classic, but a grid was placed by the tab (Fast)');
                process.exitCode = 1;
            }
        });
    }
    let current = globalThis.fetch && classic(globalThis.fetch);
    Object.defineProperty(globalThis, 'fetch', {
        configurable: true,
        get: () => current,
        set: (fetch) => { current = fetch && classic(fetch); },
    });
}

/**
 * The browser's <dialog>, which linkedom (0.18.13) lacks (#292): showModal()
 * puts it on a stack - the top layer - and close() takes it off, saying so
 * with a close event. And focus, which linkedom does not track: focus() makes
 * an element the document's activeElement.
 */
function dialogStandIn(window) {
    const document = window.document;
    const layer = [];
    window.__topLayer = layer;
    const proto = Object.getPrototypeOf(Object.getPrototypeOf(document.createElement('div')));
    let focused = null;
    Object.defineProperty(document, 'activeElement', {
        configurable: true,
        get: () => (focused?.isConnected ? focused : document.body),
    });
    proto.focus = function focus() { focused = this; };
    proto.blur = function blur() { if (focused === this) focused = null; };
    Object.defineProperty(proto, 'open', {
        configurable: true,
        get() { return this.hasAttribute('open'); },
        set(value) { this.toggleAttribute('open', Boolean(value)); },
    });
    proto.showModal = function showModal() {
        if (this.hasAttribute('open')) throw new Error('InvalidStateError: the dialog is already open');
        this.setAttribute('open', '');
        layer.push(this);
    };
    proto.close = function close(returnValue) {
        if (!this.hasAttribute('open')) return;
        this.removeAttribute('open');
        if (returnValue !== undefined) this.returnValue = returnValue;
        const at = layer.indexOf(this);
        if (at >= 0) layer.splice(at, 1);
        this.dispatchEvent(new window.Event('close'));
    };
}

/**
 * Esc, as a browser delivers it with a modal dialog open: the key to what has
 * focus, bubbling; then, unless a listener held it back, cancel on the top
 * dialog, which closes it unless held back too. Returns the dialog it reached.
 */
export function escape() {
    const window = globalThis.window;
    const document = window.document;
    const target = document.activeElement && document.activeElement !== document.body
        ? document.activeElement : (window.__topLayer?.at(-1) || document.body);
    const key = new window.Event('keydown', { bubbles: true, cancelable: true });
    key.key = 'Escape';
    window.event = key;
    try {
        target.dispatchEvent(key);
    } finally {
        window.event = undefined;
    }
    // The top dialog once the key's listeners have run: one they opened is
    // the one the press would cancel, as a browser's is.
    const top = window.__topLayer?.at(-1) ?? null;
    if (key.defaultPrevented || !top) return top;
    const cancel = new window.Event('cancel', { cancelable: true });
    top.dispatchEvent(cancel);
    if (!cancel.defaultPrevented) top.close();
    return top;
}

/**
 * Answer each question as it opens (#292), where a suite stubbed confirm():
 * `pick(dialog, words)` returns the value of the button to press - as the
 * question's buttons carry it, data-value - or undefined to leave it to the
 * suite. Pressed a moment after it opens, as a person would: the question is
 * not yet the dialog module's as it shows. Returns the words of every
 * question asked, its title and message, in order.
 */
export function answerQuestions(pick) {
    const window = globalThis.window;
    const asked = [];
    const proto = Object.getPrototypeOf(Object.getPrototypeOf(window.document.createElement('div')));
    const showModal = proto.showModal;
    proto.showModal = function answered() {
        showModal.call(this);
        if (!this.classList.contains('mm-question')) return;
        const words = [this.querySelector('h3'), ...this.querySelectorAll('.mm-question-message')]
            .filter(Boolean).map((e) => e.textContent.replace(/\s+/g, ' ').trim()).join(' ');
        asked.push(words);
        const value = pick(this, words);
        if (value === undefined) return;
        setTimeout(() => this.querySelector(`[data-value="${value}"]`)
            ?.dispatchEvent(new window.Event('click', { bubbles: true })), 0);
    };
    return asked;
}

/**
 * Put a tab's markup and the globals it needs in place.
 *
 * @param {string} tabFile - the tab's Python file, relative to the extension.
 * @returns {{window: object, document: object}}
 */
export function mountTab(tabFile) {
    const { window } = parseHTML(`<!doctype html><html><body>${tabMarkup(tabFile)}</body></html>`);

    globalThis.window = window;
    globalThis.document = window.document;
    globalThis.location = { origin: 'http://localhost:7860' };
    window.location = globalThis.location;
    globalThis.URL = URL;
    globalThis.Event = window.Event;
    globalThis.MouseEvent = window.MouseEvent ?? window.Event;
    globalThis.CustomEvent = window.CustomEvent;
    // A browser global; descriptions are sanitized by parsing them with it.
    globalThis.DOMParser = window.DOMParser;
    globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
    gridLayout(window);
    dialogStandIn(window);
    globalThis.gradioApp = () => window.document;
    globalThis.onUiLoaded = (cb) => cb();
    globalThis.onAfterUiUpdate = () => {};
    globalThis.onUiUpdate = () => {};
    globalThis.opts = {};
    globalThis.onOptionsChanged = (callback) => optionsChanged.push(callback);
    globalThis.IntersectionObserver = class { observe() {} unobserve() {} disconnect() {} };
    globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
    window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
    window.scrollTo = () => {};
    // At the top, as a browser's page starts (#271). With no position, a
    // gallery going back to its top worked out NaN, asked for a scroll, and
    // waited out half a second for one that never came.
    window.scrollY = 0;
    window.pageYOffset = 0;
    window.requestAnimationFrame = (cb) => setTimeout(cb, 0);
    globalThis.requestAnimationFrame = window.requestAnimationFrame;
    window.localStorage = {
        _d: {}, getItem(k) { return this._d[k] ?? null; },
        setItem(k, v) { this._d[k] = String(v); }, removeItem(k) { delete this._d[k]; },
    };
    globalThis.localStorage = window.localStorage;

    // linkedom gives <select> a value getter with no setter, and leaves
    // `checked` as a plain property, so `:checked` never matches.
    const selectProto = Object.getPrototypeOf(window.document.createElement('select'));
    Object.defineProperty(selectProto, 'value', {
        configurable: true,
        get() {
            const chosen = Array.from(this.options).find((o) => o.hasAttribute('selected'));
            return chosen ? chosen.value : (this.options[0] ? this.options[0].value : '');
        },
        set(v) {
            Array.from(this.options).forEach((o) => {
                if (o.value === String(v)) o.setAttribute('selected', '');
                else o.removeAttribute('selected');
            });
        },
    });
    const inputProto = Object.getPrototypeOf(window.document.createElement('input'));
    Object.defineProperty(inputProto, 'checked', {
        configurable: true,
        get() { return this.hasAttribute('checked'); },
        set(on) {
            if (on) {
                if (this.type === 'radio' && this.name) {
                    this.ownerDocument
                        .querySelectorAll(`input[type="radio"][name="${this.name}"]`)
                        .forEach((other) => { if (other !== this) other.removeAttribute('checked'); });
                }
                this.setAttribute('checked', '');
            } else {
                this.removeAttribute('checked');
            }
        },
    });

    return { window, document: window.document };
}

/**
 * Send's hidden buttons (scheduler/load.py), one per tab, standing in for
 * the server: each request - a task, a generation's image, an infotext to
 * paste - is kept in the list returned, `onAsk(tab, request)` runs, and the
 * answer carries the request's nonce with what `answer(tab, request)` adds.
 * A paste leaves the prompts as Forge's paste does: the prompt and the
 * negative prompt alone, the settings line read into their controls. `delay`,
 * a number or a function of the request, holds the answer back that long.
 */
export function sendLoaders(document, { tabs = ['txt2img', 'img2img'], onAsk = null,
                                        answer = () => ({ pasted: true }), delay = 0 } = {}) {
    const asked = [];
    for (const tab of tabs) {
        document.body.insertAdjacentHTML('beforeend', `
            <div id="mm_load_${tab}_asked"><textarea></textarea></div>
            <div id="mm_load_${tab}_answer"><textarea></textarea></div>
            <button id="mm_load_${tab}"></button>`);
        document.getElementById(`mm_load_${tab}`).addEventListener('click', () => {
            const request = JSON.parse(document.querySelector(`#mm_load_${tab}_asked textarea`).value);
            asked.push({ tab, ...request });
            if (request.paste !== undefined) {
                const lines = String(request.paste).split('\n');
                if (lines.length > 1 && /^Steps: /.test(lines[lines.length - 1])) lines.pop();
                const at = lines.findIndex((line) => line.startsWith('Negative prompt: '));
                const prompt = document.querySelector(`#${tab}_prompt textarea`);
                const negative = document.querySelector(`#${tab}_neg_prompt textarea`);
                if (prompt) prompt.value = (at < 0 ? lines : lines.slice(0, at)).join('\n');
                if (negative) {
                    negative.value = at < 0 ? '' : [lines[at].slice('Negative prompt: '.length),
                                                     ...lines.slice(at + 1)].join('\n');
                }
            }
            onAsk?.(tab, request);
            const reply = { nonce: request.nonce, ...(answer(tab, request) || {}) };
            setTimeout(() => {
                document.querySelector(`#mm_load_${tab}_answer textarea`).value = JSON.stringify(reply);
            }, typeof delay === 'function' ? delay(tab, request) : delay);
        });
    }
    return asked;
}

// The most tries a wait may ask for: 400 tries of 50 ms, 20 seconds. Seven
// waits once asked for 4,000-6,000, up to 300 s each, and a broken one held a
// run for minutes before it said anything (#145). A suite waits in seconds.
export const MAX_WAIT_TRIES = 400;

// A try is five looks, 10 ms apart (#271). One look every 50 ms slept out the
// rest of it once the page was ready: 32 s summed over the suites. Windows
// wakes a timer on its clock's tick, 15.5 ms apart, so a try there takes 78
// ms, where one look took 62: no budget got shorter.
const LOOK_MS = 10;
const LOOKS_PER_TRY = 5;

/** Collect failures without stopping at the first one. */
export function checker(label = '') {
    const fails = [];
    const prefix = label ? `[${label}] ` : '';
    return {
        fails,
        check(what, got, want = true) {
            if (JSON.stringify(got) !== JSON.stringify(want)) {
                fails.push(`${prefix}${what}\n     got  ${JSON.stringify(got)}`
                         + `\n     want ${JSON.stringify(want)}`);
            }
        },
        /**
         * Wait for something to become true.
         *
         * A fixed sleep is a race that passes most of the time, which is worse
         * than failing: the work here is a chain of fetches with no event to
         * wait on.
         */
        async waitFor(what, predicate, tries = 60) {
            if (tries > MAX_WAIT_TRIES) {
                fails.push(`${prefix}waits for ${what}: ${tries} tries is more than ${MAX_WAIT_TRIES}`
                           + ' - a suite waits in seconds');
                return;
            }
            for (let n = 0; n < tries * LOOKS_PER_TRY; n++) {
                const seen = predicate();
                // A promise is true: a condition that awaits would pass at
                // once, whatever it came to.
                if (typeof seen?.then === 'function') {
                    fails.push(`${prefix}waits for ${what}: its condition answers with a promise,`
                               + ' which counts as true at once - a condition answers without awaiting');
                    return;
                }
                if (seen) return;
                await new Promise((r) => setTimeout(r, LOOK_MS));
            }
            fails.push(`${prefix}timed out waiting for ${what}`);
        },
        done() {
            console.log(fails.length
                ? fails.map((f) => 'FAIL ' + f).join('\n')
                : `All checks passed.${label ? ` (${label})` : ''}`);
            process.exit(fails.length ? 1 : 0);
        },
    };
}

/**
 * What the Civitai Browser's gallery endpoint answers for these images, as a
 * stub server gives it: page N of them - the Nth slice of 100, before the
 * switches the request names - its images through those switches, its
 * counts, which the page adds up for the banner, and a cursor to the next
 * page while there is one. The page does not
 * filter; the server does, in api/civitai.py, which browser_api_test.py holds
 * to the meanings used here. Each image needs the mm_level the server stamps;
 * the prompt floor is the server's MIN_PROMPT_LENGTH. `more` says whether a page follows
 * the last of them - Civitai has more.
 */
export function browserGalleryAnswer(href, images, extra = {}, { more = false, size = 100 } = {}) {
    const params = new URL(href, 'http://webui').searchParams;
    const hideNsfw = params.get('hide_nsfw_images') === 'true';
    const hidePromptless = params.get('hide_promptless_images') === 'true';
    const number = Number(params.get('page') || 1);
    const safe = (img) => typeof img.mm_level === 'number' && img.mm_level <= 3;
    const readable = (img) => ((img.meta || {}).prompt || '').trim().length >= 4;
    const count = (list) => {
        const nsfwKept = list.filter((img) => safe(img) || !hideNsfw);
        const shown = nsfwKept.filter((img) => readable(img) || !hidePromptless);
        // Hidden by both filters: counted apart, in neither's number.
        const both = hideNsfw && hidePromptless ? list.filter((img) => !safe(img) && !readable(img)).length : 0;
        return {
            shown,
            counts: {
                total: list.length,
                filtered: shown.length,
                hidden_nsfw: list.length - nsfwKept.length - both,
                hidden_both: both,
                promptless_total: list.filter((img) => !readable(img)).length,
                hidden_promptless: nsfwKept.length - shown.length,
                hidden: list.length - shown.length,
                nsfw_count: list.filter((img) => !safe(img) && (readable(img) || !hidePromptless)).length,
                promptless_count: nsfwKept.filter((img) => !readable(img)).length,
            },
        };
    };
    const rows = images.slice((number - 1) * size, number * size);
    const page = count(rows);
    const hasMore = images.length > number * size || more;
    return {
        success: true,
        images: page.shown,
        next_cursor: hasMore ? String(number * size) : null,
        page: { number, size, count: rows.length, shown: page.counts.filtered,
                hidden_nsfw: page.counts.hidden_nsfw, hidden_promptless: page.counts.hidden_promptless,
                hidden_both: page.counts.hidden_both, nsfw_count: page.counts.nsfw_count,
                promptless_count: page.counts.promptless_count, promptless_total: page.counts.promptless_total,
                more: hasMore, error: null },
        ...extra,
    };
}

/**
 * A stub server that answers the Model Manager's gallery pages from its own
 * details stub. The details used to carry the gallery's images; they now
 * carry its totals, and page 1 is asked for after - /model-manager/images/
 * gallery-page. A suite whose details stub still lists the images, with the
 * switches it was asked about, wraps its fetch in this: a page request is
 * put to that stub, with the same switches and the last model's path, and
 * its images come back as page 1, the only page, its note counting what the
 * stub's state says was hidden. Paging itself is gallery_test.mjs's.
 */
export function withGalleryPages(fetch) {
    let lastPath = null;
    return async (url, init) => {
        const href = String(url);
        if (href.includes('/model-manager/models/details')) {
            lastPath = new URL(href, 'http://webui').searchParams.get('path');
        }
        if (!href.includes('/model-manager/images/gallery-page')) return fetch(url, init);
        const asked = new URL(href, 'http://webui').searchParams;
        const details = new URL('/model-manager/models/details', 'http://webui');
        if (lastPath !== null) details.searchParams.set('path', lastPath);
        // So a stub counting the details it was asked for can leave these out.
        details.searchParams.set('via_page', '1');
        for (const key of ['hide_nsfw_images', 'hide_promptless_images']) {
            if (asked.get(key) !== null) details.searchParams.set(key, asked.get(key));
        }
        const body = await (await fetch(details.pathname + details.search, init)).json();
        const model = body.model || {};
        const state = model.images_state || {};
        const number = Number(asked.get('page') || 1);
        const images = number === 1 ? (model.images || []) : [];
        return { ok: true, json: async () => ({
            success: true,
            images,
            images_state: state,
            page: { number, size: 100, count: images.length + (state.hidden_nsfw || 0) + (state.hidden_promptless || 0),
                    shown: images.length, hidden_nsfw: state.hidden_nsfw || 0,
                    hidden_promptless: state.hidden_promptless || 0, more: false, error: null },
        }) };
    };
}

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
 * Put a tab's markup and the globals it needs in place.
 *
 * @param {string} tabFile - the tab's Python file, relative to the extension.
 * @returns {{window: object, document: object}}
 */
export function mountTab(tabFile) {
    const source = readFileSync(`${ROOT}/${tabFile}`, 'utf8');
    const markup = source.match(/gr\.HTML\(\s*("""|''')([\s\S]*?)\1/);
    if (!markup) throw new Error(`could not find the tab markup in ${tabFile}`);

    const { window } = parseHTML(`<!doctype html><html><body>${markup[2]}</body></html>`);

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
    globalThis.gradioApp = () => window.document;
    globalThis.onUiLoaded = (cb) => cb();
    globalThis.onAfterUiUpdate = () => {};
    globalThis.onUiUpdate = () => {};
    globalThis.opts = {};
    globalThis.IntersectionObserver = class { observe() {} unobserve() {} disconnect() {} };
    globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
    window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
    window.scrollTo = () => {};
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
            for (let n = 0; n < tries; n++) {
                if (predicate()) return;
                await new Promise((r) => setTimeout(r, 50));
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
 * stub server gives it: the images through the two switches the request
 * names, one page of them, and the counts. The page no longer filters or
 * pages - the server does, in api/images.image_list_page(), which
 * browser_api_test.py holds to the meanings used here. Each image needs the
 * mm_level the server stamps; the prompt floor is MIN_PROMPT_LENGTH.
 */
export function browserGalleryAnswer(href, images, extra = {}) {
    const params = new URL(href, 'http://webui').searchParams;
    const hideNsfw = params.get('hide_nsfw_images') === 'true';
    const hidePromptless = params.get('hide_promptless_images') === 'true';
    const offset = Number(params.get('offset') || 0);
    const limit = Number(params.get('limit') || 100);
    const safe = (img) => typeof img.mm_level === 'number' && img.mm_level <= 3;
    const readable = (img) => ((img.meta || {}).prompt || '').trim().length >= 4;
    const nsfwKept = images.filter((img) => safe(img) || !hideNsfw);
    const shown = nsfwKept.filter((img) => readable(img) || !hidePromptless);
    return {
        success: true,
        images: shown.slice(offset, offset + limit),
        next_cursor: null,
        images_state: {
            offset,
            total: images.length,
            filtered: shown.length,
            hidden_nsfw: images.length - nsfwKept.length,
            hidden_promptless: nsfwKept.length - shown.length,
            hidden: images.length - shown.length,
            nsfw_count: images.filter((img) => !safe(img) && (readable(img) || !hidePromptless)).length,
            promptless_count: nsfwKept.filter((img) => !readable(img)).length,
        },
        ...extra,
    };
}

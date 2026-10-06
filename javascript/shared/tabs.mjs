/**
 * The WebUI's tabs, found by the ids Gradio gives them (#87).
 *
 * They were found by their label, or by position - txt2img the first button,
 * img2img the second - and a translated label or a tab bar the person had
 * reordered found the wrong one, or none. Moving to another tab clicked its
 * button and waited a fixed 100 ms before drawing there: a hidden tab's grid
 * measures nothing. On a slow machine the search ran while the tab was still
 * hidden. showTab() waits for the tab itself to show.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { TIMING } = await shared('core.mjs');

// Each tab's panel: "tab_" and the id it registers with (the WebUI's
// modules/ui.py; ours in scripts/model_manager_ui.py and
// model_manager/ui/tab_model_manager.py). Gradio 4 gives its button the
// panel's id and "-button". img2imgMode is img2img's own mode, beside Sketch
// and Inpaint.
const PANELS = {
    txt2img: 'tab_txt2img',
    img2img: 'tab_img2img',
    img2imgMode: 'img2img_img2img_tab',
    queue: 'tab_queue_tab',
    generations: 'tab_generations_tab',
    modelManager: 'tab_model_manager_tab',
    civitaiBrowser: 'tab_civitai_browser_tab',
};

function find(id) {
    return (typeof gradioApp === 'function' ? gradioApp() : document).querySelector(`#${id}`);
}

/** A tab's button, or null. */
export function tabButton(tab) {
    return find(`${PANELS[tab]}-button`);
}

/**
 * The WebUI's top-level tab showing, any tab - its panel's id: tab_txt2img,
 * tab_settings - from its selected button, as the WebUI's own
 * get_uiCurrentTab reads it; null when none is.
 */
export function shownPanel() {
    const root = typeof gradioApp === 'function' ? gradioApp() : document;
    const selected = [...root.querySelectorAll('#tabs > .tab-nav > button, #tabs > button')]
        .find((button) => button.classList.contains('selected') || button.getAttribute('aria-selected') === 'true');
    return selected?.id?.replace(/-button$/, '') || null;
}

/** A top-level tab's button, by its panel's id (shownPanel), or null. */
export function panelButton(id) {
    return id ? find(`${id}-button`) : null;
}

/** Whether a tab is the one selected. */
export function tabShowing(tab) {
    const button = tabButton(tab);
    return Boolean(button && (button.classList.contains('selected') || button.getAttribute('aria-selected') === 'true'));
}

/**
 * Show a tab, and resolve once Gradio has shown its panel - it sets the
 * panel's display as it draws, looked at each frame - so what is drawn there
 * can measure itself. At once if it shows already, or has no panel to look
 * at; after TIMING.tabShown at most, so nothing waits for ever. Answers
 * whether it shows.
 */
export function showTab(tab) {
    const button = tabButton(tab);
    if (!button) {
        console.warn(`[ModelManager] The ${tab} tab was not found`);
        return Promise.resolve(false);
    }
    const panel = find(PANELS[tab]);
    const shown = () => !panel || panel.style.display !== 'none';
    button.click();
    if (shown()) return Promise.resolve(true);
    const until = Date.now() + TIMING.tabShown;
    return new Promise((resolve) => {
        const look = () => {
            if (shown() || Date.now() >= until) resolve(shown());
            else requestAnimationFrame(look);
        };
        requestAnimationFrame(look);
    });
}

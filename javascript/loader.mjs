/**
 * The extension's one script the WebUI loads (#183). It asks the server for
 * the version our modules are asked for under, then hands the page to the
 * loading module (shared/loading.mjs), which loads the tabs that are on - a
 * tab switched off is never loaded. The tabs' scripts are in
 * javascript/tabs/, which the WebUI does not list: it loaded each of them,
 * whatever its switch said.
 */

// The WebUI versions the scripts it lists and nothing else: list_scripts()
// uses os.listdir(), which does not recurse, so javascript/shared/ and
// javascript/tabs/ are never listed and never get a ?mtime. A plain import of
// them would resolve to a URL that never changed, a browser would cache it
// forever, and an export added there would be missing from the copy the
// browser held - which is a link error, so the whole script stopped running
// until someone happened to force a reload.
//
// So they are asked for with a version of their own, the newest mtime among
// them, which the server is asked for: a tab script's own version, as they
// used to take, stayed the same when only a shared file changed, and Gradio's
// file route sends no Cache-Control, so a browser could keep the copy it
// held. Every module is one URL under the one answer, and runs once, not
// once per tab. It is asked until it is answered: a page reloaded by "Apply
// and restart UI" comes back as soon as the WebUI's own routes answer, before
// the extensions' app_started adds ours, and each tab fell back to a version
// of its own - a copy of every shared module per tab, and a downloads list
// and a note pile each, for the session (#121). A dynamic import is the only
// way to build that URL at runtime, which is why this is not a plain import.
window.mmSharedVersion ||= (async () => {
    let waiting = false;
    for (;;) {
        try {
            // Not there yet - 404, the extension's app_started not run - is
            // waited out. Any other answer is taken, one without a version as
            // this script's own: still one copy.
            const response = await fetch('/model-manager/asset-version', { cache: 'no-store' });
            if (response.status !== 404) {
                const body = response.ok ? await response.json().catch(() => null) : null;
                return /^\d+$/.test(String(body?.version ?? '')) ? `?v=${body.version}`
                    : new URL(import.meta.url).search;
            }
        } catch (e) { /* the server is not answering at all */ }
        if (!waiting) {
            waiting = true;
            console.log("[ModelManager] waiting for the Model Manager's API...");
        }
        await new Promise((resolve) => setTimeout(resolve, 500));
    }
})();
const sharedVersion = await window.mmSharedVersion;
const { boot } = await import(new URL(`./shared/loading.mjs${sharedVersion}`, import.meta.url).href);
boot();

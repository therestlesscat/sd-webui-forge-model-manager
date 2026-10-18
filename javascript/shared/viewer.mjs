/**
 * The image viewer every gallery opens: an image, or a video, as large as the
 * window, ← and → (and the wheel) through the gallery's images and on into
 * its next page, the gallery's own buttons below it, and its details beside
 * it in a panel that folds away. Esc, ×, or a click around the image closes
 * it - gone from the screen as the button goes down.
 *
 * What the viewer shows is the gallery's to say, through a source:
 *
 *   count()        how many images the gallery has loaded
 *   media(i)       { url, video } - the file to show large
 *   buttons(i)     the buttons below it, as HTML
 *   details(i)     the panel, as HTML
 *   where(i)       a word on where it is, or ''
 *   views(i)       other ways to show it, optional: [{ label, url, layer, kind }],
 *                  the first the image itself - a switch under it picks one
 *                  (#34: the source an img2img generation started from, and
 *                  that source with the layer painted over it)
 *   more()         whether another page can be loaded
 *   loadMore()     loads it, adding to what count() counts
 *   onClick(e, i)  a click inside the viewer the gallery handles; true if so
 *   onClose(i)     the viewer closed on image i
 *
 * A button with data-viewer-close, or a gallery's Send (.mm-send-btn), closes
 * the viewer as it is pressed: the page goes to txt2img or img2img.
 *
 * It imports core.mjs, for its escapeHtml, under the version it was itself
 * asked for under (see the top of civitai_browser.mjs): the tabs' copy.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { escapeHtml, holdPage } = await shared('core.mjs');
const { fetchUiOptions } = await shared('ui_options.mjs');
const { ask, dialogShowing, openDialog } = await shared('dialog.mjs');

// The details panel folded away, or not: remembered in this browser.
const PANEL_KEY = 'mm_viewer_panel_closed';
// The wheel: how far it has to turn for one image, and how soon the next.
const WHEEL_STEP = 50;
const WHEEL_PAUSE_MS = 150;
// Around the image - not on it, a button or the details: a click there closes it.
const AROUND = '.mm-viewer, .mm-viewer-stage, .mm-viewer-main, .mm-viewer-frame, '
    + '.mm-viewer-bar, .mm-viewer-where';

let current = null;      // { source, index, view, element, wheel, wheelAt, pageScroll }

function readPanelClosed() {
    try {
        return localStorage.getItem(PANEL_KEY) === 'true';
    } catch (e) {
        return false;
    }
}

function writePanelClosed(closed) {
    try {
        localStorage.setItem(PANEL_KEY, String(closed));
    } catch (e) { /* this visit only */ }
}


/** Whether a viewer is open - any tab's. */
export function viewerIsOpen() {
    return !!document.querySelector('.mm-viewer');
}

/** Open the viewer on image `index` of a gallery's `source`; one open closes any other. */
export function openViewer(source, index = 0) {
    if (current) closeViewer();
    const element = document.createElement('div');
    element.className = 'mm-viewer' + (readPanelClosed() ? ' mm-viewer-collapsed' : '');
    element.setAttribute('role', 'dialog');
    element.innerHTML = `
        <div class="mm-viewer-stage">
            <button type="button" class="mm-viewer-step mm-viewer-prev" data-step="-1" title="Previous (←)">‹</button>
            <div class="mm-viewer-main">
                <div class="mm-viewer-frame"></div>
                <div class="mm-viewer-bar">
                    <span class="mm-viewer-where"></span>
                    <span class="mm-viewer-views"></span>
                    <span class="mm-viewer-actions"></span>
                </div>
            </div>
            <button type="button" class="mm-viewer-step mm-viewer-next" data-step="1" title="Next (→)">›</button>
        </div>
        <aside class="mm-viewer-panel">
            <button type="button" class="mm-viewer-panel-toggle" data-panel title="Show or hide the details"></button>
            <div class="mm-viewer-info"></div>
        </aside>
        <button type="button" class="mm-viewer-close" data-close title="Close (Esc)">×</button>`;
    element.addEventListener('pointerdown', onPress);
    element.addEventListener('click', onClick);
    element.addEventListener('wheel', onWheel, { passive: false });
    document.addEventListener('keydown', onKey);
    // Where the page was, before it is held still: a Send from the viewer
    // saves it, for the Model Manager's "Previous Position".
    const pageScroll = window.scrollY || document.documentElement?.scrollTop || 0;
    document.body.appendChild(element);
    // The page under it stays where it is: the wheel is the viewer's.
    holdPage('viewer', true);
    current = { source, index: 0, view: 0, element, wheel: 0, wheelAt: 0, pageScroll };
    showImage(index);
    return current;
}

/** Close the viewer. */
export function closeViewer() {
    if (!current) return;
    const { source, index, element } = current;
    current = null;
    element.remove();
    document.removeEventListener('keydown', onKey);
    holdPage('viewer', false);
    source.onClose?.(index);
}

/** Show image `index` - kept within what is loaded. */
export function showImage(index) {
    if (!current) return;
    const count = current.source.count();
    if (!count) {
        closeViewer();
        return;
    }
    const shown = Math.max(0, Math.min(index, count - 1));
    // Another image opens as itself, not as the view the last was left on.
    if (shown !== current.index) current.view = 0;
    current.index = shown;
    render();
}

/** Draw the image shown again: something about it changed. */
export function refreshViewer() {
    if (current) showImage(current.index);
}

/**
 * Where the page was scrolled when the viewer opened, or null with none open:
 * while it is open the page is held still, and what it says of its scroll is
 * the browser's to decide.
 */
export function viewerPageScroll() {
    return current ? current.pageScroll : null;
}

/** The image shown, or -1. */
export function viewerIndex() {
    return current ? current.index : -1;
}

/**
 * One image on - or back - loading the gallery's next page past its last.
 */
export async function stepViewer(by) {
    if (!current) return;
    const { source } = current;
    const next = current.index + by;
    if (next >= source.count() && by > 0 && source.more()) {
        await source.loadMore();
        if (!current) return;
    }
    if (next < 0 || next >= source.count()) return;
    showImage(next);
}

function render() {
    const { source, index, element } = current;
    const media = source.media(index) || {};
    const frame = element.querySelector('.mm-viewer-frame');
    // A video may be played from a copy the size the frame shows it (the
    // source's videoUrl): the frame is measured first, as it is now.
    const playUrl = media.video && source.videoUrl
        ? source.videoUrl(media, { width: frame.clientWidth, height: frame.clientHeight }) : media.url;
    const views = source.views?.(index) || [];
    const view = views[current.view] && current.view > 0 ? views[current.view] : null;
    frame.innerHTML = view ? viewHtml(view)
        : media.video
        ? `<video class="mm-viewer-image" src="${escapeHtml(playUrl)}" controls autoplay muted loop playsinline></video>`
        : `<img class="mm-viewer-image" src="${escapeHtml(media.url)}" alt="Image">`;
    element.querySelector('.mm-viewer-views').innerHTML = views.length > 1
        ? views.map((v, at) => `<button type="button" class="mm-btn ${at === current.view ? 'primary active' : 'secondary'} mm-btn-small mm-viewer-view"
                                        data-view="${at}" aria-pressed="${at === current.view}">${escapeHtml(v.label)}</button>`).join('')
        : '';
    element.querySelector('.mm-viewer-actions').innerHTML = source.buttons(index) || '';
    element.querySelector('.mm-viewer-where').textContent = source.where?.(index) || '';
    element.querySelector('.mm-viewer-info').innerHTML = source.details(index) || '';
    element.querySelector('.mm-viewer-prev').disabled = index === 0;
    element.querySelector('.mm-viewer-next').disabled = index >= source.count() - 1 && !source.more();
}

/**
 * Another view of the image: a picture, or a picture with a layer drawn over
 * it - both the same size, so each fills the frame the same way and the
 * layer lands where it was painted.
 */
function viewHtml(view) {
    if (!view.layer) return `<img class="mm-viewer-image" src="${escapeHtml(view.url)}" alt="${escapeHtml(view.label)}">`;
    return `<div class="mm-viewer-layered">
        <img class="mm-viewer-layered-image" src="${escapeHtml(view.url)}" alt="${escapeHtml(view.label)}">
        <img class="mm-viewer-layered-image mm-viewer-layer" data-layer-kind="${escapeHtml(view.kind || '')}"
             src="${escapeHtml(view.layer)}" alt="">
    </div>`;
}

function onClick(event) {
    if (!current) return;
    const target = event.target;
    const view = target.closest?.('[data-view]');
    if (view) {
        current.view = Number(view.getAttribute('data-view')) || 0;
        render();
        return;
    }
    const step = target.closest?.('[data-step]');
    if (step) {
        stepViewer(Number(step.getAttribute('data-step')));
        return;
    }
    if (target.closest?.('[data-close]')) {
        closeViewer();
        return;
    }
    if (target.closest?.('[data-panel]')) {
        writePanelClosed(current.element.classList.toggle('mm-viewer-collapsed'));
        return;
    }
    if (current.source.onClick?.(event, current.index)) return;
    // The gallery's Send goes on to txt2img or img2img: out of the way - once
    // the click is done. Send is its data-action, which the page's listener
    // runs after this one (shared/calls.mjs), and it saves where the page was
    // from the viewer, open (viewerPageScroll).
    if (target.closest?.('[data-viewer-close], .mm-send-btn')) {
        setTimeout(closeViewer, 0);
        return;
    }
    if (target.matches?.(AROUND)) closeViewer();
}

/**
 * A press around the image hides the viewer at once; the click on release
 * closes it. Closed on the click alone, it stayed on screen for as long as
 * the button was held - 65 ms in a trace (#112). It is not removed on the
 * press: the release would land on the page under it, and a card there would
 * take the click. A press that ends in no click shows it again.
 */
function onPress(event) {
    if (!current || event.button !== 0 || !event.target.matches?.(AROUND)) return;
    const { element } = current;
    element.style.opacity = '0';
    // The click comes in the same task as the release: after it, the viewer
    // is closed, or the press came to nothing.
    const settle = () => {
        window.removeEventListener('pointerup', settle);
        window.removeEventListener('pointercancel', settle);
        setTimeout(() => { element.style.opacity = ''; }, 0);
    };
    window.addEventListener('pointerup', settle);
    window.addEventListener('pointercancel', settle);
}

/**
 * The wheel steps through the images - down on, up back - one at a time
 * however hard it turns: a trackpad sends many small turns, a wheel a few
 * large ones. Over the details it scrolls them, while they have further to go.
 */
function onWheel(event) {
    if (!current) return;
    const info = event.target.closest?.('.mm-viewer-info');
    if (info && info.scrollHeight > info.clientHeight) {
        const atTop = info.scrollTop <= 0;
        const atBottom = info.scrollTop + info.clientHeight >= info.scrollHeight - 1;
        if ((event.deltaY < 0 && !atTop) || (event.deltaY > 0 && !atBottom)) return;
    }
    event.preventDefault();
    const now = Date.now();
    current.wheel += event.deltaY;
    if (Math.abs(current.wheel) < WHEEL_STEP || now - current.wheelAt < WHEEL_PAUSE_MS) return;
    const by = current.wheel > 0 ? 1 : -1;
    current.wheel = 0;
    current.wheelAt = now;
    stepViewer(by);
}

/** ← → and Esc - unless a question or a dialog over the viewer has them. */
function onKey(event) {
    if (!current || dialogShowing()) return;
    if (event.key === 'ArrowLeft') stepViewer(-1);
    else if (event.key === 'ArrowRight') stepViewer(1);
    else if (event.key === 'Escape') closeViewer();
    else return;
    event.preventDefault?.();
}

/**
 * A source for a gallery of cards - the Civitai images, in either tab - that
 * shows each card as it is: its file large, its buttons below it, the rest of
 * its text beside it. So the viewer offers what the card offers, and the two
 * cannot drift apart. A card says its file on its image column
 * (data-viewer-url, data-viewer-video); its buttons name it by its place.
 *
 * @param {object} options
 * @param {() => Element[]} options.cards - the gallery's cards, in order
 * @param {() => boolean} options.more - whether another page can be loaded
 * @param {() => Promise} options.loadMore - loads it, drawing its cards
 * @param {Function} [options.videoUrl] - (url, {width, height}, box) => what
 *     a video plays: viewerVideoUrl in media.mjs
 */
export function cardSource({ cards, more, loadMore, videoUrl }) {
    const card = (index) => cards()[index];
    return {
        count: () => cards().length,
        media: (index) => {
            const column = card(index)?.querySelector('.mm-image-left');
            return { url: column?.getAttribute('data-viewer-url') || '',
                     video: column?.getAttribute('data-viewer-video') === 'true',
                     width: Number(column?.getAttribute('data-viewer-width')) || 0,
                     height: Number(column?.getAttribute('data-viewer-height')) || 0 };
        },
        // What a video plays, from its media and the frame's size; its url when not given.
        videoUrl: videoUrl ? (media, box) => videoUrl(media.url, media, box) : null,
        buttons: (index) => card(index)?.querySelector('.mm-image-actions')?.innerHTML || '',
        details: (index) => {
            const text = card(index)?.querySelector('.mm-image-right')?.cloneNode(true);
            text?.querySelector('.mm-image-actions')?.remove();
            return text?.innerHTML || '';
        },
        where: () => '',
        more,
        loadMore,
    };
}

// ------------------------------------------------------------- deleting
/**
 * Ask to delete, and whether the image files go too: resolves to
 * { withFiles }, or null for no. Every gallery of your own images asks it.
 * The box starts as the settings say now (#107) - asked each time, so a
 * change on the Settings page counts without a reload - and unticked when
 * the server does not answer.
 */
export async function askToDelete(question, n = 1) {
    const filesToo = (await fetchUiOptions())?.generations_delete_files === true;
    const answer = await ask({
        className: 'mm-delete-dialog',
        title: question,
        tick: { label: `Also delete the image file${n === 1 ? '' : 's'} from disk`, checked: filesToo },
        note: `Otherwise only the record goes; the file${n === 1 ? ' stays' : 's stay'} where ${
            n === 1 ? 'it was' : 'they were'} saved.`,
        buttons: [{ label: 'Cancel', value: false }, { label: 'Delete', value: true, type: 'danger' }],
    });
    return answer?.value ? { withFiles: answer.ticked } : null;
}

// The window open - an image's metadata, its Resources, a task's details -
// its handle in the dialog container (#292).
let metaWindow = null;

/**
 * Show a window - an image's metadata, its Resources, a task's details - in
 * place of the last: its markup, a <dialog id="mm_meta_modal">, opened in the
 * dialog container, which closes it on Esc and a click beside it. Its × is
 * wired here, so the markup names no global - three modules draw one.
 */
export function openMetaModal(modalHtml) {
    const open = metaWindow?.element;
    if (open?.isConnected) {
        redrawMetaModal(open, modalHtml);
        return;
    }
    closeMetaModal();
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    const modal = document.getElementById('mm_meta_modal');
    if (!modal) return;
    const handle = openDialog(modal, {
        focus: () => modal.querySelector('.mm-modal-close'),
        onClose: () => {
            if (metaWindow === handle) metaWindow = null;
            modal.remove();
        },
    });
    metaWindow = handle;
    modal.querySelector('.mm-modal-close')?.addEventListener('click', closeMetaModal);
}

/**
 * A window drawn again while open - Resources filling in as Civitai answers,
 * or another window in its place: its content replaced, the <dialog> kept,
 * and with it its place on top and the page held. Closing it and opening a
 * new one moved focus at every answer. Focus goes back to the control that
 * had it, as the new content draws it again, else to the ×.
 */
function redrawMetaModal(open, modalHtml) {
    const had = open.contains(document.activeElement) ? document.activeElement : null;
    const same = had ? controlKey(had) : null;
    const holder = document.createElement('div');
    holder.innerHTML = modalHtml;
    const fresh = holder.querySelector('#mm_meta_modal');
    if (!fresh) return;
    open.replaceChildren(...fresh.childNodes);
    open.querySelector('.mm-modal-close')?.addEventListener('click', closeMetaModal);
    if (!had) return;
    const again = same ? Array.from(open.querySelectorAll(had.tagName)).find((e) => controlKey(e) === same) : null;
    (again || open.querySelector('.mm-modal-close'))?.focus?.();
}

/** What a control is, across a redraw: its tag, its data and its class, its words. */
function controlKey(element) {
    const data = Array.from(element.attributes || []).filter((a) => a.name.startsWith('data-') || a.name === 'class')
        .map((a) => `${a.name}=${a.value}`).sort().join(' ');
    return `${element.tagName} ${data} ${element.textContent.trim()}`;
}

/** Close the window open, if one is. */
export function closeMetaModal() {
    metaWindow?.close('code');
    metaWindow = null;
}

/**
 * The image viewer every gallery opens: an image, or a video, as large as the
 * window, ← and → (and the wheel) through the gallery's images and on into
 * its next page, the gallery's own buttons below it, and its details beside
 * it in a panel that folds away. Esc, ×, or a click around the image closes
 * it.
 *
 * What the viewer shows is the gallery's to say, through a source:
 *
 *   count()        how many images the gallery has loaded
 *   media(i)       { url, video } - the file to show large
 *   buttons(i)     the buttons below it, as HTML
 *   details(i)     the panel, as HTML
 *   where(i)       a word on where it is, or ''
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

// The details panel folded away, or not: remembered in this browser.
const PANEL_KEY = 'mm_viewer_panel_closed';
// The wheel: how far it has to turn for one image, and how soon the next.
const WHEEL_STEP = 50;
const WHEEL_PAUSE_MS = 150;

let current = null;      // { source, index, element, wheel, wheelAt, pageScroll }

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


/**
 * Whether a question or a dialog is showing over the page - one that is
 * shown, not one waiting in the markup: the Model Manager keeps its sync and
 * scan dialogs there, hidden, and all three tabs are one page, so asking only
 * whether one exists found them always, and the viewer's keys never worked.
 */
export function dialogShowing() {
    return Array.from(document.querySelectorAll('.mm-dialog-backdrop, .mm-modal-overlay, .gen-menu'))
        .some((element) => element.isConnected && !element.hidden && element.style.display !== 'none');
}

/**
 * Close this element on Escape, and only it: the key is taken before any
 * other listener sees it, so one Escape closes one thing. The tabs used to
 * listen on the page and close the first modal on it, whichever tab had
 * made it - and the Civitai Browser its open model as well.
 */
export function closeOnEscape(element, close) {
    const onEscape = (event) => {
        if (!element.isConnected) {
            document.removeEventListener('keydown', onEscape, true);
            return;
        }
        if (event.key !== 'Escape') return;
        event.stopPropagation();
        document.removeEventListener('keydown', onEscape, true);
        close();
    };
    document.addEventListener('keydown', onEscape, true);
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
    element.addEventListener('click', onClick);
    element.addEventListener('wheel', onWheel, { passive: false });
    document.addEventListener('keydown', onKey);
    // Where the page was, before it is held still: a Send from the viewer
    // saves it, for the Model Manager's "Previous Position".
    const pageScroll = window.scrollY || document.documentElement?.scrollTop || 0;
    document.body.appendChild(element);
    // The page under it stays where it is: the wheel is the viewer's.
    holdPage('viewer', true);
    current = { source, index: 0, element, wheel: 0, wheelAt: 0, pageScroll };
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
    current.index = Math.max(0, Math.min(index, count - 1));
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
    frame.innerHTML = media.video
        ? `<video class="mm-viewer-image" src="${escapeHtml(playUrl)}" controls autoplay muted loop playsinline></video>`
        : `<img class="mm-viewer-image" src="${escapeHtml(media.url)}" alt="Image">`;
    element.querySelector('.mm-viewer-actions').innerHTML = source.buttons(index) || '';
    element.querySelector('.mm-viewer-where').textContent = source.where?.(index) || '';
    element.querySelector('.mm-viewer-info').innerHTML = source.details(index) || '';
    element.querySelector('.mm-viewer-prev').disabled = index === 0;
    element.querySelector('.mm-viewer-next').disabled = index >= source.count() - 1 && !source.more();
}

function onClick(event) {
    if (!current) return;
    const target = event.target;
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
    // Around the image - not on it, a button or the details - closes it.
    if (target.matches?.('.mm-viewer, .mm-viewer-stage, .mm-viewer-main, .mm-viewer-frame, '
                         + '.mm-viewer-bar, .mm-viewer-where')) closeViewer();
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
 */
export function askToDelete(question, n = 1) {
    return new Promise((resolve) => {
        let answer = null;
        const backdrop = document.createElement('div');
        backdrop.className = 'mm-dialog-backdrop';
        backdrop.innerHTML = `
            <div class="mm-dialog mm-delete-dialog">
                <h3>${escapeHtml(question)}</h3>
                <label class="mm-delete-files">
                    <input type="checkbox" data-files>
                    Also delete the image file${n === 1 ? '' : 's'} from disk
                </label>
                <p class="mm-delete-note">Otherwise only the record goes; the file${n === 1 ? ' stays' : 's stay'} where ${n === 1 ? 'it was' : 'they were'} saved.</p>
                <div class="mm-dialog-buttons">
                    <button type="button" class="mm-btn secondary" data-close>Cancel</button>
                    <button type="button" class="mm-btn danger" data-confirm>Delete</button>
                </div>
            </div>`;
        const close = () => {
            if (!backdrop.isConnected) return;
            backdrop.remove();
            document.removeEventListener('keydown', onEscape, true);
            resolve(answer);
        };
        const onEscape = (event) => {
            if (event.key !== 'Escape') return;
            event.stopPropagation();
            close();
        };
        backdrop.addEventListener('click', (event) => {
            if (event.target.closest?.('[data-confirm]')) {
                answer = { withFiles: !!backdrop.querySelector('[data-files]')?.checked };
                close();
            } else if (event.target === backdrop || event.target.closest?.('[data-close]')) {
                close();
            }
        });
        document.addEventListener('keydown', onEscape, true);
        document.body.appendChild(backdrop);
    });
}

/**
 * Show a modal - an image's metadata, or its Resources - in place of the
 * last. Esc, its ×, or a click on the overlay around it closes it: wired
 * here, so the markup names no global - the tab's own and resources.mjs
 * both draw one.
 */
export function openMetaModal(modalHtml) {
    document.getElementById('mm_meta_modal')?.remove();
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    holdPage('dialog', true);
    const modal = document.getElementById('mm_meta_modal');
    if (!modal) return;
    closeOnEscape(modal, closeMetaModal);
    modal.addEventListener('click', (event) => { if (event.target === modal) closeMetaModal(); });
    modal.querySelector('.mm-modal-close')?.addEventListener('click', closeMetaModal);
}

// Close metadata modal
export function closeMetaModal() {
    const modal = document.getElementById('mm_meta_modal');
    if (modal) {
        modal.remove();
        holdPage('dialog', false);
    }
}

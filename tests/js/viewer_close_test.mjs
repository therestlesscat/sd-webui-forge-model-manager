// The image viewer, closed by a click around the image (#112). It closed on
// the click - on the release - and stayed on screen as long as the button was
// held: 65 ms in a trace, a delay you could see. A press around the image
// hides it now; the click still closes it, so the release lands on the viewer,
// not on a card under it. A press on the image or a button changes nothing,
// and a press that ends in no click shows the viewer again.
import { checker, mountTab, sharedModule } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();
globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({ success: true }) });

const { openViewer, viewerIsOpen } = await sharedModule('viewer.mjs');
const source = {
    count: () => 2, media: () => ({ url: 'https://example.invalid/1.jpeg' }),
    buttons: () => '<button type="button" class="mm-btn">Send</button>', details: () => 'details',
    more: () => false,
};
const viewer = () => document.querySelector('.mm-viewer');
const hidden = () => viewer()?.style.opacity === '0';
const fire = (target, type, init = {}) => target.dispatchEvent(
    Object.assign(new window.Event(type, { bubbles: true }), { button: 0, ...init }));
const press = (target, init) => fire(target, 'pointerdown', init);
const release = (target, type = 'pointerup') => fire(target, type);
const click = (target) => fire(target, 'click');
const settled = () => new Promise((resolve) => setTimeout(resolve, 10));

// ------------------------------------------------------- around the image
openViewer(source, 0);
const stage = viewer().querySelector('.mm-viewer-stage');
press(stage);
check('a press around the image hides the viewer at once', hidden(), true);
check('and leaves it in the page, to take the release', viewerIsOpen(), true);
release(stage);
click(stage);
await settled();
check('the click closes it', viewerIsOpen(), false);

// ------------------------------------------------- on the image, a button, the details
for (const [what, selector] of [['the image', '.mm-viewer-image'], ['a button', '.mm-viewer-actions button'],
                                ['the details', '.mm-viewer-info']]) {
    openViewer(source, 0);
    const target = viewer().querySelector(selector);
    press(target);
    check(`a press on ${what} leaves the viewer showing`, hidden(), false);
    release(target);
    click(target);
    await settled();
    check(`and a click there leaves it open`, viewerIsOpen(), true);
    viewer().querySelector('[data-close]').dispatchEvent(new window.Event('click', { bubbles: true }));
}

// ---------------------------------------------------- a press that comes to nothing
openViewer(source, 0);
press(viewer().querySelector('.mm-viewer-frame'));
check('pressed around the image: hidden', hidden(), true);
release(viewer(), 'pointercancel');
await waitFor('the viewer shown again', () => !hidden());
check('a press cancelled shows the viewer again, still open', [hidden(), viewerIsOpen()], [false, true]);

press(viewer().querySelector('.mm-viewer-frame'), { button: 2 });
check('a right-button press does not hide it', hidden(), false);

done();

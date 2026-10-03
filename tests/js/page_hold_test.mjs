// What holds the page still - body.mm-modal-open, overflow hidden - while
// something is open over it (#122). The image viewer, the metadata and
// Resources window, and the settings window each set the class, and each took
// it off when it closed, whatever else was still open: Show All opened from
// the viewer, then closed, left the page under the viewer free to scroll.
//
// Here: the page is held while anything holds it, and let go with the last;
// and nothing but core.mjs's holdPage() touches the class.
import { readdirSync, readFileSync } from 'node:fs';
import { ROOT, checker, mountTab, sharedModule } from './harness.mjs';

mountTab('model_manager/ui/tab_model_manager.py');
const { check, done } = checker();
globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({ success: true }) });

const { openViewer, closeViewer, openMetaModal } = await sharedModule('viewer.mjs');
const held = () => document.body.classList.contains('mm-modal-open');
const closeDialog = () => document.querySelector('#mm_meta_modal .mm-modal-close')
    .dispatchEvent(new window.Event('click', { bubbles: true }));
const source = {
    count: () => 1, media: () => ({ url: 'https://example.invalid/1.jpeg' }),
    buttons: () => '', details: () => '', more: () => false,
};
const dialog = (title) => `<div class="mm-modal-overlay" id="mm_meta_modal"><div class="mm-modal">
    <div class="mm-modal-header"><h3>${title}</h3><button class="mm-modal-close">&times;</button></div></div></div>`;

check('nothing open, the page is free', held(), false);
openViewer(source, 0);
check('the viewer holds it', held(), true);
for (const title of ['Image Metadata', 'Resources']) {
    openMetaModal(dialog(title));
    closeDialog();
    check(`${title} opened over the viewer and closed: the viewer still holds the page`,
          [!!document.getElementById('mm_meta_modal'), held()], [false, true]);
}
closeViewer();
check('the viewer closed, the last: the page is free again', held(), false);

openMetaModal(dialog('Image Metadata'));
check('a window on its own holds it', held(), true);
closeDialog();
check('and lets it go', held(), false);

// One place sets the class: every module of the page, read for it.
const files = [...readdirSync(`${ROOT}/javascript`).filter((f) => f.endsWith('.mjs')),
               ...readdirSync(`${ROOT}/javascript/shared`).filter((f) => f.endsWith('.mjs')).map((f) => `shared/${f}`)];
const touching = files.filter((f) => /classList\.(add|remove|toggle)\(\s*'mm-modal-open'/
    .test(readFileSync(`${ROOT}/javascript/${f}`, 'utf8')));
check('nothing but holdPage() in core.mjs sets or clears the class', touching, ['shared/core.mjs']);

done();

// A tab's introduction, for a first install (release_notes.py: kind "intro",
// audience "new"): on top of the tab's pile, with a button for each step. The
// Model Manager's opens the Sync dialog as it is, or set to Force sync on the
// files Civitai has not identified - opened, never started.
import { ROOT, checker, mountTab, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

const NOTES = [
    { id: 'pinned-tabs', version: '0.40.13', kind: 'feature', audience: 'everyone', tabs: ['model_manager'],
      title: 'Pin the models you come back to', text: 'Pinned ones get a tab.' },
    { id: 'generations', version: '0.40.0', kind: 'feature', important: true, audience: 'everyone',
      tabs: ['model_manager'], title: 'Every image you generate', text: 'Read this.' },
    { id: 'intro-model-manager', version: '0.41.4', kind: 'intro', audience: 'new', tabs: ['model_manager'],
      title: 'Getting your models in', text: 'Sync.',
      actions: [{ id: 'sync', label: 'Open Sync' }, { id: 'sync_unidentified', label: 'Open Force sync' }] },
];
const posted = [];
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (init.method === 'POST') posted.push(href);
    if (href.includes('/model-manager/notes')) return reply({ success: true, notes: NOTES });
    if (href.includes('/sync/estimate')) {
        return reply({ success: true, all: { models: 1, requests: 1, seconds: 1 }, total: 2, identified: 1,
                       unidentified: 1, asked_not_found: 0, never_asked: 1 });
    }
    return reply({ success: true });
};

await startTab('modelManager');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const top = () => document.querySelector('#mm_notes [data-note]');
const click = (element) => element?.dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the notes', () => top(), 6000);

check('the introduction is on top, ahead of even an important note, marked as information',
      [top().dataset.note, top().className, top().querySelector('.mm-banner-icon')?.textContent,
       document.querySelector('#mm_notes .mm-note-count')?.textContent],
      ['intro-model-manager', 'mm-banner mm-note mm-note-intro', 'i', '1 of 3']);
check('with a button for each step, and Dismiss',
      Array.from(top().querySelectorAll('.mm-btn')).map((b) => b.textContent.trim()),
      ['Open Sync', 'Open Force sync', 'Dismiss']);

click(top().querySelector('[data-note-action="sync"]'));
// Through the loading module, which shows the Model Manager first (#184).
await waitFor('the sync dialog', () => document.getElementById('mm_sync_dialog')?.style.display === 'flex');
check('Open Sync opens it as it is - all models, not re-reading every header',
      [document.getElementById('mm_sync_dialog')?.style.display,
       document.querySelector('input[name="mm_sync_scope"]:checked')?.value,
       document.getElementById('mm_sync_reread')?.checked],
      ['flex', 'all', false]);
click(document.getElementById('mm_sync_dialog_cancel'));

click(top().querySelector('[data-note-action="sync_unidentified"]'));
await waitFor('the sync dialog', () => document.getElementById('mm_sync_dialog')?.style.display === 'flex');
check('Open Force sync opens the sync dialog set to Force sync, on the files Civitai has not identified',
      [document.getElementById('mm_sync_dialog')?.style.display,
       document.querySelector('input[name="mm_sync_scope"]:checked')?.value,
       document.getElementById('mm_sync_force_mode')?.value],
      ['flex', 'force', 'unidentified']);
await new Promise((resolve) => setTimeout(resolve, 50));
check('and starts nothing: that is still the reader\'s click',
      posted.filter((u) => u.includes('/sync')), []);

done();

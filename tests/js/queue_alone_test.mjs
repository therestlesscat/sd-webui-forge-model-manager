// The Queue tab alone starts none of the Model Manager's work (#182): no
// sync's progress asked when the browser tab comes back into view, and no
// downloads list. It used to: the notes imported the sync's module, whose
// listener came with it, and Send's Resources dialog started the downloads
// list as it was imported. Each module's work, and start(): import_work_test.mjs.
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_queue.py');
const { check, waitFor, done } = checker();

// The Queue tab showing: it asks for its lists only then.
document.body.insertAdjacentHTML('afterbegin', `
    <div id="tabs"><button id="tab_queue_tab-button" class="selected" aria-selected="true">Queue</button></div>`);

const asked = [];
globalThis.fetch = async (url) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '').replace(/\?.*/, '');
    asked.push(path);
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (path === '/model-manager/ui-options') {
        return reply({ success: true, samplers: [], schedulers: [], generations_enabled: true, queue_enabled: true });
    }
    if (path === '/model-manager/asset-version') return reply({ success: true, version: '1' });
    return reply({ success: true, notes: [], tasks: [], total: 0, page: 1, pages: 1, downloads: [] });
};
Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' });

await import(`file:///${ROOT}/javascript/queue.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await waitFor('the Queue tab to load', () => asked.includes('/model-manager/queue/tasks'));

// The browser tab hidden, and shown again.
document.dispatchEvent(new window.Event('visibilitychange'));
await new Promise((resolve) => setTimeout(resolve, 100));

check('no sync progress asked, at load or when the page is shown again',
      asked.filter((path) => path.startsWith('/model-manager/sync')), []);
check('no downloads list asked', asked.filter((path) => path.startsWith('/model-manager/civitai/download')), []);
check('what the Queue tab does ask for, it asks', asked.includes('/model-manager/queue/tasks'), true);

done();

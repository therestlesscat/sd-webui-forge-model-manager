/**
 * The settings window, opened from the gear in either tab.
 *
 * One window for both tabs. Each tab imports this module under its own
 * ?mtime, so there are two copies of the module - but only one window: it is
 * built once and kept on `window`, as downloads() in common.mjs is.
 *
 * The settings are the WebUI's, under Settings -> Model Manager. The window
 * shows them grouped and with only what applies, and edits the same values:
 * it asks the server for them each time it opens, and a save goes through the
 * same opts.set() the Settings page uses. What it adds is presentation - the
 * sections, the short labels, the rules for what to show, and a few controls
 * that suit a setting better than the Settings page's generic ones.
 *
 * After a save it puts the new values into the Settings page's own fields as
 * well. That page loads its values once, and its Apply button sends every one
 * of them back - so without this, applying anything there would quietly undo
 * what was saved here.
 */

const K = {
    apiKey: 'model_manager_civitai_api_key',
    rate: 'model_manager_civitai_requests_per_second',
    mmPageSize: 'model_manager_page_size',
    mmCardSize: 'model_manager_card_size',
    thumbnail: 'model_manager_preview_least_nsfw',
    cbPageSize: 'model_manager_civitai_page_size',
    cbCardSize: 'model_manager_civitai_card_size',
    folder: 'model_manager_civitai_folder_template',
    minPrompts: 'model_manager_civitai_min_prompt_images',
    fillPage: 'model_manager_civitai_sfw_fill_page',
    galleryNsfw: 'model_manager_gallery_hide_nsfw',
    promptless: 'model_manager_hide_promptless_images',
    browsing: 'model_manager_image_browsing',
    detection: 'model_manager_nsfw_detection',
    percent: 'model_manager_nsfw_prompt_model_percent',
    words: 'model_manager_nsfw_prompt_words',
    threads: 'model_manager_hash_threads',
    database: 'model_manager_database_path',
};
const MODULES_PREFIX = 'model_manager_modules_';

/**
 * The sections, in order. A setting the server has that no section names is
 * shown under "Other", so a new setting is never missing from the window.
 */
const SECTIONS = [
    { title: 'Civitai connection', keys: [K.apiKey, K.rate] },
    { title: 'Model Manager', keys: [K.mmPageSize, K.mmCardSize, K.thumbnail] },
    { title: 'Civitai Browser', keys: [K.cbPageSize, K.cbCardSize, K.folder, K.minPrompts] },
    { title: 'Image gallery', keys: [K.galleryNsfw, K.promptless, K.browsing] },
    { title: 'NSFW detection', keys: [K.detection, K.percent, K.words] },
    { title: 'Sync and storage', keys: [K.threads, K.database] },
    { title: 'Send to txt2img: text encoders and VAE', collapsed: true, prefix: MODULES_PREFIX },
    { title: 'Advanced', collapsed: true, keys: [K.fillPage] },
];

/** Shorter labels than the Settings page's, which have to say which tab. */
const LABELS = {
    [K.apiKey]: 'API key',
    [K.rate]: 'Requests per second',
    [K.mmPageSize]: 'Models per page',
    [K.mmCardSize]: 'Card size',
    [K.thumbnail]: 'Card thumbnail',
    [K.cbPageSize]: 'Models per page',
    [K.cbCardSize]: 'Card size',
    [K.folder]: 'Download folder',
    [K.minPrompts]: 'Only with usable prompts: images needed',
    [K.fillPage]: "Fill every page with 'Only Show Models with SFW images'",
    [K.galleryNsfw]: 'Hide explicit images by default',
    [K.promptless]: 'Hide images with no prompt by default',
    [K.browsing]: 'Moving through the images',
    [K.detection]: 'What finds explicit images Civitai rates PG or PG-13',
    [K.percent]: 'Trained model: share of PG/PG-13 prompts to treat as X (%)',
    [K.words]: 'Extra prompt words',
    [K.threads]: 'Hashing threads',
    [K.database]: 'Database file',
};

/**
 * When a setting is shown. One that does nothing under the others' current
 * values is hidden - its value is kept, and a change to it still counts.
 */
const SHOWN_WHEN = {
    // Without a key the client runs at Civitai's anonymous rate, whatever
    // this says.
    [K.rate]: (s) => s.hasKey(),
    [K.percent]: (s) => s.value(K.detection) === 'model',
};

/** Controls that suit a setting better than its kind's default one. */
const CONTROLS = {
    [K.thumbnail]: { kind: 'choice', choices: [['The least explicit image', true], ['The most recent image', false]] },
    [K.mmCardSize]: { kind: 'cardsize' },
    [K.cbCardSize]: { kind: 'cardsize' },
    [K.folder]: { kind: 'folder' },
    [K.words]: { kind: 'words' },
    [K.database]: { kind: 'database' },
};

const CARD_PRESETS = [['Small', 160, 224], ['Medium', 200, 280], ['Large', 260, 364]];
// The card preview: one row of the tab's own cards, at the size being set.
// The gap is the grid's (.model-grid-inner). Below the smallest size a card
// is not worth drawing - typing "240" passes through "2" and "24" - and the
// cap keeps a very wide screen from asking Civitai for a page of models.
const CARD_GAP = 15;
const CARD_PREVIEW_MIN = 50;
const CARD_PREVIEW_MOST = 30;
const PREVIEW_WAIT_MS = 300;
const FOLDER_PLACEHOLDERS = ['{baseModel}', '{modelName}', '{creator}', '{modelId}'];

function esc(text) {
    return String(text ?? '').replace(/[&<>"']/g, (c) => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function same(a, b) {
    return a === b || (typeof a === 'number' && typeof b === 'number' && Math.abs(a - b) < 1e-9);
}

function parseCardSize(text) {
    const m = String(text || '').match(/^\s*(\d+)\s*[xX]\s*(\d+)\s*$/);
    return m ? [Number(m[1]), Number(m[2])] : [200, 280];
}

function createSettings() {
    let meta = null;         // the server's answer: settings, order, extras
    let draft = {};          // what the window holds, by key
    let secretTyped = null;  // a key typed into the window; null = unchanged
    let errors = {};
    let root = null;
    let saving = false;
    const previewOpen = new Set();   // card size settings showing their preview
    const previewTimers = {};
    const previewAsked = {};
    const previewDrawn = {};         // what each preview last drew, to skip redrawing it

    const state = {
        value: (key) => draft[key],
        hasKey: () => (secretTyped !== null
            ? secretTyped.trim() !== ''
            : Boolean(meta?.settings?.[K.apiKey]?.has_value)),
    };

    function changedKeys() {
        if (!meta) return [];
        return meta.order.filter((key) => {
            const s = meta.settings[key];
            if (s.kind === 'secret') return secretTyped !== null;
            return !same(draft[key], s.value);
        });
    }

    function sectionsWithKeys() {
        const placed = new Set();
        const sections = SECTIONS.map((section) => {
            const keys = section.prefix
                ? meta.order.filter((k) => k.startsWith(section.prefix))
                : section.keys.filter((k) => k in meta.settings);
            keys.forEach((k) => placed.add(k));
            return { ...section, keys };
        });
        const rest = meta.order.filter((k) => !placed.has(k));
        if (rest.length) sections.push({ title: 'Other', keys: rest });
        return sections.filter((s) => s.keys.length);
    }

    // ------------------------------------------------------------- drawing
    function build() {
        root = document.createElement('div');
        root.id = 'mm_settings';
        root.className = 'mm-dialog-backdrop mm-settings-backdrop';
        root.style.display = 'none';
        root.innerHTML = `
            <div class="mm-dialog mm-settings-dialog" role="dialog" aria-modal="true"
                 aria-labelledby="mm_settings_title">
                <div class="mm-settings-head">
                    <h3 id="mm_settings_title">Model Manager settings</h3>
                    <input type="search" class="mm-settings-search" id="mm_settings_search"
                           placeholder="Search settings" aria-label="Search settings">
                    <button type="button" class="mm-modal-close" data-act="cancel"
                            title="Close" aria-label="Close">&times;</button>
                </div>
                <div class="mm-settings-body" id="mm_settings_body"></div>
                <div class="mm-settings-foot">
                    <span class="mm-settings-status" id="mm_settings_status"></span>
                    <div class="mm-dialog-actions">
                        <button type="button" class="mm-btn" data-act="cancel">Cancel</button>
                        <button type="button" class="mm-btn primary" data-act="save"
                                id="mm_settings_save">Save</button>
                    </div>
                </div>
            </div>`;
        document.body.appendChild(root);

        root.addEventListener('click', onClick);
        root.addEventListener('input', onInput);
        root.addEventListener('change', onInput);
        root.querySelector('#mm_settings_search').addEventListener('input', applyVisibility);
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && root.style.display !== 'none') {
                e.stopPropagation();
                close();
            }
        });
    }

    function renderBody() {
        const body = root.querySelector('#mm_settings_body');
        body.innerHTML = sectionsWithKeys().map((section) => `
            <details class="mm-settings-section" ${section.collapsed ? '' : 'open'}>
                <summary class="mm-dialog-heading">${esc(section.title)}</summary>
                <div class="mm-settings-fields">
                    ${section.keys.map(renderField).join('')}
                </div>
            </details>`).join('');
        refresh();
    }

    function renderField(key) {
        const s = meta.settings[key];
        const control = { ...s, ...(CONTROLS[key] || {}) };
        const label = LABELS[key] || s.label;
        const id = `mms_${key}`;
        const inline = control.kind === 'bool';
        const head = inline ? '' : `
            <div class="mm-settings-label-row">
                <label for="${id}" class="mm-settings-label">${esc(label)}</label>
                ${resetButton(key)}
            </div>`;
        return `
            <div class="mm-settings-field" data-key="${esc(key)}"
                 data-search="${esc((label + ' ' + s.label + ' ' + (s.info || '')).toLowerCase())}">
                ${head}
                ${renderControl(key, control, id, label)}
                <div class="mm-settings-extra" data-extra="${esc(key)}"></div>
                ${s.info ? `<div class="mm-settings-help">${esc(s.info)}</div>` : ''}
                <div class="mm-settings-error" data-error="${esc(key)}"></div>
            </div>`;
    }

    function resetButton(key) {
        return `<button type="button" class="mm-settings-reset" data-reset="${esc(key)}"
                        title="Back to the default">Reset</button>`;
    }

    function renderControl(key, c, id, label) {
        const v = draft[key];
        switch (c.kind) {
        case 'bool':
            return `
                <div class="mm-settings-label-row">
                    <label class="mm-settings-check">
                        <input type="checkbox" id="${id}" data-key="${esc(key)}" ${v ? 'checked' : ''}>
                        <span class="mm-settings-label">${esc(label)}</span>
                    </label>
                    ${resetButton(key)}
                </div>`;
        case 'choice':
            return `<div class="mm-settings-choices" role="radiogroup" id="${id}">
                ${c.choices.map(([text, value], i) => `
                    <label class="mm-dialog-option">
                        <input type="radio" name="${id}" data-key="${esc(key)}" data-index="${i}"
                               ${same(value, v) ? 'checked' : ''}>
                        <span>${esc(text)}</span>
                    </label>`).join('')}
            </div>`;
        case 'number': {
            const bounds = [['minimum', 'min'], ['maximum', 'max'], ['step', 'step']]
                .filter(([name]) => c[name] !== undefined)
                .map(([name, attr]) => `${attr}="${c[name]}"`).join(' ');
            const range = c.minimum !== undefined && c.maximum !== undefined
                ? `<input type="range" class="mm-settings-range" data-key="${esc(key)}" ${bounds}
                          value="${esc(v)}" aria-label="${esc(label)}">`
                : '';
            return `<div class="mm-settings-number">${range}
                <input type="number" id="${id}" class="mm-settings-input mm-settings-num"
                       data-key="${esc(key)}" ${bounds} value="${esc(v)}"></div>`;
        }
        case 'secret':
            return `<div class="mm-settings-secret">
                <input type="password" id="${id}" class="mm-settings-input" data-key="${esc(key)}"
                       autocomplete="off" spellcheck="false"
                       placeholder="${c.has_value ? 'A key is saved - type a new one to replace it' : 'Paste your Civitai API key'}">
                <button type="button" class="mm-btn mm-btn-small" data-act="reveal">Show</button>
                ${c.has_value ? '<button type="button" class="mm-btn mm-btn-small" data-act="forget">Remove</button>' : ''}
            </div>`;
        case 'cardsize': {
            const [w, h] = parseCardSize(v);
            return `<div class="mm-settings-cardsize" id="${id}">
                <input type="number" class="mm-settings-input mm-settings-num" data-card="${esc(key)}"
                       data-side="w" min="10" max="9999" value="${w}" aria-label="Width">
                <span>&times;</span>
                <input type="number" class="mm-settings-input mm-settings-num" data-card="${esc(key)}"
                       data-side="h" min="10" max="9999" value="${h}" aria-label="Height">
                <span class="mm-settings-unit">px</span>
                ${CARD_PRESETS.map(([name, pw, ph]) => `
                    <button type="button" class="mm-btn mm-btn-small" data-card-preset="${esc(key)}"
                            data-w="${pw}" data-h="${ph}">${name}</button>`).join('')}
                <button type="button" class="mm-btn mm-btn-small" data-card-show="${esc(key)}">${
                    previewOpen.has(key) ? 'Hide preview' : 'Show preview'}</button>
            </div>
            <div class="mm-settings-card-note" data-card-note="${esc(key)}"></div>
            <div class="mm-settings-card-row" data-card-row="${esc(key)}"
                 ${previewOpen.has(key) ? '' : 'hidden'}></div>`;
        }
        case 'folder':
            return `<div class="mm-settings-folder">
                <input type="text" id="${id}" class="mm-settings-input" data-key="${esc(key)}"
                       value="${esc(v)}" spellcheck="false" placeholder="${esc(c.placeholder || '')}">
                <div class="mm-settings-chips">
                    ${FOLDER_PLACEHOLDERS.map((p) => `
                        <button type="button" class="mm-settings-chip" data-insert="${esc(p)}"
                                data-into="${esc(key)}">${esc(p)}</button>`).join('')}
                </div>
            </div>`;
        case 'words':
            return `<textarea id="${id}" class="mm-settings-input" data-key="${esc(key)}" rows="3"
                              spellcheck="false" placeholder="comma-separated words">${esc(v)}</textarea>`;
        default: {
            if (c.lines && c.lines > 1) {
                return `<textarea id="${id}" class="mm-settings-input" data-key="${esc(key)}"
                                  rows="${c.lines}">${esc(v)}</textarea>`;
            }
            return `<input type="text" id="${id}" class="mm-settings-input" data-key="${esc(key)}"
                           value="${esc(v)}" spellcheck="false" placeholder="${esc(c.placeholder || '')}">`;
        }
        }
    }

    // ------------------------------------------------------ card preview
    function schedulePreview(key) {
        clearTimeout(previewTimers[key]);
        previewTimers[key] = setTimeout(() => drawPreview(key), PREVIEW_WAIT_MS);
    }

    /**
     * One row of the tab's own cards at the size being set: as many as fit
     * across, never a second row. The tab draws them, from the models it
     * already has, and asks for more - exactly as many as fit - only when it
     * has too few.
     */
    async function drawPreview(key) {
        const row = root.querySelector(`[data-card-row="${key}"]`);
        const note = root.querySelector(`[data-card-note="${key}"]`);
        if (!row || !previewOpen.has(key)) return;
        const [w, h] = parseCardSize(draft[key]);
        if (w < CARD_PREVIEW_MIN || h < CARD_PREVIEW_MIN) {
            row.innerHTML = '';
            note.textContent = `Too small to preview: a card has to be at least ${CARD_PREVIEW_MIN} × ${CARD_PREVIEW_MIN}.`;
            return;
        }
        row.style.setProperty('--mm-preview-card-width', `${w}px`);
        row.style.setProperty('--mm-preview-card-height', `${h}px`);
        const count = Math.min(CARD_PREVIEW_MOST,
                               Math.max(1, Math.floor((row.clientWidth + CARD_GAP) / (w + CARD_GAP))));
        const drawing = `${w}x${h}:${count}`;
        if (previewDrawn[key] === drawing && row.childElementCount) return;
        previewDrawn[key] = drawing;
        const draw = window.mmCardPreviews?.[key];
        if (!draw) {
            note.textContent = 'This tab has not loaded yet, so there are no cards to preview.';
            return;
        }
        const asked = (previewAsked[key] || 0) + 1;
        previewAsked[key] = asked;
        note.textContent = '';
        try {
            const cards = await draw(count);
            if (asked !== previewAsked[key]) return;
            row.innerHTML = cards || '';
            note.textContent = cards ? '' : 'No models to preview.';
        } catch (e) {
            if (asked !== previewAsked[key]) return;
            delete previewDrawn[key];
            note.textContent = `Could not load models for the preview: ${e.message}`;
        }
    }

    // ------------------------------------------------ what depends on values
    let folderAsked = 0;

    function refreshExtras() {
        previewOpen.forEach((key) => schedulePreview(key));

        const words = root.querySelector(`[data-extra="${K.words}"]`);
        if (words) {
            const bundled = meta.bundled_nsfw_words;
            words.textContent = (bundled ? `These add to the ${bundled} words that come with the extension. ` : '')
                + 'They apply with either detection, the trained model included.';
        }

        const db = root.querySelector(`[data-extra="${K.database}"]`);
        if (db) {
            const inUse = meta.database_in_use || '';
            const wanted = (draft[K.database] || '').trim();
            const differs = wanted ? wanted.toLowerCase() !== inUse.toLowerCase()
                                   : meta.settings[K.database].value.trim() !== '';
            db.innerHTML = `In use: <code>${esc(inUse || 'unknown')}</code>`
                + (differs ? ' <span class="mm-settings-badge">Takes effect after a restart</span>' : '');
        }

        const folder = root.querySelector(`[data-extra="${K.folder}"]`);
        if (folder) {
            const asked = ++folderAsked;
            fetch(`/model-manager/settings/folder-example?template=${encodeURIComponent(draft[K.folder] || '')}`)
                .then((r) => r.json())
                .then((data) => {
                    if (asked !== folderAsked || !data?.success) return;
                    folder.innerHTML = `A model would be saved under: <code>&lt;its type's folder&gt;${
                        data.subfolder ? esc('\\' + data.subfolder.replace(/\//g, '\\')) : ''}</code>`
                        + (data.unknown.length
                            ? ` <span class="mm-settings-warning">Not a placeholder: ${esc(data.unknown.join(', '))}</span>`
                            : '');
                })
                .catch(() => {});
        }
    }

    function refreshModified() {
        root.querySelectorAll('.mm-settings-field').forEach((field) => {
            const key = field.dataset.key;
            const s = meta.settings[key];
            const atDefault = s.kind === 'secret'
                ? !state.hasKey()
                : same(draft[key], s.default);
            const reset = field.querySelector('.mm-settings-reset');
            if (reset) reset.hidden = atDefault || s.kind === 'secret';
            field.classList.toggle('mm-settings-changed', changedKeys().includes(key));
            const error = field.querySelector('.mm-settings-error');
            error.textContent = errors[key] || '';
        });
    }

    function applyVisibility() {
        const query = (root.querySelector('#mm_settings_search').value || '').trim().toLowerCase();
        root.querySelectorAll('.mm-settings-section').forEach((section) => {
            let any = false;
            section.querySelectorAll('.mm-settings-field').forEach((field) => {
                const rule = SHOWN_WHEN[field.dataset.key];
                const shown = (!rule || rule(state))
                    && (!query || field.dataset.search.includes(query));
                field.hidden = !shown;
                any = any || shown;
            });
            section.hidden = !any;
            if (query && any) section.open = true;
        });
    }

    function refreshFooter() {
        const n = changedKeys().length;
        root.querySelector('#mm_settings_status').textContent = saving ? 'Saving...'
            : (n ? `${n} unsaved change${n === 1 ? '' : 's'}` : '');
        root.querySelector('#mm_settings_save').disabled = saving || n === 0;
    }

    function refresh() {
        refreshExtras();
        refreshModified();
        applyVisibility();
        refreshFooter();
    }

    /** Put the draft back into the controls of one setting, after a reset or a preset. */
    function redrawField(key) {
        const field = root.querySelector(`.mm-settings-field[data-key="${key}"]`);
        if (field) field.outerHTML = renderField(key);
        refresh();
    }

    // ------------------------------------------------------------- events
    function onInput(e) {
        const t = e.target;
        if (t.id === 'mm_settings_search') return;
        const card = t.dataset.card;
        if (card) {
            const [w, h] = parseCardSize(draft[card]);
            const n = Math.round(Number(t.value));
            if (!Number.isFinite(n) || n <= 0) return;
            draft[card] = t.dataset.side === 'w' ? `${n}x${h}` : `${w}x${n}`;
            refresh();
            return;
        }
        const key = t.dataset.key;
        if (!key || !meta.settings[key]) return;
        const s = { ...meta.settings[key], ...(CONTROLS[key] || {}) };
        if (s.kind === 'secret') {
            secretTyped = t.value;
        } else if (s.kind === 'bool') {
            draft[key] = t.checked;
        } else if (s.kind === 'choice') {
            if (!t.checked) return;
            draft[key] = s.choices[Number(t.dataset.index)][1];
        } else if (s.kind === 'number') {
            if (t.value === '') return;
            draft[key] = Number(t.value);
            // The slider and the box beside it say the same number.
            root.querySelectorAll(`[data-key="${key}"]`).forEach((other) => {
                if (other !== t) other.value = t.value;
            });
        } else {
            draft[key] = t.value;
        }
        delete errors[key];
        refresh();
    }

    function onClick(e) {
        const t = e.target.closest('button, [data-act]') || e.target;
        if (e.target === root) {             // the backdrop
            close();
            return;
        }
        const act = t.dataset?.act;
        if (act === 'cancel') close();
        else if (act === 'save') save();
        else if (act === 'reveal') {
            const input = t.parentElement.querySelector('input');
            input.type = input.type === 'password' ? 'text' : 'password';
            t.textContent = input.type === 'password' ? 'Show' : 'Hide';
        } else if (act === 'forget') {
            secretTyped = '';
            const input = t.parentElement.querySelector('input');
            input.value = '';
            input.placeholder = 'The key will be removed when you save';
            refresh();
        } else if (t.dataset?.reset) {
            const key = t.dataset.reset;
            draft[key] = meta.settings[key].default;
            delete errors[key];
            redrawField(key);
        } else if (t.dataset?.cardShow) {
            const key = t.dataset.cardShow;
            const row = root.querySelector(`[data-card-row="${key}"]`);
            if (previewOpen.has(key)) {
                previewOpen.delete(key);
                row.hidden = true;
                row.innerHTML = '';
                root.querySelector(`[data-card-note="${key}"]`).textContent = '';
                t.textContent = 'Show preview';
            } else {
                previewOpen.add(key);
                row.hidden = false;
                t.textContent = 'Hide preview';
                drawPreview(key);
            }
        } else if (t.dataset?.cardPreset) {
            draft[t.dataset.cardPreset] = `${t.dataset.w}x${t.dataset.h}`;
            redrawField(t.dataset.cardPreset);
        } else if (t.dataset?.insert) {
            const key = t.dataset.into;
            const input = root.querySelector(`input[data-key="${key}"]`);
            const at = input.selectionStart ?? input.value.length;
            const end = input.selectionEnd ?? at;
            input.value = input.value.slice(0, at) + t.dataset.insert + input.value.slice(end);
            draft[key] = input.value;
            input.focus();
            const caret = at + t.dataset.insert.length;
            input.setSelectionRange?.(caret, caret);
            refresh();
        }
    }

    // ------------------------------------------------------ opening, saving
    function take(answer) {
        meta = answer;
        draft = {};
        meta.order.forEach((key) => {
            if (meta.settings[key].kind !== 'secret') draft[key] = meta.settings[key].value;
        });
        secretTyped = null;
        errors = {};
    }

    async function open() {
        if (!root) build();
        root.style.display = 'flex';
        document.body.classList.add('mm-modal-open');
        const body = root.querySelector('#mm_settings_body');
        body.innerHTML = '<div class="mm-settings-loading">Loading settings...</div>';
        root.querySelector('#mm_settings_search').value = '';
        try {
            const response = await fetch('/model-manager/settings', { cache: 'no-store' });
            const answer = await response.json();
            if (!answer.success) throw new Error(answer.error || 'the server did not say why');
            take(answer);
            renderBody();
        } catch (e) {
            meta = null;
            body.innerHTML = `<div class="mm-settings-error">Could not read the settings: ${esc(e.message)}</div>`;
            root.querySelector('#mm_settings_save').disabled = true;
        }
    }

    function close() {
        const n = changedKeys().length;
        if (n && !window.confirm(`Discard ${n} unsaved change${n === 1 ? '' : 's'}?`)) return;
        root.style.display = 'none';
        document.body.classList.remove('mm-modal-open');
    }

    async function save() {
        const keys = changedKeys();
        if (!keys.length || saving) return;
        const values = {};
        keys.forEach((key) => {
            values[key] = meta.settings[key].kind === 'secret' ? secretTyped.trim() : draft[key];
        });
        saving = true;
        refreshFooter();
        try {
            const response = await fetch('/model-manager/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ values }),
            });
            const answer = await response.json();
            if (!answer.success) {
                errors = answer.errors || {};
                if (!answer.errors) {
                    root.querySelector('#mm_settings_status').textContent = `Not saved: ${answer.error}`;
                }
                return;
            }
            syncSettingsPage(values);
            take(answer);
            root.style.display = 'none';
            document.body.classList.remove('mm-modal-open');
            window.dispatchEvent(new CustomEvent('mm-settings-saved', {
                detail: { changed: answer.changed || [], settings: answer.settings },
            }));
        } catch (e) {
            root.querySelector('#mm_settings_status').textContent = `Not saved: ${e.message}`;
            return;
        } finally {
            saving = false;
            if (meta && root.style.display !== 'none') refresh();
        }
    }

    return { open, close };
}

// ------------------------------------------------------------------------
// The Settings page's own fields

function fire(el, type) {
    const event = new Event(type, { bubbles: true });
    Object.defineProperty(event, 'target', { value: el });
    el.dispatchEvent(event);
}

/**
 * Put saved values into the Settings page's fields, as if typed there, so its
 * Apply button sends them rather than what the page loaded with. Gradio keeps
 * its own copy of each value and updates it from the input and change events,
 * which is what `updateInput` in the WebUI's ui.js relies on too.
 */
export function syncSettingsPage(values) {
    const app = typeof gradioApp === 'function' ? gradioApp() : document;
    Object.entries(values).forEach(([key, value]) => {
        const holder = app.querySelector(`#setting_${key}`);
        if (!holder) return;
        if (typeof value === 'boolean') {
            const box = holder.querySelector('input[type="checkbox"]');
            if (box && box.checked !== value) {
                box.checked = value;
                fire(box, 'input');
                fire(box, 'change');
            }
            return;
        }
        const radios = Array.from(holder.querySelectorAll('input[type="radio"]'));
        if (radios.length) {
            const wanted = radios.find((r) => r.value === String(value));
            if (wanted && !wanted.checked) {
                wanted.checked = true;
                fire(wanted, 'input');
                fire(wanted, 'change');
            }
            return;
        }
        holder.querySelectorAll('input[type="number"], input[type="range"], input[type="text"], '
                                + 'input[type="password"], input:not([type]), textarea')
            .forEach((input) => {
                if (input.value === String(value)) return;
                input.value = String(value);
                fire(input, 'input');
                fire(input, 'change');
            });
    });
}

/** The one settings window, for whichever tab asks first. */
export function settingsWindow() {
    if (!window.mmSettingsWindow) window.mmSettingsWindow = createSettings();
    return window.mmSettingsWindow;
}

window.mmOpenSettings ||= () => settingsWindow().open();

/**
 * The settings window, opened from the gear in either tab.
 *
 * One window for both tabs: the tabs share this module's one copy (#53).
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

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { TIMING, escapeHtml, holdPage } = await shared('core.mjs');
const { ready, call } = await shared('calls.mjs');

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
    pageSize: 'model_manager_gallery_page_size',
    galleryOriginals: 'model_manager_gallery_originals',
    cardOriginals: 'model_manager_card_originals',
    recordGenerations: 'model_manager_record_generations',
    generationsNsfw: 'model_manager_generations_hide_nsfw',
    queueEnabled: 'model_manager_queue_enabled',
    mmEnabled: 'model_manager_model_manager_enabled',
    cbEnabled: 'model_manager_civitai_browser_enabled',
    queueInputs: 'model_manager_queue_inputs_dir',
    queueAskAbove: 'model_manager_queue_ask_above',
    detection: 'model_manager_nsfw_detection',
    percent: 'model_manager_nsfw_prompt_model_percent',
    words: 'model_manager_nsfw_prompt_words',
    threads: 'model_manager_hash_threads',
    database: 'model_manager_database_path',
    checkUpdates: 'model_manager_check_updates',
};
const MODULES_PREFIX = 'model_manager_modules_';

/**
 * The sections, in order. A setting the server has that no section names is
 * shown under "Other", so a new setting is never missing from the window.
 */
// Every section starts collapsed; opened from a tab's gear, the ones that tab
// uses are open (`tabs`), and a note's button opens the one it is about, by
// its id (`section` in model_manager/data/release_notes.json). A section is
// shown while a tab it serves is on (`shownWith`; none: always, #185) - not
// its `tabs`: the connection serves Generations' Send too, and storage holds
// the database every tab uses.
const SECTIONS = [
    { id: 'tabs', title: 'Tabs', tabs: [], keys: [K.queueEnabled, K.recordGenerations, K.mmEnabled, K.cbEnabled] },
    { id: 'connection', title: 'Civitai connection', tabs: ['model_manager', 'civitai_browser'],
      shownWith: ['model_manager', 'civitai_browser', 'generations'], keys: [K.apiKey, K.rate] },
    { id: 'model_manager', title: 'Model Manager', tabs: ['model_manager'], shownWith: ['model_manager'],
      keys: [K.mmPageSize, K.mmCardSize, K.thumbnail] },
    { id: 'civitai_browser', title: 'Civitai Browser', tabs: ['civitai_browser'], shownWith: ['civitai_browser'],
      keys: [K.cbPageSize, K.cbCardSize, K.folder, K.minPrompts] },
    { id: 'gallery', title: 'Image gallery', tabs: ['model_manager', 'civitai_browser'],
      shownWith: ['model_manager', 'civitai_browser'], keys: [K.galleryNsfw, K.promptless, K.pageSize, K.galleryOriginals, K.cardOriginals] },
    { id: 'generations', title: 'Your generations', tabs: ['model_manager', 'generations'],
      shownWith: ['generations'], keys: [K.generationsNsfw] },
    { id: 'queue', title: 'Queue', tabs: ['queue'], shownWith: ['queue'], keys: [K.queueInputs, K.queueAskAbove] },
    { id: 'nsfw', title: 'NSFW detection', tabs: ['model_manager', 'civitai_browser', 'generations'],
      shownWith: ['model_manager', 'civitai_browser', 'generations'], keys: [K.detection, K.percent, K.words] },
    { id: 'storage', title: 'Sync and storage', tabs: ['model_manager'], keys: [K.threads, K.database] },
    { id: 'modules', title: 'Send to txt2img: text encoders and VAE', tabs: [], prefix: MODULES_PREFIX,
      intro: 'Automatic is what Send to txt2img picks by itself. Choose a file to use that one '
             + 'instead. A file chosen for one model is filled in for the others that use it, '
             + 'where nothing is chosen yet.' },
    { id: 'updates', title: 'Updates', tabs: [], keys: [K.checkUpdates] },
    { id: 'advanced', title: 'Advanced', tabs: ['civitai_browser'], shownWith: ['civitai_browser'], keys: [K.fillPage] },
];

// Each tab's switch, by the name the sections give it.
const TAB_SWITCHES = { queue: K.queueEnabled, generations: K.recordGenerations, model_manager: K.mmEnabled,
                       civitai_browser: K.cbEnabled };

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
    [K.pageSize]: 'Images per page',
    [K.galleryOriginals]: 'Gallery images: load as uploaded, not resized',
    [K.cardOriginals]: 'Model cards: load as uploaded, not resized',
    [K.recordGenerations]: 'Your generations: record the images you generate, and show them',
    [K.generationsNsfw]: 'Generations tab: hide explicit images by default',
    [K.queueEnabled]: 'Queue: the Queue button beside Generate, and the Queue tab',
    [K.mmEnabled]: 'Model Manager tab',
    [K.cbEnabled]: 'Civitai Browser tab',
    [K.queueInputs]: 'Folder for the images a task needs',
    [K.queueAskAbove]: 'Ask "Generate N images?" above this many images',
    [K.detection]: 'What finds explicit images Civitai rates PG or PG-13',
    [K.percent]: 'Trained model: share of PG/PG-13 prompts to treat as X (%)',
    [K.words]: 'Extra prompt words',
    [K.threads]: 'Hashing threads',
    [K.database]: 'Database file',
    [K.checkUpdates]: 'Check for a new version',
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
    // No Generations tab while nothing is recorded.
    [K.generationsNsfw]: (s) => s.value(K.recordGenerations) !== false,
    // Nothing is queued while the queue is off.
    [K.queueInputs]: (s) => s.value(K.queueEnabled) !== false,
    [K.queueAskAbove]: (s) => s.value(K.queueEnabled) !== false,
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
const FOLDER_PLACEHOLDERS = ['{baseModel}', '{modelName}', '{creator}', '{modelId}'];

function same(a, b) {
    return a === b || (typeof a === 'number' && typeof b === 'number' && Math.abs(a - b) < 1e-9);
}

function parseCardSize(text) {
    const m = String(text || '').match(/^\s*(\d+)\s*[xX]\s*(\d+)\s*$/);
    return m ? [Number(m[1]), Number(m[2])] : [200, 280];
}

function createSettings() {
    let meta = null;         // the server's answer: settings, order, extras
    let openedFor = {};      // the tab, or the one section, open() was asked for
    let draft = {};          // what the window holds, by key
    let secretTyped = null;  // a key typed into the window; null = unchanged
    let errors = {};
    let root = null;
    let saving = false;
    // The text encoder and VAE table, by setting: forge_modules' description
    // of each preset this WebUI has, with the window's edits. null when the
    // server could not describe them, and the settings show as text instead.
    let modules = null;
    const previewOpen = new Set();   // card size settings showing their preview
    const previewTimers = {};
    const previewAsked = {};
    const previewDrawn = {};         // what each preview last drew, to skip redrawing it
    let keyTests = 0;                // a key test's answer is shown only if nothing changed since

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
            let keys = section.prefix
                ? meta.order.filter((k) => k.startsWith(section.prefix))
                : section.keys.filter((k) => k in meta.settings);
            keys.forEach((k) => placed.add(k));
            // A preset this WebUI does not have is left out, not offered.
            if (section.prefix === MODULES_PREFIX && modules) keys = keys.filter((k) => k in modules);
            return { ...section, keys };
        });
        const rest = meta.order.filter((k) => !placed.has(k));
        if (rest.length) sections.push({ id: 'other', title: 'Other', tabs: [], keys: rest });
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
        const onKey = (e) => {
            if (e.key === 'Escape' && root.style.display !== 'none') {
                e.stopPropagation();
                close();
            }
        };
        // On the document: through the service's scope, gone with it (#186).
        if (settingsScope) settingsScope.listen(document, 'keydown', onKey);
        else document.addEventListener('keydown', onKey);
    }

    function renderBody() {
        const body = root.querySelector('#mm_settings_body');
        const shown = (section) => (openedFor.section ? section.id === openedFor.section
            : (section.tabs || []).includes(openedFor.tab));
        body.innerHTML = whatsNewSection() + sectionsWithKeys().map((section) => `
            <details class="mm-settings-section" data-section="${escapeHtml(section.id)}" ${shown(section) ? 'open' : ''}>
                <summary class="mm-dialog-heading">${escapeHtml(section.title)}</summary>
                ${section.intro && modules ? `<div class="mm-settings-help">${escapeHtml(section.intro)}</div>` : ''}
                <div class="mm-settings-fields">
                    ${section.keys.map(renderField).join('')}
                </div>
            </details>`).join('');
        refresh();
        loadWhatsNew();
        if (openedFor.section) body.querySelector(`[data-section="${openedFor.section}"]`)?.scrollIntoView?.({ block: 'start' });
    }

    // "What's new": every note to the user that applies here, dismissed or
    // not, newest first (model_manager/release_notes.py) - where a note
    // dismissed in a tab can be read again. Not a setting: the search leaves
    // it out.
    function whatsNewSection() {
        return `
            <details class="mm-settings-section" data-whats-new>
                <summary class="mm-dialog-heading">What's new</summary>
                <div class="mm-settings-fields" id="mm_settings_notes">Loading...</div>
            </details>`;
    }

    async function loadWhatsNew() {
        let notes = null;
        try {
            const data = await (await fetch('/model-manager/notes')).json();
            if (data && data.success) notes = data.notes || [];
        } catch (e) { /* said below */ }
        const box = root.querySelector('#mm_settings_notes');
        if (!box) return;
        if (!notes) {
            box.textContent = 'The notes could not be read.';
            return;
        }
        const versions = [...new Set(notes.map((n) => n.version))];
        box.innerHTML = versions.map((version) => `
            <div class="mm-settings-notes-version">${escapeHtml(version)}</div>
            ${notes.filter((n) => n.version === version).map((n) => `
                <div class="mm-settings-note" data-settings-note="${escapeHtml(n.id)}">
                    <strong>${n.important ? '[Important] ' : ''}${escapeHtml(n.title)}</strong>
                    <div class="mm-settings-help">${escapeHtml(n.text)}</div>
                </div>`).join('')}`).join('') || 'Nothing yet.';
    }

    function renderField(key) {
        if (modules?.[key]) return renderModules(key);
        const s = meta.settings[key];
        const control = { ...s, ...(CONTROLS[key] || {}) };
        const label = LABELS[key] || s.label;
        const id = `mms_${key}`;
        const inline = control.kind === 'bool';
        const head = inline ? '' : `
            <div class="mm-settings-label-row">
                <label for="${id}" class="mm-settings-label">${escapeHtml(label)}</label>
                ${resetButton(key)}
            </div>`;
        return `
            <div class="mm-settings-field" data-key="${escapeHtml(key)}"
                 data-search="${escapeHtml((label + ' ' + s.label + ' ' + (s.info || '')).toLowerCase())}">
                ${head}
                ${renderControl(key, control, id, label)}
                <div class="mm-settings-extra" data-extra="${escapeHtml(key)}"></div>
                ${s.info ? `<div class="mm-settings-help">${escapeHtml(s.info)}</div>` : ''}
                <div class="mm-settings-error" data-error="${escapeHtml(key)}"></div>
            </div>`;
    }

    function resetButton(key) {
        return `<button type="button" class="mm-settings-reset" data-reset="${escapeHtml(key)}"
                        title="Back to the default">Reset</button>`;
    }

    function renderControl(key, c, id, label) {
        const v = draft[key];
        switch (c.kind) {
        case 'bool':
            return `
                <div class="mm-settings-label-row">
                    <label class="mm-settings-check">
                        <input type="checkbox" id="${id}" data-key="${escapeHtml(key)}" ${v ? 'checked' : ''}>
                        <span class="mm-settings-label">${escapeHtml(label)}</span>
                    </label>
                    ${resetButton(key)}
                </div>`;
        case 'choice':
            return `<div class="mm-settings-choices" role="radiogroup" id="${id}">
                ${c.choices.map(([text, value], i) => `
                    <label class="mm-dialog-option">
                        <input type="radio" name="${id}" data-key="${escapeHtml(key)}" data-index="${i}"
                               ${same(value, v) ? 'checked' : ''}>
                        <span>${escapeHtml(text)}</span>
                    </label>`).join('')}
            </div>`;
        case 'number': {
            const bounds = [['minimum', 'min'], ['maximum', 'max'], ['step', 'step']]
                .filter(([name]) => c[name] !== undefined)
                .map(([name, attr]) => `${attr}="${c[name]}"`).join(' ');
            const range = c.minimum !== undefined && c.maximum !== undefined
                ? `<input type="range" class="mm-settings-range" data-key="${escapeHtml(key)}" ${bounds}
                          value="${escapeHtml(v)}" aria-label="${escapeHtml(label)}">`
                : '';
            return `<div class="mm-settings-number">${range}
                <input type="number" id="${id}" class="mm-settings-input mm-settings-num"
                       data-key="${escapeHtml(key)}" ${bounds} value="${escapeHtml(v)}"></div>`;
        }
        case 'secret':
            return `<div class="mm-settings-secret">
                <input type="password" id="${id}" class="mm-settings-input" data-key="${escapeHtml(key)}"
                       autocomplete="off" spellcheck="false"
                       placeholder="${c.has_value ? 'A key is saved - type a new one to replace it' : 'Paste your Civitai API key'}">
                <button type="button" class="mm-btn mm-btn-small" data-act="reveal">Show</button>
                <button type="button" class="mm-btn mm-btn-small" data-act="test-key"
                        title="Ask Civitai whether it takes this key">Test</button>
                ${c.has_value ? '<button type="button" class="mm-btn mm-btn-small" data-act="forget">Remove</button>' : ''}
            </div>
            <div class="mm-settings-key-test" id="mm_settings_key_test" role="status"></div>`;
        case 'cardsize': {
            const [w, h] = parseCardSize(v);
            return `<div class="mm-settings-cardsize" id="${id}">
                <input type="number" class="mm-settings-input mm-settings-num" data-card="${escapeHtml(key)}"
                       data-side="w" min="10" max="9999" value="${w}" aria-label="Width">
                <span>&times;</span>
                <input type="number" class="mm-settings-input mm-settings-num" data-card="${escapeHtml(key)}"
                       data-side="h" min="10" max="9999" value="${h}" aria-label="Height">
                <span class="mm-settings-unit">px</span>
                ${CARD_PRESETS.map(([name, pw, ph]) => `
                    <button type="button" class="mm-btn mm-btn-small" data-card-preset="${escapeHtml(key)}"
                            data-w="${pw}" data-h="${ph}">${name}</button>`).join('')}
                <button type="button" class="mm-btn mm-btn-small" data-card-show="${escapeHtml(key)}">${
                    previewOpen.has(key) ? 'Hide preview' : 'Show preview'}</button>
            </div>
            <div class="mm-settings-card-note" data-card-note="${escapeHtml(key)}"></div>
            <div class="mm-settings-card-row" data-card-row="${escapeHtml(key)}"
                 ${previewOpen.has(key) ? '' : 'hidden'}></div>`;
        }
        case 'folder':
            return `<div class="mm-settings-folder">
                <input type="text" id="${id}" class="mm-settings-input" data-key="${escapeHtml(key)}"
                       value="${escapeHtml(v)}" spellcheck="false" placeholder="${escapeHtml(c.placeholder || '')}">
                <div class="mm-settings-chips">
                    ${FOLDER_PLACEHOLDERS.map((p) => `
                        <button type="button" class="mm-settings-chip" data-insert="${escapeHtml(p)}"
                                data-into="${escapeHtml(key)}">${escapeHtml(p)}</button>`).join('')}
                </div>
            </div>`;
        case 'words':
            return `<textarea id="${id}" class="mm-settings-input" data-key="${escapeHtml(key)}" rows="3"
                              spellcheck="false" placeholder="comma-separated words">${escapeHtml(v)}</textarea>`;
        default: {
            if (c.lines && c.lines > 1) {
                return `<textarea id="${id}" class="mm-settings-input" data-key="${escapeHtml(key)}"
                                  rows="${c.lines}">${escapeHtml(v)}</textarea>`;
            }
            return `<input type="text" id="${id}" class="mm-settings-input" data-key="${escapeHtml(key)}"
                           value="${escapeHtml(v)}" spellcheck="false" placeholder="${escapeHtml(c.placeholder || '')}">`;
        }
        }
    }

    // ------------------------------------------ text encoders and VAE table
    function takeModules(presets) {
        const table = {};
        presets.forEach((preset) => {
            const m = { ...preset, text: false, message: '' };
            m.initial = moduleState(m);
            table[preset.setting] = m;
        });
        return table;
    }

    /** What a preset's table says, to tell an edit from no change. */
    function moduleState(m) {
        return JSON.stringify([m.rows.map((r) => r.selected || ''), m.kept.map((k) => k.name)]);
    }

    /** The setting's text for what a preset's table says: the chosen files, then the kept names. */
    function composeModules(key) {
        const m = modules[key];
        // Back where it started: the setting as it was written, not a respelling of it.
        if (moduleState(m) === m.initial) return meta.settings[key].value;
        return [...m.rows.filter((r) => r.selected).map((r) => r.selected),
                ...m.kept.map((k) => k.name)].join(', ');
    }

    function and(items) {
        return items.length < 2 ? items.join('') : `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
    }

    function renderModules(key) {
        const m = modules[key];
        const search = [m.label, ...m.classes, ...m.rows.flatMap((r) => [r.label, ...r.candidates.map((c) => c.label)])]
            .join(' ').toLowerCase();
        const body = m.text
            ? `<input type="text" class="mm-settings-input" data-key="${escapeHtml(key)}" value="${escapeHtml(draft[key])}"
                      spellcheck="false" placeholder="file names, separated by commas" aria-label="${escapeHtml(m.label)}">`
            : `<div class="mm-settings-module-rows">${m.rows.map((row) => renderModuleRow(key, m, row)).join('')}</div>
               ${m.kept.length ? `<div class="mm-settings-chips">${m.kept.map((k, i) => `
                   <span class="mm-settings-kept" title="Kept in the setting as written: ${escapeHtml(k.why)}">
                       ${escapeHtml(k.name)} <em>${escapeHtml(k.why)}</em>
                       <button type="button" data-kept-remove="${escapeHtml(key)}" data-index="${i}"
                               aria-label="Remove ${escapeHtml(k.name)}">&times;</button>
                   </span>`).join('')}</div>` : ''}`;
        return `
            <div class="mm-settings-field mm-settings-modules" data-key="${escapeHtml(key)}" data-search="${escapeHtml(search)}">
                <div class="mm-settings-label-row">
                    <span class="mm-settings-label mm-settings-module-title">${escapeHtml(m.label)}</span>
                    <span>
                        <button type="button" class="mm-settings-link" data-modules-text="${escapeHtml(key)}">${
                            m.text ? 'Use the table' : 'Edit as text'}</button>
                        ${resetButton(key)}
                    </span>
                </div>
                ${m.note ? `<div class="mm-settings-help">${escapeHtml(m.note)}</div>` : ''}
                ${body}
                <div class="mm-settings-extra">${escapeHtml(m.message)}</div>
                <div class="mm-settings-error" data-error="${escapeHtml(key)}"></div>
            </div>`;
    }

    function renderModuleRow(key, m, row) {
        const forWhom = m.classes.length > 1
            ? `<span class="mm-settings-module-for">${escapeHtml(row.used_by.join(', '))}</span>` : '';
        const choice = row.candidates.length
            ? `<select class="mm-dialog-select mm-settings-module-select" data-module="${escapeHtml(key)}"
                       data-file="${escapeHtml(row.file)}" aria-label="${escapeHtml(`${m.label}: ${row.label}`)}">
                   <option value="" ${row.selected ? '' : 'selected'}>Automatic${
                       row.automatic ? `: ${escapeHtml(row.automatic)}` : ''}</option>
                   ${row.candidates.map((c) => `
                       <option value="${escapeHtml(c.label)}" ${c.label === row.selected ? 'selected' : ''}>${
                           escapeHtml(c.label)}${c.precision ? ` (${escapeHtml(c.precision)})` : ''}</option>`).join('')}
               </select>`
            : `<span class="mm-settings-warning">None installed.</span> Download: ${row.links.map(([name, url]) =>
                  `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(name)}</a>`).join(', ')}`;
        return `
            <div class="mm-settings-module-row" data-file="${escapeHtml(row.file)}">
                <div class="mm-settings-module-name">${escapeHtml(row.label)}${forWhom}</div>
                <div class="mm-settings-module-choice">${choice}</div>
            </div>`;
    }

    /**
     * A file chosen for one preset's row. It is filled in for the other
     * presets that use the same file, where nothing is chosen - a row set by
     * hand is never changed from another. A row whose automatic pick is that
     * file already is left on Automatic, to keep following it.
     */
    function chooseModule(key, file, label) {
        const m = modules[key];
        m.rows.find((r) => r.file === file).selected = label || null;
        draft[key] = composeModules(key);
        const also = [];
        const kept = [];
        if (label) {
            Object.entries(modules).forEach(([otherKey, other]) => {
                if (otherKey === key || other.text) return;
                const row = other.rows.find((r) => r.file === file);
                if (!row) return;
                if (row.selected) {
                    if (row.selected !== label) kept.push(`${other.label} (${row.selected})`);
                    return;
                }
                if (row.automatic === label || !row.candidates.some((c) => c.label === label)) return;
                row.selected = label;
                draft[otherKey] = composeModules(otherKey);
                other.message = '';
                also.push(other.label);
                redrawField(otherKey);
            });
        }
        m.message = [
            also.length ? `Also set for ${and(also)}.` : '',
            kept.length ? `${and(kept)} kept ${kept.length > 1 ? 'their own choices' : 'its own choice'}.` : '',
        ].filter(Boolean).join(' ');
        redrawField(key);
    }

    /** Back from editing a preset as text: the server reads the text into the table. */
    async function tableFromText(key) {
        const m = modules[key];
        try {
            const drafts = JSON.stringify({ [m.preset]: draft[key] });
            const response = await fetch(`/model-manager/settings/modules?drafts=${encodeURIComponent(drafts)}`);
            const answer = await response.json();
            const preset = answer.success && answer.presets.find((p) => p.preset === m.preset);
            if (!preset) throw new Error(answer.error || 'the server did not describe it');
            modules[key] = { ...preset, text: false, message: '', initial: m.initial };
        } catch (e) {
            errors[key] = `Could not read the text into the table: ${e.message}`;
        }
        redrawField(key);
    }

    // ------------------------------------------------------------ API key
    function showKeyTest(text, tone) {
        keyTests += 1;               // any answer still on its way is for another key
        const out = root.querySelector('#mm_settings_key_test');
        if (!out) return;
        out.textContent = text;
        out.dataset.tone = tone;
    }

    /**
     * Ask Civitai whether it takes the key: the one typed here, if one is -
     * so it can be tried before it is saved - else the saved one.
     */
    async function testKey(button) {
        showKeyTest('Testing...', '');
        const asked = keyTests;
        button.disabled = true;
        let text;
        let tone;
        try {
            const response = await fetch('/model-manager/settings/test-key', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(secretTyped !== null ? { key: secretTyped } : {}),
            });
            const answer = await response.json();
            if (!answer.success) throw new Error(answer.error || 'the server did not say why');
            const which = answer.which === 'typed' ? 'The key typed here' : 'The saved key';
            if (answer.result === 'works') {
                text = `${which} works${answer.username ? `: signed in as ${answer.username}` : ''}.`;
                tone = 'good';
            } else if (answer.result === 'refused') {
                text = `Civitai refused ${which.toLowerCase()}.`;
                tone = 'bad';
            } else if (answer.result === 'none') {
                text = 'No key to test: type one, or save one first.';
                tone = '';
            } else {
                text = `Could not reach Civitai: ${answer.error || 'no answer'}.`;
                tone = 'warn';
            }
        } catch (e) {
            text = `Could not test the key: ${e.message}`;
            tone = 'warn';
        } finally {
            button.disabled = false;
        }
        if (asked === keyTests) showKeyTest(text, tone);
    }

    // ------------------------------------------------------ card preview
    function schedulePreview(key) {
        clearTimeout(previewTimers[key]);
        previewTimers[key] = setTimeout(() => drawPreview(key), TIMING.previewWait);
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
        // The one pair every card is sized by, set on the row it is in.
        row.style.setProperty('--mm-card-width', `${w}px`);
        row.style.setProperty('--mm-card-height', `${h}px`);
        const count = Math.min(CARD_PREVIEW_MOST,
                               Math.max(1, Math.floor((row.clientWidth + CARD_GAP) / (w + CARD_GAP))));
        const drawing = `${w}x${h}:${count}`;
        if (previewDrawn[key] === drawing && row.childElementCount) return;
        previewDrawn[key] = drawing;
        const preview = `cardPreview.${key}`;
        if (!ready(preview)) {
            note.textContent = 'This tab has not loaded yet, so there are no cards to preview.';
            return;
        }
        const asked = (previewAsked[key] || 0) + 1;
        previewAsked[key] = asked;
        note.textContent = '';
        try {
            const cards = await call(preview, count);
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
            db.innerHTML = `In use: <code>${escapeHtml(inUse || 'unknown')}</code>`
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
                        data.subfolder ? escapeHtml('\\' + data.subfolder.replace(/\//g, '\\')) : ''}</code>`
                        + (data.unknown.length
                            ? ` <span class="mm-settings-warning">Not a placeholder: ${escapeHtml(data.unknown.join(', '))}</span>`
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
            if (section.hasAttribute('data-whats-new')) {
                section.hidden = Boolean(query);
                return;
            }
            // Every tab it serves off, as the window holds them now: not shown.
            const served = SECTIONS.find((s) => s.id === section.dataset.section)?.shownWith;
            const tabOn = !served || served.some((tab) => state.value(TAB_SWITCHES[tab]) !== false);
            let any = false;
            section.querySelectorAll('.mm-settings-field').forEach((field) => {
                const rule = SHOWN_WHEN[field.dataset.key];
                const shown = tabOn && (!rule || rule(state))
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
        if (t.dataset.module) {
            if (e.type === 'change') chooseModule(t.dataset.module, t.dataset.file, t.value);
            return;
        }
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
            showKeyTest('', '');
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
        } else if (act === 'test-key') {
            testKey(t);
        } else if (act === 'forget') {
            secretTyped = '';
            showKeyTest('', '');
            const input = t.parentElement.querySelector('input');
            input.value = '';
            input.placeholder = 'The key will be removed when you save';
            refresh();
        } else if (t.dataset?.reset) {
            const key = t.dataset.reset;
            draft[key] = meta.settings[key].default;
            delete errors[key];
            if (modules?.[key]) {
                const m = modules[key];
                m.rows.forEach((r) => { r.selected = null; });
                m.kept = [];
                m.text = false;
                m.message = '';
            }
            redrawField(key);
        } else if (t.dataset?.modulesText) {
            const key = t.dataset.modulesText;
            if (modules[key].text) {
                tableFromText(key);
            } else {
                modules[key].text = true;
                redrawField(key);
            }
        } else if (t.dataset?.keptRemove) {
            const key = t.dataset.keptRemove;
            modules[key].kept.splice(Number(t.dataset.index), 1);
            draft[key] = composeModules(key);
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

    /**
     * @param {{tab?: string, section?: string}} [options] - tab: the tab
     *     whose gear it is ("model_manager", "civitai_browser",
     *     "generations"), whose sections are opened; section: one section's
     *     id, the only one opened, scrolled to - a note's button. Neither:
     *     every section collapsed.
     */
    async function open({ tab = null, section = null } = {}) {
        openedFor = { tab, section };
        if (!root) build();
        root.style.display = 'flex';
        holdPage('settings', true);
        const body = root.querySelector('#mm_settings_body');
        body.innerHTML = '<div class="mm-settings-loading">Loading settings...</div>';
        root.querySelector('#mm_settings_search').value = '';
        // The table reads file headers, the first time; the settings do not
        // wait for it, but the window draws once both have answered.
        const table = fetch('/model-manager/settings/modules', { cache: 'no-store' })
            .then((r) => r.json())
            .then((answer) => (answer.success ? takeModules(answer.presets) : null))
            .catch(() => null);
        try {
            const response = await fetch('/model-manager/settings', { cache: 'no-store' });
            const answer = await response.json();
            if (!answer.success) throw new Error(answer.error || 'the server did not say why');
            take(answer);
            modules = await table;
            renderBody();
        } catch (e) {
            meta = null;
            body.innerHTML = `<div class="mm-settings-error">Could not read the settings: ${escapeHtml(e.message)}</div>`;
            root.querySelector('#mm_settings_save').disabled = true;
        }
    }

    function close() {
        const n = changedKeys().length;
        if (n && !window.confirm(`Discard ${n} unsaved change${n === 1 ? '' : 's'}?`)) return;
        root.style.display = 'none';
        holdPage('settings', false);
    }

    /** Gone with the last tab (#186): its routes refuse now, so nothing in it is asked to be kept. */
    function remove() {
        if (root) holdPage('settings', false);
        root?.remove();
        root = null;
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
            // A change to how images are judged has them judged again, on
            // the server; say how far that has got.
            if ((answer.changed || []).some((key) => NSFW_KEYS.includes(key))) restampNotice().watch();
            take(answer);
            root.style.display = 'none';
            holdPage('settings', false);
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

    return { open, close, remove };
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

// ------------------------------------------------------------------------
// Judging stored images again

// The settings that change how images are judged: saving one has the server
// judge every stored image again (prompt_levels.py).
const NSFW_KEYS = [K.words, K.detection, K.percent];
const RESTAMP_DONE_MS = 6000;

/**
 * A notice in the corner while the server judges stored images again - a bar
 * of how many so far, then what changed. In the corner, not the settings
 * window: the window closes on the save that started it. One for the page.
 */
function createRestampNotice() {
    let box = null;
    let polling = null;
    let hideTimer = null;

    function show(text, share, tone = '') {
        if (!box) {
            box = document.createElement('div');
            box.className = 'mm-notice mm-restamp';
            box.setAttribute('role', 'status');
            box.innerHTML = '<div class="mm-restamp-text"></div>'
                + '<div class="mm-restamp-bar"><div class="mm-restamp-fill"></div></div>';
            document.body.appendChild(box);
        }
        clearTimeout(hideTimer);
        box.style.display = '';
        box.dataset.tone = tone;
        box.querySelector('.mm-restamp-text').textContent = text;
        const fill = box.querySelector('.mm-restamp-fill');
        // No share yet: the images are still being read, and how many is not known.
        box.classList.toggle('mm-restamp-unknown', share === null);
        fill.style.width = share === null ? '' : `${Math.round(share * 100)}%`;
    }

    function hideLater(ms) {
        clearTimeout(hideTimer);
        hideTimer = setTimeout(() => { if (box) box.style.display = 'none'; }, ms);
    }

    const count = (n) => Number(n).toLocaleString();

    async function poll() {
        let state;
        try {
            const response = await fetch('/model-manager/settings/nsfw-levels', { cache: 'no-store' });
            state = await response.json();
        } catch (e) {
            state = null;
        }
        if (state?.state === 'running') {
            // Every image judged, and the changes being written: about a
            // second on 109,738 images, the bar full meanwhile.
            if (state.total && state.judged === state.total) {
                show('Saving the new levels...', 1);
            } else if (state.total) {
                show(`Judging stored images again... ${count(state.judged)} of ${count(state.total)}`,
                     state.judged / state.total);
            } else {
                show('Reading stored images...', null);
            }
            polling = setTimeout(poll, TIMING.restampPoll);
            return;
        }
        polling = null;
        if (state?.state === 'done') {
            show(state.changed === null || state.changed === undefined
                ? 'Stored images already match these settings.'
                : `Done: ${count(state.changed)} of ${count(state.total)} images changed level.`, 1, 'good');
            hideLater(RESTAMP_DONE_MS);
        } else if (state?.state === 'failed') {
            show(`Could not judge stored images again: ${state.error}`, 1, 'bad');
            hideLater(RESTAMP_DONE_MS * 2);
        } else if (box) {
            box.style.display = 'none';
        }
    }

    /** Follow the pass a save has just started, to its end. */
    function watch() {
        if (!polling) poll();
    }

    /** Show a pass already running when the page loads - the one at the WebUI's start. */
    async function check() {
        try {
            const response = await fetch('/model-manager/settings/nsfw-levels', { cache: 'no-store' });
            if ((await response.json()).state === 'running') watch();
        } catch (e) {
            // Nothing to show.
        }
    }

    /** Stopped with the last tab (#186): no more asking, and the notice gone. */
    function stop() {
        clearTimeout(polling);
        clearTimeout(hideTimer);
        polling = null;
        box?.remove();
        box = null;
    }

    return { watch, check, stop };
}

let notice = null;

/** The one notice, for whichever tab asks first. */
export function restampNotice() {
    if (!notice) {
        notice = createRestampNotice();
        notice.check();
    }
    return notice;
}

// ------------------------------------------------------------------------
// The WebUI's own Settings page

// The Settings page's result line, and nothing else in its element: while
// Apply runs, Gradio puts its timer ("0.1s") in the same element, beside the
// line the last Apply left - which is not this one's answer.
const SETTINGS_RESULT_LINE = /^\s*\d+ settings changed/;
// A safety, should the line never be seen to settle: after this long, a
// settled line as it stands is taken as the answer.
const SETTINGS_RESULT_WAIT_MS = 10000;

/**
 * The settings the Settings page says it changed: its result line reads
 * "2 settings changed: a, b." in Forge Neo and the original Forge alike
 * (run_settings in modules/ui_settings.py). Nothing for any other line.
 */
export function changedOnSettingsPage(text) {
    const found = String(text || '').match(/^\s*\d+ settings changed:? (?:without save: )?(.+?)\.?\s*$/);
    return found ? found[1].split(',').map((key) => key.trim()).filter(Boolean) : [];
}

/**
 * Show the notice after Apply on the Settings page, too, when what it applied
 * changes how images are judged. The Settings page is part of the same page as
 * the tabs, so this is one listener for it, set once.
 */
function followSettingsPage(scope) {
    if (globalThis.__mmFollowingSettingsPage) return;
    globalThis.__mmFollowingSettingsPage = true;
    scope.onStop(() => { globalThis.__mmFollowingSettingsPage = false; });
    scope.listen(document, 'click', (e) => {
        if (!e.target?.closest?.('#settings_submit')) return;
        const app = typeof gradioApp === 'function' ? gradioApp() : document;
        const result = app.querySelector('#settings_result');
        if (!result) return;
        let finished = false;
        let observer = null;
        const timer = setTimeout(read, SETTINGS_RESULT_WAIT_MS);
        function read() {
            // Gradio's timer is still there, with the last Apply's line.
            if (finished || !SETTINGS_RESULT_LINE.test(result.textContent)) return;
            finished = true;
            clearTimeout(timer);
            observer?.disconnect();
            const changed = changedOnSettingsPage(result.textContent);
            if (changed.some((key) => NSFW_KEYS.includes(key))) {
                restampNotice().watch();
            }
            // For what else follows a setting - "Your generations" hides its tabs.
            window.dispatchEvent(new CustomEvent('mm-settings-page-applied', { detail: { changed } }));
        }
        if (typeof MutationObserver === 'function') {
            observer = new MutationObserver(read);
            observer.observe(result, { childList: true, subtree: true, characterData: true });
        }
    }, true);
}

let theWindow = null;
let settingsScope = null;       // the service's, while it runs (#186)

/** The one settings window, for whichever tab asks first. */
export function settingsWindow() {
    return (theWindow ||= createSettings());
}

/**
 * Started by the first tab, each having a gear (#182): the window offered by
 * name - from code, and from the gear and the banners' links, with data-tab
 * or data-section - a restamp still running looked for, and the Settings
 * page followed. Stopped with the last tab (#186): the window and the notice
 * go, as every route they ask refuses.
 */
export function start(scope) {
    settingsScope = scope;
    scope.provide('settings.open', (options) => settingsWindow().open(options));
    restampNotice();
    followSettingsPage(scope);
    scope.onStop(() => {
        theWindow?.remove();
        theWindow = null;
        notice?.stop();
        notice = null;
        settingsScope = null;
    });
}

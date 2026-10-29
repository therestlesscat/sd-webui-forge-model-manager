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
const { TIMING, escapeHtml, formatBytes, setText } = await shared('core.mjs');
const { ready, call } = await shared('calls.mjs');
// The upkeep panel's own `ask` polls the server: the question is askUser here.
const { ask: askUser, openDialog } = await shared('dialog.mjs');

// The settings this window draws a control of its own for, or acts on. Every
// setting's name, group, tab heading, tags, badges and the setting it sits
// under come from the server's answer: the registry, one entry a setting
// (model_manager/settings_registry.py, #320). The window kept its own tables
// of names, groups and nesting, and they drifted from Forge's.
const K = {
    apiKey: 'model_manager_civitai_api_key',
    mmCardSize: 'model_manager_card_size',
    cbCardSize: 'model_manager_civitai_card_size',
    folder: 'model_manager_civitai_folder_template',
    detection: 'model_manager_nsfw_detection',
    percent: 'model_manager_nsfw_prompt_model_percent',
    words: 'model_manager_nsfw_prompt_words',
    database: 'model_manager_database_path',
    thumbnailsFolder: 'model_manager_thumbnails_folder',
    queueInputs: 'model_manager_queue_inputs_dir',
    startImages: 'model_manager_generations_inputs_dir',
};
const MODULES_PREFIX = 'model_manager_modules_';
// Send's presets, after its other settings under a name of their own, drawn
// as a setting's, with the explanation as its description (#320).
const MODULES_HEADING = 'Text encoders and VAE';
const MODULES_INTRO = 'Automatic is what Send picks by itself. Choose a file to use that one instead. A file '
    + 'chosen for one model is filled in for the others that use it, where nothing is chosen yet.';
// The Tabs group's switches are named by their tabs; nothing in it is put
// under a tab's heading.
const TABS_GROUP = 'tabs';
const SHARED_HEADING = 'Shared across tabs';
// How long a setting a link opened at stays marked (#320).
const MARKED_MS = 2000;
// Controls too wide for the row's right-hand column, drawn across it (#320).
const WIDE_KINDS = ['cardsize', 'folder', 'secret', 'database', 'words', 'path'];

/** Controls that suit a setting better than its kind's default one. */
const CONTROLS = {
    [K.mmCardSize]: { kind: 'cardsize' },
    [K.cbCardSize]: { kind: 'cardsize' },
    [K.folder]: { kind: 'folder' },
    [K.words]: { kind: 'words' },
    [K.database]: { kind: 'database' },
    // A folder's full path, across the row; empty, its hint is the folder
    // the server would use (#345).
    [K.thumbnailsFolder]: { kind: 'path' },
    [K.queueInputs]: { kind: 'path' },
    [K.startImages]: { kind: 'path' },
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
    let openedFor = {};      // the tab, or the one section, open() was asked for, and a field to focus
    let draft = {};          // what the window holds, by key
    let secretTyped = null;  // a key typed into the window; null = unchanged
    let errors = {};
    let root = null;
    let shown = null;               // the window's handle in the dialog container, while open (#292)
    let saving = false;
    // What the list shows (#320): 'tab' - the settings tagged with the tab
    // whose gear opened it - or 'all', with the band; null, opened from
    // anywhere else, no band. And whether only those off their default show.
    let band = null;
    let changedOnly = false;
    // The group the list shows, picked on the left - or 'whats-new'. Always
    // one: the list of every group added nothing the left pane does not say
    // (#344). Null only until the window is drawn.
    let picked = null;
    let groupCounts = {};            // each group's settings shown now, for the left pane
    // The text encoder and VAE table, by setting: forge_modules' description
    // of each preset this WebUI has, with the window's edits. null when the
    // server could not describe them, and the settings show as text instead.
    let modules = null;
    const previewOpen = new Set();   // card size settings showing their preview
    const previewTimers = {};
    const previewAsked = {};
    const previewDrawn = {};         // what each preview last drew, to skip redrawing it
    let keyTests = 0;                // a key test's answer is shown only if nothing changed since
    // The database file's space and backups, under Database file (#287).
    const upkeep = createUpkeep(() => root?.querySelector('#mm_settings_upkeep') || null);

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

    /**
     * The groups, in the registry's order, each with its settings. A preset
     * this WebUI does not have is left out, not offered.
     */
    function sectionsWithKeys() {
        return meta.groups.map((group) => {
            const keys = meta.order.filter((k) => meta.settings[k].group === group.id
                && !(k.startsWith(MODULES_PREFIX) && modules && !(k in modules)));
            return { id: group.id, title: group.label, keys };
        }).filter((s) => s.keys.length);
    }

    /** Whether a setting is at its default - a key unset, for the API key. */
    function atDefault(key) {
        const s = meta.settings[key];
        return s.kind === 'secret' ? !state.hasKey() : same(draft[key], s.default);
    }

    /** Each tab's switch, from the Tabs group. */
    function tabSwitches() {
        const switchOf = {};
        meta.order.forEach((k) => {
            if (meta.settings[k].group === TABS_GROUP) switchOf[meta.settings[k].tags[0]] = k;
        });
        return switchOf;
    }

    /** Whether a setting shows with the tabs on as the window holds them: one it is shown with is on. */
    function shownByTabs(key, switchOf = tabSwitches()) {
        const needs = meta.settings[key]?.shown_with || [];
        return !needs.length || needs.some((tab) => !switchOf[tab] || state.value(switchOf[tab]) !== false);
    }

    /** The settings drawn, as the band would count them: the tab's, or all. */
    function countFor(which) {
        const switchOf = tabSwitches();
        return [...root.querySelectorAll('.mm-settings-field[data-key]')].map((f) => f.dataset.key)
            .filter((k) => shownByTabs(k, switchOf)
                && (which !== 'tab' || (meta.settings[k].tags || []).includes(openedFor.tab))).length;
    }

    /**
     * A group's settings under a heading per tab, where they act in different
     * tabs (#320): those shared across tabs first, then each tab in the
     * WebUI's order. None in the Tabs group, nor where all fall under one.
     */
    function headed(section) {
        const headingOf = (k) => meta.settings[k].heading || SHARED_HEADING;
        const headings = new Set(section.keys.map(headingOf));
        if (section.id === TABS_GROUP || headings.size < 2) return [[null, section.keys]];
        return [SHARED_HEADING, ...Object.values(meta.tag_labels)].filter((h) => headings.has(h))
            .map((h) => [h, section.keys.filter((k) => headingOf(k) === h)]);
    }

    /** The heading a setting is drawn under in its group, if the group has them. */
    function headingFor(key) {
        const section = sectionsWithKeys().find((s) => s.keys.includes(key));
        return section ? headed(section).find(([, keys]) => keys.includes(key))[0] : null;
    }

    // ------------------------------------------------------------- drawing
    function build() {
        root = document.createElement('dialog');
        root.id = 'mm_settings';
        root.className = 'mm-window mm-settings-window';
        root.setAttribute('aria-labelledby', 'mm_settings_title');
        root.innerHTML = `
            <div class="mm-dialog mm-settings-dialog">
                <div class="mm-settings-head">
                    <h3 id="mm_settings_title">Model Manager settings</h3>
                    <input type="search" class="mm-settings-search" id="mm_settings_search"
                           placeholder="Search settings: names, descriptions, tabs" aria-label="Search settings">
                    <div class="mm-settings-seg" role="group" aria-label="Which settings">
                        <button type="button" data-act="changed" data-changed="false" id="mm_settings_all"
                                aria-pressed="true">All</button>
                        <button type="button" data-act="changed" data-changed="true" id="mm_settings_changed"
                                aria-pressed="false" title="Only the settings that differ from their default">Changed</button>
                    </div>
                    <button type="button" class="mm-modal-close" data-act="cancel"
                            title="Close" aria-label="Close">&times;</button>
                </div>
                <div class="mm-settings-panes">
                    <nav class="mm-settings-nav" id="mm_settings_nav" aria-label="Groups"></nav>
                    <div class="mm-settings-body" id="mm_settings_body"></div>
                </div>
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
        root.querySelector('#mm_settings_search').addEventListener('input', () => {
            // A search keeps the group; the left pane's counts are of them all.
            applyVisibility();
            refreshFilters();
        });
    }

    function renderBody() {
        const body = root.querySelector('#mm_settings_body');
        body.innerHTML = '<div class="mm-settings-band" id="mm_settings_band" hidden></div>'
            + whatsNewSection() + sectionsWithKeys().map((section) => `
            <section class="mm-settings-section" data-section="${escapeHtml(section.id)}">
                <div class="mm-settings-fields">
                    ${headed(section).map(([heading, keys]) => (heading
        ? `<div class="mm-settings-subheading">${escapeHtml(heading)}</div>` : '')
        + keys.map((key) => (modules?.[key] && key === keys.find((k) => modules?.[k])
            ? `<div class="mm-settings-subheading mm-settings-presets-head">${escapeHtml(MODULES_HEADING)}</div>
               <div class="mm-settings-help mm-settings-intro">${escapeHtml(MODULES_INTRO)}</div>` : '')
            + renderField(key)).join('')).join('')}
                </div>
            </section>`).join('')
            + '<div class="mm-settings-empty" id="mm_settings_empty" hidden>'
            + 'No setting matches. Try fewer words, or clear the filters.</div>';
        // A note's button shows its group; a link, its setting's (#320); else
        // the first with a setting shown (applyVisibility).
        picked = openedFor.section || meta.settings[openedFor.focus]?.group || null;
        refresh();
        loadWhatsNew();
        upkeep.start();
        if (openedFor.section) body.querySelector(`[data-section="${openedFor.section}"]`)?.scrollIntoView?.({ block: 'start' });
        if (openedFor.focus) {
            const field = body.querySelector(`.mm-settings-field[data-key="${openedFor.focus}"]`);
            field?.scrollIntoView?.({ block: 'center' });
            // Marked for a moment, so the eye finds it - a link's setting (#320).
            field?.classList.add('mm-settings-marked');
            setTimeout(() => field?.classList.remove('mm-settings-marked'), MARKED_MS);
            field?.querySelector(['input', 'textarea', 'select']
                .map((tag) => `${tag}[data-key="${openedFor.focus}"]`).join(', '))?.focus?.();
        }
    }

    /**
     * The band, All / Changed and the left pane, as the list now is (#320).
     * The band and the pane are drawn again only when what they say changes.
     */
    function refreshFilters() {
        const bar = root.querySelector('#mm_settings_band');
        if (bar) {
            bar.hidden = !band;
            const label = meta.tag_labels?.[openedFor.tab] || openedFor.tab;
            const button = (which, text) => `<button type="button" data-act="band" data-band="${which}"
                    aria-pressed="${band === which}">${escapeHtml(text)} <span class="mm-settings-count">${
                    countFor(which)}</span></button>`;
            const html = band ? `<span>Showing</span><div class="mm-settings-seg mm-settings-seg-big" role="group"
                    aria-label="Which settings to show">${button('tab', `${label} settings`)}${
                    button('all', 'All settings')}</div>` : '';
            if (bar.dataset.drawn !== html) {
                bar.innerHTML = html;
                bar.dataset.drawn = html;
            }
        }
        const n = meta.order.filter((k) => root.querySelector(`.mm-settings-field[data-key="${k}"]`)
            && !atDefault(k)).length;
        setText(root.querySelector('#mm_settings_changed'), `Changed (${n})`);
        root.querySelector('#mm_settings_changed').setAttribute('aria-pressed', String(changedOnly));
        root.querySelector('#mm_settings_all').setAttribute('aria-pressed', String(!changedOnly));
        const nav = root.querySelector('#mm_settings_nav');
        const entry = (id, title, count) => `<button type="button" data-act="group" data-group="${escapeHtml(id)}"
                aria-current="${picked === id}"${count === 0 ? ' disabled' : ''}><span>${escapeHtml(title)}</span>${
                count === null ? '' : `<span class="mm-settings-count">${count}</span>`}</button>`;
        const html = entry('whats-new', "What's new", null) + sectionsWithKeys()
            .map((section) => entry(section.id, section.title, groupCounts[section.id] || 0)).join('');
        if (nav.dataset.drawn !== html) {
            nav.innerHTML = html;
            nav.dataset.drawn = html;
        }
    }

    /** What is typed in the search, word by word (#320): a setting shows when it holds every one. */
    function searchWords() {
        return (root.querySelector('#mm_settings_search').value || '').toLowerCase().split(/\s+/).filter(Boolean);
    }

    // "What's new": every note to the user that applies here, dismissed or
    // not, newest first (model_manager/release_notes.py) - where a note
    // dismissed in a tab can be read again. Not a setting: the search leaves
    // it out.
    function whatsNewSection() {
        return `
            <section class="mm-settings-section" data-whats-new>
                <div class="mm-settings-fields" id="mm_settings_notes">Loading...</div>
            </section>`;
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

    /**
     * A row, as the proof of concept drew it (#320): the name, its badges and
     * tags, the description under it, and the control on the right - or, for
     * a control too wide for that column, across the row under the
     * description.
     */
    function renderField(key) {
        if (modules?.[key]) return renderModules(key);
        const s = meta.settings[key];
        const control = { ...s, ...(CONTROLS[key] || {}) };
        const label = s.name || s.label;
        const id = `mms_${key}`;
        const wide = WIDE_KINDS.includes(control.kind);
        const tags = (s.tags || []).map((tag) => meta.tag_labels[tag] || tag);
        const depth = depthOf(key);
        const drawn = renderControl(key, control, id, label);
        return `
            <div class="mm-settings-field${depth ? ` mm-settings-child mm-settings-child-${Math.min(depth, 2)}` : ''}${
                wide ? ' mm-settings-wide' : ''}"
                 data-key="${escapeHtml(key)}"
                 data-search="${escapeHtml([label, s.label, s.info || '', ...tags].join(' ').toLowerCase())}">
                <div class="mm-settings-name">
                    <label for="${id}" class="mm-settings-label">${escapeHtml(label)}</label>${markings(key, headingFor(key))}
                </div>
                <div class="mm-settings-ctl">${wide ? '' : drawn}${resetButton(key)}</div>
                ${s.info ? `<div class="mm-settings-help">${escapeHtml(s.info)}</div>` : ''}
                ${s.under ? `<div class="mm-settings-under" data-under="${escapeHtml(key)}"></div>` : ''}
                ${wide ? `<div class="mm-settings-wide-ctl">${drawn}</div>` : ''}
                <div class="mm-settings-extra" data-extra="${escapeHtml(key)}"></div>
                ${key === K.database ? '<div class="mm-upkeep" id="mm_settings_upkeep"></div>' : ''}
                <div class="mm-settings-error" data-error="${escapeHtml(key)}"></div>
            </div>`;
    }

    /**
     * A setting's badges, Changed while it differs from its default, then the
     * tabs it acts in - but the one its heading names.
     */
    function markings(key, heading) {
        const s = meta.settings[key];
        const badges = (s.badges || []).map((b) => `<span class="mm-settings-badge">${
            escapeHtml(meta.badge_labels?.[b] || b)}</span>`);
        const changed = '<span class="mm-settings-badge mm-settings-badge-changed" hidden>Changed</span>';
        const tags = s.group === TABS_GROUP ? [] : (s.tags || []).map((tag) => meta.tag_labels[tag] || tag)
            .filter((tag) => tag !== heading).map((tag) => `<span class="mm-settings-tag">${escapeHtml(tag)}</span>`);
        return [...badges, changed, ...tags].join('');
    }

    /** How many settings deep it sits under switches. */
    function depthOf(key) {
        const under = meta.settings[key]?.under;
        return under && meta.settings[under[0]] ? 1 + depthOf(under[0]) : 0;
    }

    /** Whether the setting it sits under holds the value that turns it on - a key set, for the API key. */
    function holds(key) {
        const [parent, value] = meta.settings[key].under;
        const now = meta.settings[parent]?.kind === 'secret' ? state.hasKey() : state.value(parent);
        return value === true ? Boolean(now) : same(now, value);
    }

    /**
     * Why a setting does nothing now, from the nearest switch that is not as
     * it needs - or '' when every one is. Greyed, not hidden (#320): hidden, a
     * person cannot learn it exists.
     */
    function idleBecause(key) {
        const under = meta.settings[key]?.under;
        if (!under || !meta.settings[under[0]]) return '';
        if (holds(key)) return idleBecause(under[0]);
        const parent = meta.settings[under[0]];
        if (parent.kind === 'secret') return 'Applies once an API key is set.';
        const name = parent.name || parent.label;
        if (under[1] === true) return `Applies while \u201c${name}\u201d is on.`;
        const words = (parent.choices || []).find(([, v]) => same(v, under[1]))?.[0] ?? String(under[1]);
        return `Applies while \u201c${name}\u201d is ${words}.`;
    }

    function resetButton(key) {
        return `<button type="button" class="mm-settings-reset" data-reset="${escapeHtml(key)}"
                        title="Back to the default">Reset</button>`;
    }

    function renderControl(key, c, id, label) {
        const v = draft[key];
        const check = (on) => `<input type="checkbox" class="mm-settings-switch" id="${id}"
                                      data-key="${escapeHtml(key)}" ${on ? 'checked' : ''}>`;
        // A choice of two the window draws as a switch: on is its first (#320).
        if (c.switch) return check(same(v, c.switch[0]));
        switch (c.kind) {
        case 'bool':
            return check(v);
        case 'choice':
            // Segmented, on one line (#320).
            return `<div class="mm-settings-seg mm-settings-choices" role="radiogroup" id="${id}"
                         aria-label="${escapeHtml(label)}">
                ${c.choices.map(([text, value], i) => `
                    <label class="mm-settings-seg-option">
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
        case 'path':
            return `<input type="text" id="${id}" class="mm-settings-input" data-key="${escapeHtml(key)}"
                           value="${escapeHtml(v)}" spellcheck="false"
                           placeholder="${escapeHtml(meta.default_folders?.[key] || c.placeholder || '')}">`;
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
            <div class="mm-settings-field mm-settings-modules mm-settings-wide" data-key="${escapeHtml(key)}"
                 data-search="${escapeHtml(search)}">
                <div class="mm-settings-name">
                    <span class="mm-settings-label mm-settings-module-title">${escapeHtml(m.label)}</span>${
                        markings(key, headingFor(key))}
                </div>
                <div class="mm-settings-ctl">
                    <button type="button" class="mm-settings-link" data-modules-text="${escapeHtml(key)}">${
                        m.text ? 'Use the table' : 'Edit as text'}</button>
                    ${resetButton(key)}
                </div>
                ${m.note ? `<div class="mm-settings-help">${escapeHtml(m.note)}</div>` : ''}
                <div class="mm-settings-wide-ctl">${body}</div>
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
            const reset = field.querySelector('.mm-settings-reset');
            if (reset) reset.hidden = atDefault(key) || s.kind === 'secret';
            const changed = field.querySelector('.mm-settings-badge-changed');
            if (changed) changed.hidden = atDefault(key);
            field.classList.toggle('mm-settings-changed', changedKeys().includes(key));
            const error = field.querySelector('.mm-settings-error');
            error.textContent = errors[key] || '';
        });
    }

    function applyVisibility() {
        const words = searchWords();
        // A setting is shown while a tab it needs is on, as the window holds
        // them now; then as the band, Changed and the search narrow it. The
        // picked group shows alone; the counts are of them all.
        const switchOf = tabSwitches();
        groupCounts = {};
        const sections = Array.from(root.querySelectorAll('.mm-settings-section[data-section]'));
        sections.forEach((section) => {
            let count = 0;
            section.querySelectorAll('.mm-settings-field').forEach((field) => {
                const key = field.dataset.key;
                const s = meta.settings[key] || {};
                const shown = shownByTabs(key, switchOf)
                    && (band !== 'tab' || (s.tags || []).includes(openedFor.tab))
                    && (!changedOnly || !atDefault(key))
                    && words.every((word) => field.dataset.search.includes(word));
                field.hidden = !shown;
                if (shown) count += 1;
                const why = idleBecause(field.dataset.key);
                field.classList.toggle('mm-settings-off', Boolean(why));
                const note = field.querySelector(':scope > .mm-settings-under');
                if (note && note.textContent !== why) note.textContent = why;
            });
            // A heading goes with the last of its settings, and the text
            // under it - Send's explanation of its presets - with it.
            section.querySelectorAll('.mm-settings-subheading').forEach((heading) => {
                let next = heading.nextElementSibling;
                let shownBelow = false;
                const intros = [];
                while (next && !next.classList.contains('mm-settings-subheading')) {
                    shownBelow = shownBelow || (next.classList.contains('mm-settings-field') && !next.hidden);
                    if (next.classList.contains('mm-settings-intro')) intros.push(next);
                    next = next.nextElementSibling;
                }
                heading.hidden = !shownBelow;
                intros.forEach((intro) => { intro.hidden = !shownBelow; });
            });
            groupCounts[section.dataset.section] = count;
        });
        // A picked group with nothing left to show gives way to the first
        // that has (#344): "queue folder" typed on Tabs shows Files and
        // folders. What's new holds no setting, so a search or Changed
        // leaves it too.
        const empty = (id) => (id === 'whats-new' ? Boolean(words.length) || changedOnly : !groupCounts[id]);
        if (picked === null || empty(picked)) {
            const first = sections.find((s) => groupCounts[s.dataset.section]);
            if (first && first.dataset.section !== picked) {
                picked = first.dataset.section;
                root.querySelector('#mm_settings_body').scrollTop = 0;
            }
        }
        let anyShown = false;
        sections.forEach((section) => {
            section.hidden = !groupCounts[section.dataset.section] || picked !== section.dataset.section;
            anyShown = anyShown || !section.hidden;
        });
        const whatsNew = root.querySelector('[data-whats-new]');
        if (whatsNew) whatsNew.hidden = picked !== 'whats-new';
        const nothing = root.querySelector('#mm_settings_empty');
        if (nothing) nothing.hidden = anyShown || picked === 'whats-new';
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
        refreshFilters();
        refreshFooter();
    }

    /** Put the draft back into the controls of one setting, after a reset or a preset. */
    function redrawField(key) {
        const field = root.querySelector(`.mm-settings-field[data-key="${key}"]`);
        if (field) field.outerHTML = renderField(key);
        if (key === K.database) upkeep.draw();
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
        } else if (s.switch) {
            draft[key] = t.checked ? s.switch[0] : s.switch[1];
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
        const act = t.dataset?.act;
        if (act === 'cancel') close();
        else if (act === 'save') save();
        else if (act === 'band' || act === 'changed') {
            if (act === 'band') band = t.dataset.band;
            else changedOnly = t.dataset.changed === 'true';
            refresh();
        } else if (act === 'group') {
            // Pressed, the group alone; pressed again, it stays (#344).
            picked = t.dataset.group;
            refresh();
            root.querySelector('#mm_settings_body').scrollTop = 0;
        }
        else if (act === 'reveal') {
            const input = t.parentElement.querySelector('input');
            input.type = input.type === 'password' ? 'text' : 'password';
            t.textContent = input.type === 'password' ? 'Show' : 'Hide';
        } else if (act === 'test-key') {
            testKey(t);
        } else if (act === 'compact') {
            upkeep.compact();
        } else if (act === 'compact-cancel') {
            upkeep.cancel();
        } else if (act === 'backup-delete') {
            upkeep.remove([t.dataset.name]);
        } else if (act === 'backups-delete-all') {
            upkeep.remove(null);
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
     * @param {{tab?: string, section?: string, focus?: string}} [options] - tab: the tab
     *     whose gear it is ("queue", "generations", "gallery", "model_manager",
     *     "civitai_browser"): the band shows the settings tagged with it,
     *     beside All settings (#320); section: one group's id
     *     (settings_registry.GROUPS), shown, scrolled to - a note's button.
     *     Neither: the first group with a setting shown (#344). focus: a
     *     setting's key, its group shown, the setting scrolled to, marked for
     *     a moment and focused - a link to it (#320), the database notice's
     *     button (#136).
     */
    async function open({ tab = null, section = null, focus = null } = {}) {
        openedFor = { tab, section, focus };
        band = tab ? 'tab' : null;
        changedOnly = false;
        picked = null;
        if (!root) build();
        // In the dialog container: Esc, a click beside it, its × and Cancel
        // ask first if anything is unsaved; a save closes it without asking.
        if (!shown) {
            shown = openDialog(root, {
                beforeClose: discardUnsaved,
                focus: () => root.querySelector('#mm_settings_search'),
                onClose: () => {
                    shown = null;
                    upkeep.stop();
                },
            });
        }
        const body = root.querySelector('#mm_settings_body');
        body.innerHTML = '<div class="mm-settings-loading">Loading settings...</div>';
        const nav = root.querySelector('#mm_settings_nav');
        nav.innerHTML = '';
        nav.dataset.drawn = '';
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

    /** Its × and Cancel: closed, after the question if anything is unsaved. */
    function close() {
        return shown?.close('cancel');
    }

    /**
     * Asked before the window closes by the person's hand: false keeps it
     * open. Nothing unsaved, it answers at once, and the window closes at once.
     */
    function discardUnsaved() {
        const n = changedKeys().length;
        if (!n) return true;
        return askUser({
            title: `Discard ${n} unsaved change${n === 1 ? '' : 's'}?`,
            buttons: [{ label: 'Keep editing', value: false }, { label: 'Discard', value: true, type: 'danger' }],
        }).then((answer) => answer?.value === true);
    }

    /** Gone with the last tab (#186): its routes refuse now, so nothing in it is asked to be kept. */
    function remove() {
        shown?.close('code');
        upkeep.stop();
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
            shown?.close('code');
            window.dispatchEvent(new CustomEvent('mm-settings-saved', {
                detail: { changed: answer.changed || [], settings: answer.settings },
            }));
        } catch (e) {
            root.querySelector('#mm_settings_status').textContent = `Not saved: ${e.message}`;
            return;
        } finally {
            saving = false;
            if (meta && shown) refresh();
        }
    }

    return { open, close, remove };
}

// ------------------------------------------------------------------------
// The database file: the space no row uses, and the backups beside it (#287)

// Seconds a compact takes per byte kept, on a fast disk: 17.4 s for 1.76 GB.
const COMPACT_SECONDS_PER_BYTE = 17.4 / 1.76e9;

// formatBytes says "Unknown" for 0: here 0 is known.
const sizeText = (bytes) => (bytes > 0 ? formatBytes(bytes) : '0 B');

/** When a backup was made, as its line says it: "15 Oct 2026, 23:39". */
function backupMade(made) {
    const date = new Date(made);
    if (Number.isNaN(date.getTime())) return made;
    return date.toLocaleString('en-GB', { day: 'numeric', month: 'short', year: 'numeric',
                                          hour: '2-digit', minute: '2-digit' });
}

function backupHolds(backup) {
    if (backup.kind === 'image_cache') return 'the old image cache';
    return backup.holds === null || backup.holds === undefined ? 'version unknown' : `database version ${backup.holds}`;
}

/**
 * The Compact database line and the Old backups list, drawn into the box
 * `container()` finds - the settings window's, under Database file - from
 * the server's answer (db/upkeep.py). It asks again each second while a
 * compact runs, and every few seconds while something stops one, so the
 * button comes back by itself.
 */
function createUpkeep(container) {
    let space = null;      // the server's last answer
    let message = null;    // {text, tone}: what an action's answer said
    let watched = false;   // a compact this window started or saw running: its end is shown
    let timer = null;
    let asked = 0;         // an answer is drawn only if nothing was asked since
    let active = false;    // between the window's drawing and its closing

    function later(work, ms) {
        clearTimeout(timer);
        timer = setTimeout(work, ms);
    }

    /** Ask the server, and draw what it says. */
    async function ask() {
        clearTimeout(timer);
        timer = null;
        if (!active || !container()) return;
        const mine = ++asked;
        let answer;
        try {
            answer = await (await fetch('/model-manager/database/space', { cache: 'no-store' })).json();
        } catch (e) {
            answer = { success: false, error: e.message };
        }
        if (mine !== asked || !active || !container()) return;
        space = answer;
        draw();
        if (!answer.success) return;
        if (answer.compact?.state === 'running') {
            watched = true;
            later(follow, TIMING.compactPoll);
        } else if (answer.blocked) {
            later(ask, TIMING.compactRetry);
        }
    }

    /** A running compact's progress, each second until it ends. */
    async function follow() {
        timer = null;
        if (!active || !container()) return;
        let answer;
        try {
            answer = await (await fetch('/model-manager/database/compact', { cache: 'no-store' })).json();
        } catch (e) {
            answer = null;
        }
        if (!active || !container()) return;
        if (answer?.success && answer.compact?.state === 'running') {
            space = { ...space, compact: answer.compact };
            draw();
            later(follow, TIMING.compactPoll);
        } else {
            ask();
        }
    }

    function compactHtml() {
        const s = space;
        const c = s.compact;
        if (c?.state === 'running') {
            return `
                <div class="mm-upkeep-row">
                    <span class="mm-upkeep-line">Compacting the database... ${Math.floor(c.seconds)} s</span>
                    <button type="button" class="mm-btn mm-btn-small" data-act="compact-cancel">Cancel</button>
                </div>
                <div class="mm-restamp-bar mm-restamp-unknown"><div class="mm-restamp-fill"></div></div>`;
        }
        const total = s.file_bytes + s.wal_bytes;
        let ended = '';
        if (c && (watched || (c.state === 'done' && !c.shrunk))) {
            let text;
            let tone = 'good';
            if (c.state === 'done' && c.shrunk) {
                text = `Compacted: ${sizeText(c.before)} to ${sizeText(c.after)}, `
                    + `${sizeText(Math.max(0, c.before - c.after))} freed, in ${Math.round(c.seconds)} s.`;
            } else if (c.state === 'done') {
                text = `Compacted. The file shrinks to ${sizeText(s.pages * s.page_size)} as soon as nothing `
                    + 'is reading it: something was reading it for the 30 seconds the compact waited. '
                    + 'This window tries again each time it asks.';
                tone = 'warn';
            } else if (c.state === 'cancelled') {
                text = 'Cancelled: the database is as it was.';
                tone = '';
            } else if (c.locked) {
                text = 'Could not compact: another program was writing to the database, most likely the other '
                    + 'WebUI sharing it. Nothing was changed; try again when it is idle.';
                tone = 'bad';
            } else {
                text = `Could not compact: ${c.error || 'the server did not say why'}. Nothing was changed.`;
                tone = 'bad';
            }
            ended = `<div class="mm-upkeep-line" data-tone="${tone}" role="status">${escapeHtml(text)}</div>`;
        }
        let line;
        let why = '';
        if (s.blocked) {
            line = s.blocked;
            why = s.blocked;
        } else if (s.free_bytes < s.min_free) {
            line = `The file is already compact: ${sizeText(s.free_bytes)} of ${sizeText(total)} unused.`;
            why = line;
        } else {
            line = `About ${sizeText(s.free_bytes)} of the ${sizeText(total)} file is unused.`;
        }
        return `${ended}
            <div class="mm-upkeep-row">
                <span class="mm-upkeep-line">${escapeHtml(line)}</span>
                <button type="button" class="mm-btn mm-btn-small" data-act="compact"
                        ${why ? `disabled title="${escapeHtml(why)}"` : ''}>Compact database</button>
            </div>`;
    }

    function backupsHtml() {
        const list = space.backups || [];
        if (!list.length) return '<div class="mm-upkeep-line">No old backups beside the database.</div>';
        return `
            <div class="mm-upkeep-row mm-upkeep-backups-head">
                <span class="mm-upkeep-line">Old backups: ${list.length} ${list.length === 1 ? 'copy' : 'copies'},
                    ${sizeText(space.backups_bytes)}</span>
                <button type="button" class="mm-btn mm-btn-small" data-act="backups-delete-all">Delete all</button>
            </div>
            <div class="mm-upkeep-backups">
                ${list.map((b) => `
                    <span>${escapeHtml(backupMade(b.made))}</span>
                    <span>${escapeHtml(backupHolds(b))}</span>
                    <span>${escapeHtml(sizeText(b.bytes))}</span>
                    <button type="button" class="mm-btn mm-btn-small" data-act="backup-delete"
                            data-name="${escapeHtml(b.name)}">Delete</button>`).join('')}
            </div>`;
    }

    function draw() {
        const box = container();
        if (!box || !space) return;
        if (!space.success) {
            box.innerHTML = `<div class="mm-upkeep-line" data-tone="warn">Could not read the database's space: ${
                escapeHtml(space.error || 'the server did not say why')}</div>`;
            return;
        }
        box.innerHTML = compactHtml()
            + (message ? `<div class="mm-upkeep-line" data-tone="${escapeHtml(message.tone)}" role="status">${
                escapeHtml(message.text)}</div>` : '')
            + backupsHtml()
            + '<div class="mm-upkeep-repairs" data-repairs-slot></div>';
        // A place for each repair's line: its own script draws it, loaded
        // only where the library needs it (#241). None of their code is here.
        window.dispatchEvent(new CustomEvent('mm-upkeep-drawn',
                                             { detail: { slot: box.querySelector('[data-repairs-slot]') } }));
    }

    async function post(endpoint, body) {
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body || {}),
        });
        return response.json();
    }

    async function compact() {
        const s = space;
        if (!s?.success) return;
        const seconds = Math.max(5, Math.round(s.kept_bytes * COMPACT_SECONDS_PER_BYTE / 5) * 5);
        const asked = await askUser({
            title: 'Compact the database?',
            message: `It rewrites the ${sizeText(s.file_bytes + s.wal_bytes)} file: `
                + `about ${seconds} seconds on a fast disk, longer on a slow one. `
                + 'Generations, downloads and syncs in this WebUI wait until it ends.'
                + (s.custom_database ? ' Another WebUI sharing this file should not generate or sync meanwhile: '
                    + 'its writes give up after 30 seconds.' : ''),
            buttons: [{ label: 'Cancel', value: false }, { label: 'Compact', value: true, type: 'primary' }],
        });
        if (!asked?.value) return;
        message = null;
        let answer;
        try {
            answer = await post('/model-manager/database/compact');
        } catch (e) {
            answer = { success: false, error: e.message };
        }
        if (answer.success) {
            watched = true;
        } else {
            message = { text: `Not compacted: ${answer.error || 'the server did not say why'}`, tone: 'bad' };
        }
        ask();
    }

    async function cancel() {
        try {
            await post('/model-manager/database/compact/cancel');
        } catch (e) {
            // The next ask shows where it is.
        }
        ask();
    }

    /** Delete these backups by name, all of them for null - each after a question. */
    async function remove(names) {
        const list = space?.backups || [];
        const chosen = names === null ? list : list.filter((b) => names.includes(b.name));
        if (!chosen.length) return;
        const bytes = chosen.reduce((sum, b) => sum + b.bytes, 0);
        const one = chosen.length === 1 && names !== null;
        const asked = await askUser({
            title: one ? `Delete the backup of ${backupHolds(chosen[0])}, made ${backupMade(chosen[0].made)}?`
                : `Delete all ${chosen.length} backups?`,
            message: one ? `It frees ${sizeText(chosen[0].bytes)}. It cannot be undone.`
                : `They free ${sizeText(bytes)}. They cannot be undone.`,
            buttons: [{ label: 'Cancel', value: false }, { label: 'Delete', value: true, type: 'danger' }],
        });
        if (!asked?.value) return;
        let answer;
        try {
            answer = await post('/model-manager/database/backups/delete', { names: chosen.map((b) => b.name) });
        } catch (e) {
            answer = { success: false, error: e.message };
        }
        if (!answer.success) {
            message = { text: `Not deleted: ${answer.error || 'the server did not say why'}`, tone: 'bad' };
        } else {
            const kept = (answer.results || []).filter((r) => !r.deleted);
            message = kept.length
                ? { text: kept.map((r) => `Could not delete ${r.name}: ${r.error}.`).join(' '), tone: 'bad' }
                : null;
        }
        ask();
    }

    /** The window drawn: ask for the file's space. */
    function start() {
        active = true;
        message = null;
        watched = false;
        ask();
    }

    /** The window closed: no more asking. */
    function stop() {
        active = false;
        clearTimeout(timer);
        timer = null;
        asked += 1;
    }

    return { start, stop, draw, compact, cancel, remove };
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
            // For what else follows a setting - "Generations" hides its tabs.
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

// Drive the new VAE helpers against a replica of Forge Neo's control.
//
// The DOM below mirrors what two sources establish:
//   - Neo's javascript/modelHelp.js  -> #setting_sd_modules div.wrap-inner div.token
//   - gradio 4.39 Index-BwXb1GqD.js  -> .token-remove, .token-remove.remove-all,
//                                        li.item[data-testid=dropdown-option][aria-label]
const fs = require('fs');
const vm = require('vm');

const path = require('path');

// The extension, found from this file rather than from a drive letter, so the
// suite runs wherever the repository happens to be checked out.
const REPO = path.resolve(__dirname, '..', '..').replace(/\\/g, '/');
const src = fs.readFileSync(REPO + '/javascript/model_manager.mjs', 'utf8');

// ---------------------------------------------------------------- tiny DOM
class El {
    constructor(tag, attrs = {}, text = '') {
        this.tag = tag; this.attrs = attrs; this.children = []; this._text = text;
        this.classList = {
            _s: new Set((attrs.class || '').split(/\s+/).filter(Boolean)),
            contains(c) { return this._s.has(c); },
        };
        this.onclick = null;
    }
    get className() { return [...this.classList._s].join(' '); }
    get parentElement() { return this.parent ?? null; }
    getAttribute(k) { return this.attrs[k] ?? null; }
    setAttribute(k, v) { this.attrs[k] = v; }
    get textContent() {
        return this._text + this.children.map(c => c.textContent).join('');
    }
    append(...kids) { this.children.push(...kids); kids.forEach(k => k.parent = this); return this; }
    remove() {
        if (this.parent) this.parent.children = this.parent.children.filter(c => c !== this);
    }
    click() { if (this.onclick) this.onclick(this); }
    // Real DOM: dispatchEvent never triggers onclick, and .click() never
    // fires a mousedown listener. Keeping those separate is the point.
    focus() {} blur() {}
    dispatchEvent(e) {
        let node = this;
        while (node) {                       // bubbling, which the list relies on
            if (node._on && node._on[e.type]) node._on[e.type](e);
            node = e.bubbles ? node.parent : null;
        }
    }
    addEventListener(t, fn) { (this._on ||= {})[t] = fn; }
    _walk(out = []) { out.push(this); this.children.forEach(c => c._walk(out)); return out; }
    _matches(sel) {
        // Supports: #id, tag, .a, .a.b, [attr="v"], "tag.class", descendant " ", and ","
        return sel.split(',').map(s => s.trim()).some(part => {
            const steps = part.split(/\s+/);
            const last = steps[steps.length - 1];
            if (!this._matchSimple(last)) return false;
            let node = this.parent;
            for (let i = steps.length - 2; i >= 0; i--) {
                while (node && !node._matchSimple(steps[i])) node = node.parent;
                if (!node) return false;
                node = node.parent;
            }
            return true;
        });
    }
    _matchSimple(sel) {
        let m;
        if ((m = /^#(.+)$/.exec(sel))) return this.attrs.id === m[1];
        if ((m = /^\[([\w-]+)="([^"]*)"\]$/.exec(sel))) return this.attrs[m[1]] === m[2];
        const tagPart = sel.match(/^[a-zA-Z]+/);
        if (tagPart && this.tag !== tagPart[0]) return false;
        const classes = sel.match(/\.[\w-]+/g) || [];
        return classes.every(c => this.classList.contains(c.slice(1)));
    }
    querySelector(sel) { return this._walk().slice(1).find(n => n._matches(sel)) ?? null; }
    querySelectorAll(sel) {
        const r = this._walk().slice(1).filter(n => n._matches(sel));
        r.forEach = Array.prototype.forEach.bind(r);
        return r;
    }
}

// ------------------------------------------------- build Neo's VAE control
function buildControl(selected, available, flavour = 'neo') {
    const root = flavour === 'neo'
        ? new El('div', { id: 'setting_sd_modules' })
        : new El('div', {});  // classic Forge sets no elem_id at all
    const wrapInner = new El('div', { class: 'wrap-inner' });
    const input = new El('input', {});
    input.value = '';

    // commits: the selection after each change - Neo sends Forge one request
    // per change, carrying the whole selection as it then stands.
    const state = { selected: [...selected], optionsOpen: false, commits: [] };
    const commit = () => state.commits.push([...state.selected]);

    function renderTokens() {
        wrapInner.children = wrapInner.children.filter(c => !c.classList.contains('token'));
        const toks = state.selected.map(name => {
            const tok = new El('div', { class: 'token' }, name);
            const rm = new El('div', { class: 'token-remove svelte-1scun43' }, '\u00d7');
            rm.onclick = () => { state.selected = state.selected.filter(n => n !== name); commit(); renderTokens(); };
            return tok.append(rm);
        });
        wrapInner.children.unshift(...toks);
        toks.forEach(t => t.parent = wrapInner);
    }

    const secondary = new El('div', { class: 'secondary-wrap' });
    const removeAll = new El('div', { class: 'token-remove remove-all svelte-1scun43' }, '\u00d7');
    removeAll.onclick = () => { state.selected = []; commit(); renderTokens(); };
    secondary.append(input, removeAll);
    wrapInner.append(secondary);
    renderTokens();

    // Typing in the box opens the list, filtered.
    const list = new El('ul', { class: 'options svelte-y6qw75', role: 'listbox' });
    input.addEventListener('input', () => {
        list.children = [];
        const q = String(input.value || '').toLowerCase();
        available.filter(n => n.toLowerCase().includes(q)).forEach((name, i) => {
            const li = new El('li', {
                class: 'item svelte-y6qw75', 'data-index': String(i),
                'aria-label': name, 'data-testid': 'dropdown-option', role: 'option',
                'aria-selected': String(state.selected.includes(name)),
            });
            li.append(new El('span', { class: 'inner-item svelte-y6qw75' }, name));
            li.addEventListener('mousedown', () => {
                if (!state.selected.includes(name)) state.selected.push(name);
                commit();
                renderTokens();
            });
            list.append(li);
        });
    });

    const label = new El('label', {}).append(new El('span', {}, 'VAE / Text Encoder'));
    root.append(label, new El('div', { class: 'wrap' }).append(wrapInner), list);
    const doc = new El('div', { id: 'gradio-app' }).append(root);
    return { root, doc, state, input };
}

// --------------------------------------------------------------- sandbox
let control = null;
const sandbox = {
    console: { log() {}, warn() {}, error() {} },
    setTimeout, Promise,
    Event: class { constructor(t, o = {}) { this.type = t; this.bubbles = !!o.bubbles; } },
    MouseEvent: class { constructor(t, o = {}) { this.type = t; this.bubbles = !!o.bubbles; } },
    Array, Object, String,
};
sandbox.window = sandbox;
sandbox.gradioApp = () => control.doc;
vm.createContext(sandbox);

function lift(name) {
    const m = src.match(new RegExp('^[ \\t]*(async )?function ' + name + '\\s*\\(', 'm'));
    if (!m) throw new Error('not found: ' + name);
    const isAsync = !!m[1];
    let i = src.indexOf('(', m.index + m[0].length - 1), depth = 0;
    for (;; i++) { if (src[i] === '(') depth++; else if (src[i] === ')' && --depth === 0) break; }
    i = src.indexOf('{', i);
    const start = i; depth = 0;
    for (;; i++) { if (src[i] === '{') depth++; else if (src[i] === '}' && --depth === 0) break; }
    return vm.runInContext('(' + (isAsync ? 'async ' : '') + 'function'
        + src.slice(src.indexOf('(', m.index), start) + src.slice(start, i + 1) + ')', sandbox);
}

vm.runInContext("const NEO_MODULES_ID = 'setting_sd_modules'; const MODULES_LABEL = 'VAE / Text Encoder';", sandbox);
for (const fn of ['getModulesControl', 'nextFrame', 'readModuleOptions', 'matchVAEName',
                  'pressOption', 'clearModules', 'tokenLabel', 'selectedModuleLabels', 'applyForgeModules',
                  'applyVaeSelection', 'patchForgeModules']) {
    sandbox[fn] = lift(fn);
}

let failures = 0;
const check = (label, cond, extra) => {
    if (!cond) { failures++; console.log('FAIL ' + label + (extra ? '\n  ' + extra : '')); }
};

const AVAILABLE = ['qwen_image_vae.safetensors', 'sdxl_vae.safetensors',
                   'vae-ft-mse-840000-ema-pruned.safetensors', 'clip_l.safetensors'];

(async () => {
    // 1. THE BUG: image with no VAE must clear a stale selection.
    control = buildControl(['qwen_image_vae.safetensors'], AVAILABLE);
    check('starts with the stale Qwen VAE', control.state.selected.length === 1);
    await sandbox.applyVaeSelection(null);
    check('no-VAE image clears the control', control.state.selected.length === 0,
          JSON.stringify(control.state.selected));

    // 2. Several stale modules all go.
    control = buildControl(['qwen_image_vae.safetensors', 'clip_l.safetensors'], AVAILABLE);
    await sandbox.applyVaeSelection(null);
    check('clears every stale module', control.state.selected.length === 0,
          JSON.stringify(control.state.selected));

    // 3. Already empty stays empty.
    control = buildControl([], AVAILABLE);
    await sandbox.applyVaeSelection(null);
    check('empty stays empty', control.state.selected.length === 0);

    // 4. Image naming a VAE selects exactly that one, replacing the stale pick.
    control = buildControl(['qwen_image_vae.safetensors'], AVAILABLE);
    await sandbox.applyVaeSelection('sdxl_vae.safetensors');
    check('selects the named VAE', control.state.selected.join() === 'sdxl_vae.safetensors',
          JSON.stringify(control.state.selected));

    // 5. Metadata without the extension still matches the file.
    control = buildControl(['qwen_image_vae.safetensors'], AVAILABLE);
    await sandbox.applyVaeSelection('vae-ft-mse-840000-ema-pruned');
    check('matches a bare name to the file',
          control.state.selected.join() === 'vae-ft-mse-840000-ema-pruned.safetensors',
          JSON.stringify(control.state.selected));

    // 6. A VAE this install does not have: cleared, not guessed, not left stale.
    control = buildControl(['qwen_image_vae.safetensors'], AVAILABLE);
    await sandbox.applyVaeSelection('some_vae_i_do_not_have');
    check('unknown VAE leaves the control cleared', control.state.selected.length === 0,
          JSON.stringify(control.state.selected));

    // 7. A control with no elem_id but the right label is still ours to drive:
    //    it must NOT fall through to the stub. (Covered in depth by 10 and 11.)
    control = buildControl(['qwen_image_vae.safetensors'], AVAILABLE);
    control.root.attrs.id = 'something_else';
    let calls = [];
    sandbox.selectVAE = (v) => calls.push(v);
    await sandbox.applyVaeSelection(null);
    check('id-less but labelled control is driven directly', calls.length === 0 &&
          control.state.selected.length === 0, JSON.stringify(calls));

    // 8. Neither control present: must not throw.
    control = buildControl([], AVAILABLE, 'classic');
    control.root.children = [];
    delete sandbox.selectVAE;
    let threw = false;
    try { await sandbox.applyVaeSelection(null); } catch (e) { threw = true; }
    check('no control anywhere is survivable', !threw);

    // 9. matchVAEName on its own.
    const labels = AVAILABLE;
    check('exact match', sandbox.matchVAEName('sdxl_vae.safetensors', labels) === 'sdxl_vae.safetensors');
    check('prefix match', sandbox.matchVAEName('sdxl_vae', labels) === 'sdxl_vae.safetensors');
    check('case insensitive', sandbox.matchVAEName('SDXL_VAE', labels) === 'sdxl_vae.safetensors');
    check('no match returns null', sandbox.matchVAEName('nope', labels) === null);
    check('null name returns null', sandbox.matchVAEName(null, labels) === null);
    check('no labels passes through', sandbox.matchVAEName('x', []) === 'x');

    // 10. CLASSIC FORGE: same control, no elem_id, found by its label.
    //     selectVAE exists there but only sets desiredVAEName, which feeds the
    //     "(Managed by Forge)" sd_vae gr.State - it never clears the modules.
    //     So the label lookup must win before the fallback is reached.
    let stubCalls = [];
    sandbox.selectVAE = (v) => stubCalls.push(v);

    control = buildControl(['qwen_image_vae.safetensors'], AVAILABLE, 'classic');
    check('classic control is not findable by id',
          sandbox.getModulesControl() !== null, 'label lookup failed');
    await sandbox.applyVaeSelection(null);
    check('classic: no-VAE image clears it', control.state.selected.length === 0,
          JSON.stringify(control.state.selected));
    check('classic: did NOT fall through to the selectVAE stub',
          stubCalls.length === 0, JSON.stringify(stubCalls));

    control = buildControl(['qwen_image_vae.safetensors'], AVAILABLE, 'classic');
    stubCalls = [];
    await sandbox.applyVaeSelection('sdxl_vae');
    check('classic: selects the named VAE',
          control.state.selected.join() === 'sdxl_vae.safetensors',
          JSON.stringify(control.state.selected));
    check('classic: still no stub call', stubCalls.length === 0);

    // 11. Neither flavour present -> the A1111 stub is the last resort.
    control = buildControl([], AVAILABLE, 'classic');
    control.root.children = [];  // strip the label so it cannot be found
    stubCalls = [];
    await sandbox.applyVaeSelection(null);
    check('with no control at all, selectVAE is used', stubCalls.join() === 'None',
          JSON.stringify(stubCalls));

    // 12. A PATCH, NOT A RESET: Send makes the control hold exactly what the
    //     image needs, with as few changes as can be. Each change is a request
    //     of Forge's, carrying the whole selection; they can land out of order,
    //     and after a clear-and-reselect Neo sometimes loaded an Anima model
    //     with no VAE while the control showed it. So nothing different,
    //     nothing touched; else only what differs.
    const ANIMA = ['qwen_3_06b_base.safetensors', 'qwen_image_vae.safetensors'];
    const ALL = [...AVAILABLE, 'qwen_3_06b_base.safetensors', 'sdxl_vae_fix.safetensors'];
    const same = (a, b) => JSON.stringify([...a].sort()) === JSON.stringify([...b].sort());

    control = buildControl(ANIMA, ALL);
    await sandbox.patchForgeModules(ANIMA);
    check('patch: what is already exact is not touched at all', control.state.commits.length === 0,
          JSON.stringify(control.state.commits));

    control = buildControl([...ANIMA, 'clip_l.safetensors'], ALL);
    await sandbox.patchForgeModules(ANIMA);
    check('patch: an extra file is taken out on its own, in one change',
          same(control.state.selected, ANIMA) && control.state.commits.length === 1,
          JSON.stringify(control.state.commits));

    control = buildControl(['qwen_image_vae.safetensors'], ALL);
    await sandbox.patchForgeModules(ANIMA);
    check('patch: a missing file is added on its own, the rest left in place',
          same(control.state.selected, ANIMA) && control.state.commits.length === 1
          && control.state.commits[0].includes('qwen_image_vae.safetensors'),
          JSON.stringify(control.state.commits));

    control = buildControl(['sdxl_vae.safetensors'], ALL);
    await sandbox.patchForgeModules(['sdxl_vae_fix.safetensors']);
    check('patch: one file for another is one out and one in, never an empty-then-refill',
          same(control.state.selected, ['sdxl_vae_fix.safetensors'])
          && control.state.commits.length === 2,
          JSON.stringify(control.state.commits));

    control = buildControl(['qwen_image_vae.safetensors', 'clip_l.safetensors'], ALL);
    await sandbox.patchForgeModules([]);
    check('patch: an image that needs nothing leaves nothing', control.state.selected.length === 0,
          JSON.stringify(control.state.selected));

    // A file that cannot be taken out alone: the whole control is cleared and
    // filled, the one case that still costs every change.
    control = buildControl(['sdxl_vae.safetensors', 'qwen_image_vae.safetensors'], ALL);
    control.root.querySelectorAll('.token-remove').forEach((rm) => {
        if (!rm.classList.contains('remove-all')) rm.remove();
    });
    await sandbox.patchForgeModules(['qwen_image_vae.safetensors', 'clip_l.safetensors']);
    check('patch: with no way to take one out, it is cleared and filled, and still exact',
          same(control.state.selected, ['qwen_image_vae.safetensors', 'clip_l.safetensors']),
          JSON.stringify(control.state.selected));

    control = buildControl([], AVAILABLE, 'classic');
    control.root.children = [];
    check('patch: no control, no patch', (await sandbox.patchForgeModules(['x'])) === false);

    console.log(failures === 0 ? 'All checks passed.' : failures + ' check(s) failed.');
    process.exit(failures ? 1 : 0);
})();

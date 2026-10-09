// The JavaScript answer to pyflakes.
//
// Identical code with a missing import is still broken, and neither a text
// diff nor a syntax check sees it. Stage 2 only caught that class of mistake
// in Python because pyflakes existed; this is the equivalent for the modules.
//
//   1. every imported name must actually be exported by the file named
//   2. every name read or called must be created where it is used - in its
//      function, a block around it, or the file - imported, or a known global
//   3. no file reads a window global another file defines; calls between
//      files name something shared/calls.mjs was given
//   4. markup holds no JavaScript, and every action it names is provided -
//      in the modules' templates and the tabs' Python alike
import { readFileSync, readdirSync, statSync } from 'fs';
import { fileURLToPath } from 'url';
import { join, resolve, dirname } from 'path';

// The javascript directory, found from this file rather than from a drive
// letter, so the check runs wherever the repository is checked out.
const ROOT = process.env.MM_ROOT
    ? process.env.MM_ROOT.replace(/\\/g, '/')
    : resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', 'javascript').replace(/\\/g, '/');

function walk(dir, out = []) {
    for (const e of readdirSync(dir)) {
        const p = join(dir, e).replace(/\\/g, '/');
        if (statSync(p).isDirectory()) walk(p, out);
        else if (p.endsWith('.mjs')) out.push(p);
    }
    return out;
}

const files = walk(ROOT);
let failures = 0;

// --- what each file exports -------------------------------------------------
const exported = new Map();
for (const f of files) {
    const src = readFileSync(f, 'utf8');
    const names = new Set();
    for (const m of src.matchAll(/^export\s+(?:async\s+)?function\s+(\w+)/gm)) names.add(m[1]);
    for (const m of src.matchAll(/^export\s+(?:const|let|var)\s+(\w+)/gm)) names.add(m[1]);
    for (const m of src.matchAll(/^export\s*\{([^}]*)\}/gms)) {
        for (const p of m[1].split(',')) {
            const n = p.trim().split(/\s+as\s+/).pop().trim();
            if (n) names.add(n);
        }
    }
    exported.set(f, names);
}

// --- 1. imports resolve -----------------------------------------------------
for (const f of files) {
    const src = readFileSync(f, 'utf8');
    for (const m of src.matchAll(/import\s*\{([^}]*)\}\s*from\s*['"]([^'"]+)['"]/gs)) {
        const target = resolve(dirname(f), m[2]).replace(/\\/g, '/');
        if (!exported.has(target)) {
            console.log(`FAIL ${f.replace(ROOT, '')}: imports from ${m[2]} — no such module`);
            failures++;
            continue;
        }
        for (const p of m[1].split(',')) {
            const n = p.trim().split(/\s+as\s+/)[0].trim();
            if (n && !exported.get(target).has(n)) {
                console.log(`FAIL ${f.replace(ROOT, '')}: imports ${n} from ${m[2]}, which does not export it`);
                failures++;
            }
        }
    }
}

// --- 1b. the same, for a versioned dynamic import ------------------------
// `const { a, b } = await import(<url built from a literal>)` says the same
// thing as a static import and deserves the same check.
const DYNAMIC = /new URL\(\s*['"]([^'"]+)['"][\s\S]*?const \{([^}]*)\}\s*=\s*await import\(/g;

for (const f of files) {
    const src = readFileSync(f, 'utf8');
    for (const m of src.matchAll(DYNAMIC)) {
        const target = resolve(dirname(f), m[1]).replace(/\\/g, '/');
        if (!exported.has(target)) {
            console.log(`FAIL ${f.replace(ROOT, '')}: dynamically imports ${m[1]} — no such module`);
            failures++;
            continue;
        }
        for (const part of m[2].split(',')) {
            // destructuring renames with `a: b`, and the export is `a`
            const name = part.trim().split(':')[0].trim();
            if (name && !exported.get(target).has(name)) {
                console.log(`FAIL ${f.replace(ROOT, '')}: destructures ${name} from ${m[1]}, `
                            + 'which does not export it');
                failures++;
            }
        }
    }
}

// --- 1c. the same, through a file's `shared` helper -------------------------
// The tabs and the shared modules import javascript/shared/ through one line,
// `const shared = (name) => import(new URL(\`<folder>${name}<version>\`, ...))`,
// so each module comes under one version (#93). `await shared('x.mjs')` names
// a module in that folder, and what is destructured from it has to be there.
const HELPER = /const shared = \(name\) => import\(new URL\(`([^`$]*)\$\{name\}/;
const VIA_HELPER = /(?:const \{([^}]*)\}\s*=\s*)?await shared\(\s*['"]([^'"]+)['"]\s*\)/g;

for (const f of files) {
    const src = readFileSync(f, 'utf8');
    const uses = [...src.matchAll(VIA_HELPER)];
    if (!uses.length) continue;
    const helper = src.match(HELPER);
    if (!helper) {
        console.log(`FAIL ${f.replace(ROOT, '')}: calls shared() but defines no shared helper`);
        failures++;
        continue;
    }
    // A tab asks for every module it needs at once (SHARED_MODULES), then
    // awaits each: one left off the list is asked for only at its await, a
    // round trip after the one before. The list may also name what those
    // modules import, so that is asked for at once too - send.mjs's wan.mjs
    // came a round trip after send.mjs - but nothing they do not.
    if (helper[1] === '../shared/') {
        const listed = src.match(/const SHARED_MODULES = \[([^\]]*)\]/);
        const awaited = [...new Set(uses.map((m) => m[2]))].sort();
        const named = listed ? [...listed[1].matchAll(/['"]([^'"]+)['"]/g)].map((m) => m[1]).sort() : [];
        const reached = new Set(awaited);
        for (const name of reached) {
            const path = resolve(dirname(f), helper[1] + name).replace(/\\/g, '/');
            const own = exported.has(path) ? readFileSync(path, 'utf8') : '';
            for (const m of own.matchAll(VIA_HELPER)) reached.add(m[2]);
        }
        const missing = awaited.filter((name) => !named.includes(name));
        const needless = named.filter((name) => !reached.has(name));
        if (!listed || missing.length || needless.length) {
            const said = [!listed && 'is missing',
                          missing.length && `leaves out ${missing.join(', ')}, which the tab awaits`,
                          needless.length && `names ${needless.join(', ')}, which nothing the tab loads imports`];
            console.log(`FAIL ${f.replace(ROOT, '')}: SHARED_MODULES ${said.filter(Boolean).join('; ')}`);
            failures++;
        }
    }
    for (const m of uses) {
        const target = resolve(dirname(f), helper[1] + m[2]).replace(/\\/g, '/');
        if (!exported.has(target)) {
            console.log(`FAIL ${f.replace(ROOT, '')}: imports ${m[2]} through shared() — no such module`);
            failures++;
            continue;
        }
        for (const part of (m[1] || '').split(',')) {
            const name = part.trim().split(':')[0].trim();
            if (name && !exported.get(target).has(name)) {
                console.log(`FAIL ${f.replace(ROOT, '')}: destructures ${name} from ${m[2]}, `
                            + 'which does not export it');
                failures++;
            }
        }
    }
}

// --- 2. every name used is known --------------------------------------------
// Searching the text for "word(" saw calls alone, so a name only read passed:
// [...currentImages] outlived its rename and failed only when that line ran
// (#115). The code is parsed instead (acorn, one of the tests' own packages),
// and every name read or called has to be created where it is used - in that
// function, a block around it, or the file - imported, or a global. A name
// another function creates does not count, nor a loop's `let` after the loop
// (#116).
const GLOBALS = new Set(['window', 'document', 'console', 'fetch', 'setTimeout', 'clearTimeout',
    'setInterval', 'clearInterval', 'localStorage', 'sessionStorage', 'navigator', 'URL', 'URLSearchParams',
    'FormData', 'Event', 'CustomEvent', 'MouseEvent', 'IntersectionObserver', 'ResizeObserver',
    'MutationObserver', 'DOMParser', 'File', 'DataTransfer', 'AbortController', 'alert', 'confirm',
    'requestAnimationFrame', 'atob', 'btoa', 'TextEncoder', 'TextDecoder', 'structuredClone', 'queueMicrotask',
    // the language's own
    'globalThis', 'undefined', 'arguments', 'NaN', 'Infinity', 'Promise', 'Math', 'JSON', 'Object', 'Array',
    'String', 'Number', 'Boolean', 'Symbol', 'BigInt', 'Date', 'Set', 'Map', 'WeakMap', 'WeakSet', 'RegExp',
    'Error', 'TypeError', 'RangeError', 'SyntaxError', 'Proxy', 'Reflect', 'Intl', 'Uint8Array', 'ArrayBuffer',
    'parseInt', 'parseFloat', 'isNaN', 'isFinite', 'encodeURIComponent', 'decodeURIComponent', 'encodeURI',
    'decodeURI',
    // provided by the WebUI's own classic scripts
    'gradioApp', 'onUiLoaded', 'onAfterUiUpdate', 'onUiUpdate', 'onOptionsChanged', 'opts',
    'updateInput', 'selectCheckpoint', 'selectVAE', 'inputAccordionChecked', 'switch_to_txt2img',
    'restart_reload']);

// Comments are prose; the window.<Name> check below reads the text alone.
function stripProse(text) {
    return text
        .replace(/\/\*[\s\S]*?\*\//g, ' ')
        .replace(/(^|[^:])\/\/[^\n]*/g, '$1')
        .replace(/`(?:[^`\\]|\\.)*`/g, '``')
        .replace(/'(?:[^'\\\n]|\\.)*'/g, "''")
        .replace(/"(?:[^"\\\n]|\\.)*"/g, '""');
}

let acorn = null;
let acornWalk = null;
try {
    acorn = await import('acorn');
    acornWalk = await import('acorn-walk');
} catch {
    // Without the parser nothing here is checked: say so, never pass.
    console.log('FAIL acorn is not installed - run `npm install` in tests/');
    failures++;
}

const isFunction = (node) => /Function/.test(node.type);
const isBlock = (node) => isFunction(node)
    || /^(Program|BlockStatement|StaticBlock|ForStatement|ForInStatement|ForOfStatement|SwitchStatement|CatchClause|ClassBody)$/.test(node.type);

// The names a pattern binds: x, { a, b: c = 1 }, [d, ...e].
function bound(pattern, out = []) {
    if (!pattern) return out;
    if (pattern.type === 'Identifier') out.push(pattern.name);
    else if (pattern.type === 'ObjectPattern')
        pattern.properties.forEach((p) => bound(p.type === 'RestElement' ? p.argument : p.value, out));
    else if (pattern.type === 'ArrayPattern') pattern.elements.forEach((e) => bound(e, out));
    else if (pattern.type === 'AssignmentPattern') bound(pattern.left, out);
    else if (pattern.type === 'RestElement') bound(pattern.argument, out);
    return out;
}

// Each part of the code that holds names, and the names it holds: a `var`, a
// parameter and a function's own name its function; a `let`, a `const`, a
// class or a function declaration its block; an import the file.
function scopesOf(ast) {
    const scopes = new Map();
    const hold = (scope, pattern) => {
        if (!scopes.has(scope)) scopes.set(scope, new Set());
        for (const name of bound(pattern)) scopes.get(scope).add(name);
    };
    acornWalk.fullAncestor(ast, (node, _state, ancestors) => {
        const around = ancestors.slice(0, -1).reverse();
        const block = around.find(isBlock) || ast;
        if (node.type === 'VariableDeclaration') {
            const owner = node.kind === 'var' ? (around.find(isFunction) || ast) : block;
            for (const d of node.declarations) hold(owner, d.id);
        }
        if ((node.type === 'FunctionDeclaration' || node.type === 'ClassDeclaration') && node.id) hold(block, node.id);
        if ((node.type === 'FunctionExpression' || node.type === 'ClassExpression') && node.id) hold(node, node.id);
        if (isFunction(node)) node.params.forEach((p) => hold(node, p));
        if (node.type === 'CatchClause' && node.param) hold(node, node.param);
        if (/^Import(Default|Namespace)?Specifier$/.test(node.type)) hold(ast, node.local);
    });
    return scopes;
}

for (const f of files) {
    const text = readFileSync(f, 'utf8');
    const missing = [];
    if (acorn) {
        let ast = null;
        try {
            ast = acorn.parse(text, { ecmaVersion: 'latest', sourceType: 'module', locations: true });
        } catch (e) {
            missing.push(`does not parse (${e.message})`);
        }
        if (ast) {
            const scopes = scopesOf(ast);
            const unknown = new Map();          // "reads x" -> its lines
            // The walker reaches a name in use alone: never a property after
            // a dot, an object's key or a method's name, nor a name as it is
            // made - a shorthand { images } it reaches as its value, a read.
            acornWalk.fullAncestor(ast, (node, _state, ancestors) => {
                if (node.type !== 'Identifier' || GLOBALS.has(node.name)) return;
                const parent = ancestors[ancestors.length - 2];
                if (ancestors.some((a) => scopes.get(a)?.has(node.name))) return;
                const called = /^(Call|New)Expression$/.test(parent.type) && parent.callee === node;
                const key = `${called ? 'calls' : 'reads'} ${node.name}`;
                unknown.set(key, [...(unknown.get(key) || []), node.loc.start.line]);
            });
            for (const [key, lines] of unknown) missing.push(`${key} (line ${lines.join(', ')})`);
        }
    }
    // Member calls once let window.MMCommon.x() pass as "a property access,
    // not my problem" - while the global it reached for had been replaced by
    // imports. Any window.<Name> that is not a browser global, or is assigned
    // nowhere, is a leftover.
    const src = stripProse(text);
    for (const m of src.matchAll(/window\.([A-Z]\w+)/g)) {
        const name = m[1];
        if (!new RegExp(`window\.${name}\s*=`).test(src)) {
            missing.push(`window.${name} (read, never assigned)`);
        }
    }

    if (missing.length) {
        console.log(`FAIL ${f.replace(ROOT, '')}: ${[...new Set(missing)].join(', ')} — not declared or imported`);
        failures += new Set(missing).size;
    }
}

// --- 3. calls between files go through the registry ------------------------
// Tabs and shared code once called each other through window globals - a tab
// defining window.mmShowModel, another calling it - with nothing saying who
// offered what (#94). They go through shared/calls.mjs now: what a file offers
// it provides by name, and others call that name. So no file reads a window.X
// another file defines (an inline handler in markup reaches only globals, so
// a tab keeps its own), and every name called is one some file provides.
function stripComments(text) {
    return text.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/(^|[^:])\/\/[^\n]*/g, '$1');
}
const definedIn = new Map();        // window name -> the files that define it
const provided = new Set();
const sources = new Map(files.map((f) => [f, stripComments(readFileSync(f, 'utf8'))]));
for (const [f, src] of sources) {
    for (const m of src.matchAll(/window\.(\w+)\s*(?:=|\|\|=|\?\?=)(?!=)/g)) {
        if (!definedIn.has(m[1])) definedIn.set(m[1], new Set());
        definedIn.get(m[1]).add(f);
    }
    for (const m of src.matchAll(/\bprovide\(\s*['"`]([^'"`$]+)/g)) provided.add(m[1]);
}
for (const [f, src] of sources) {
    const reached = new Set();
    for (const m of src.matchAll(/window\.(\w+)/g)) {
        const owners = definedIn.get(m[1]);
        if (owners && !owners.has(f)) reached.add(`window.${m[1]} (defined in ${[...owners].map((o) => o.replace(ROOT, '')).join(', ')})`);
    }
    const unknown = new Set();
    for (const m of src.matchAll(/\b(?:call|ready)\(\s*(['"])([^'"]+)\1/g)) {
        if (!provided.has(m[2])) unknown.add(m[2]);
    }
    if (reached.size) {
        console.log(`FAIL ${f.replace(ROOT, '')}: reaches another file's ${[...reached].join(', ')}`
                    + ' - provide it in shared/calls.mjs and call it by name');
        failures += reached.size;
    }
    if (unknown.size) {
        console.log(`FAIL ${f.replace(ROOT, '')}: calls ${[...unknown].join(', ')}, which no file provides`);
        failures += unknown.size;
    }
}

// --- 3b. tabs reach each other through the loading module -------------------
// A tab called another's actions by name - Show in Model Manager was
// call('modelManager.showModel') - and checked ready() its own way, and drew
// its link whether that tab was there or not (#184). Now it asks the loading
// module (shared/loading.mjs): available(tab), and open(tab, entry). So no
// tab's script, and no shared module but the loading module and tabs.mjs,
// names another tab's area in call, ready, provide, showTab, tabButton or
// tabShowing - nor imports another tab's script.
const TAB_AREAS = { model_manager: 'modelManager', civitai_browser: 'civitaiBrowser', generations: 'generations',
                    queue: 'queue' };
const AREA_NAMES = new Set(Object.values(TAB_AREAS));
for (const [f, src] of sources) {
    const where = f.replace(ROOT, '');
    const tab = where.match(/^\/tabs\/(\w+)\.mjs$/)?.[1];
    if (!tab && !where.startsWith('/shared/')) continue;
    if (where === '/shared/loading.mjs' || where === '/shared/tabs.mjs') continue;
    const own = tab ? TAB_AREAS[tab] : null;
    const reached = new Set();
    for (const m of src.matchAll(/\b(call|ready|provide|showTab|tabButton|tabShowing)\(\s*([^)]*)/g)) {
        for (const q of m[2].matchAll(/['"`](\w+)(?:\.\w+)?['"`]/g)) {
            if (AREA_NAMES.has(q[1]) && q[1] !== own) reached.add(`${m[1]}('${q[1]}…')`);
        }
    }
    for (const m of src.matchAll(/tabs\/(\w+)\.mjs/g)) {
        if (TAB_AREAS[m[1]] && TAB_AREAS[m[1]] !== own) reached.add(`imports tabs/${m[1]}.mjs`);
    }
    if (reached.size) {
        console.log(`FAIL ${where}: reaches another tab directly - ${[...reached].join(', ')}`
                    + ' - ask the loading module: available(tab), open(tab, entry)');
        failures += reached.size;
    }
}

// --- 4. markup names what it does ------------------------------------------
// Markup said what a click did in JavaScript - onclick="window.mmSelectModel(3)"
// - a window global named in a string, in the modules' templates and in the
// tabs' Python, that no check followed across (#95). It says it in
// data-action now, a name provided in shared/calls.mjs. So no markup has an
// inline handler, and every name of the form <area>.<what>, for an area some
// file provides under, is provided: data-action="downloads.control" in the
// Python, and the names a tab hands a renderer, action: 'modelManager.selectModel'.
const UI = resolve(ROOT, '..', 'model_manager', 'ui').replace(/\\/g, '/');
const shown = (f) => (f.startsWith(UI) ? f.replace(UI, 'model_manager/ui') : f.replace(ROOT, ''));
const markup = new Map([...sources,
    ...readdirSync(UI).filter((f) => f.endsWith('.py')).map((f) => [`${UI}/${f}`, readFileSync(`${UI}/${f}`, 'utf8')])]);
const areas = new Set([...provided].map((name) => name.split('.')[0]));
for (const [f, src] of markup) {
    const inline = [...src.matchAll(/\son([a-z]+)=\\?["']|setAttribute\(\s*['"]on([a-z]+)/g)].map((m) => `on${m[1] || m[2]}`);
    if (inline.length) {
        console.log(`FAIL ${shown(f)}: markup with an inline handler (${[...new Set(inline)].join(', ')})`
                    + ' - name what it does in data-action, provided in shared/calls.mjs');
        failures += inline.length;
    }
    const unknown = new Set();
    for (const m of src.matchAll(/(['"`])([a-zA-Z]+)\.(\w+)\1/g)) {
        if (/^(mjs|js|py|css|json)$/.test(m[3])) continue;       // a file: shared('downloads.mjs')
        if (areas.has(m[2]) && !provided.has(`${m[2]}.${m[3]}`)) unknown.add(`${m[2]}.${m[3]}`);
    }
    if (unknown.size) {
        console.log(`FAIL ${shown(f)}: names ${[...unknown].join(', ')}, which no file provides`);
        failures += unknown.size;
    }
}

// And with nothing in markup to reach them, no window globals: what a file
// offers it provides. The one left is the version the shared modules are
// asked for under, which every tab needs before the registry has loaded.
const PAGE_GLOBALS = new Set(['mmSharedVersion']);
for (const [name, owners] of definedIn) {
    if (PAGE_GLOBALS.has(name)) continue;
    console.log(`FAIL ${[...owners].map(shown).join(', ')}: defines window.${name}`
                + ' - provide it in shared/calls.mjs, or name it in data-action');
    failures += 1;
}

console.log(`${files.length} modules checked — ` +
    (failures === 0 ? 'every name resolves.' : `${failures} unresolved.`));
process.exit(failures ? 1 : 0);

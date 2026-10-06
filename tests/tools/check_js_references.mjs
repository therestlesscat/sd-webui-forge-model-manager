// The JavaScript answer to pyflakes.
//
// Identical code with a missing import is still broken, and neither a text
// diff nor a syntax check sees it. Stage 2 only caught that class of mistake
// in Python because pyflakes existed; this is the equivalent for the modules.
//
//   1. every imported name must actually be exported by the file named
//   2. every bare identifier that gets called must be declared, imported,
//      or a known global
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

// --- 2. every called name is known -----------------------------------------
const GLOBALS = new Set(['window', 'document', 'console', 'fetch', 'setTimeout', 'clearTimeout',
    'setInterval', 'clearInterval', 'localStorage', 'navigator', 'URL', 'URLSearchParams',
    'FormData', 'Event', 'MouseEvent', 'IntersectionObserver', 'AbortController', 'Promise',
    'Math', 'JSON', 'Object', 'Array', 'String', 'Number', 'Boolean', 'Date', 'Set', 'Map',
    'RegExp', 'Error', 'TypeError', 'parseInt', 'parseFloat', 'isNaN', 'encodeURIComponent',
    'decodeURIComponent', 'atob', 'btoa', 'alert', 'confirm', 'requestAnimationFrame',
    // provided by the WebUI's own classic scripts
    'gradioApp', 'onUiLoaded', 'onAfterUiUpdate', 'onUiUpdate', 'onOptionsChanged', 'opts',
    'updateInput', 'selectCheckpoint', 'selectVAE', 'inputAccordionChecked', 'switch_to_txt2img',
    'globalThis', 'structuredClone', 'queueMicrotask']);

const KEYWORDS = /^(if|for|while|switch|catch|return|typeof|await|async|new|delete|void|in|of|do|else|function|throw|yield|super|case|import)$/;

// Comments are prose, and prose contains words followed by "(" — "card sizing
// (default values)" would otherwise look like a call to `sizing`. Template
// literals hold markup, not code, for the same reason.
function stripProse(text) {
    return text
        .replace(/\/\*[\s\S]*?\*\//g, ' ')
        .replace(/(^|[^:])\/\/[^\n]*/g, '$1')
        .replace(/`(?:[^`\\]|\\.)*`/g, '``')
        .replace(/'(?:[^'\\\n]|\\.)*'/g, "''")
        .replace(/"(?:[^"\\\n]|\\.)*"/g, '""');
}

for (const f of files) {
    const src = stripProse(readFileSync(f, 'utf8'));
    const known = new Set(GLOBALS);
    for (const m of src.matchAll(/(?:function|const|let|var|class)\s+(\w+)/g)) known.add(m[1]);
    for (const m of src.matchAll(/import\s*\{([^}]*)\}/gs))
        for (const p of m[1].split(',')) known.add(p.trim().split(/\s+as\s+/).pop().trim());
    // const { a, b: c } = await import(...)
    for (const m of src.matchAll(/const \{([^}]*)\}\s*=\s*await (?:import|shared)\(/gs))
        for (const p of m[1].split(',')) known.add(p.trim().split(':').pop().trim());
    // parameters and destructured bindings
    for (const m of src.matchAll(/\(([^)]*)\)\s*(?:=>|\{)/g))
        for (const p of m[1].split(','))
            for (const n of p.matchAll(/[A-Za-z_$][\w$]*/g)) known.add(n[0]);

    const missing = new Set();
    // A member call - after one dot: a.b(), a?.b(), a chain's next line - is
    // skipped; a spread's three are not one: ...fetchFiles(img) once went
    // unchecked for the dot before it.
    for (const m of src.matchAll(/(?<![\w$'"`])(?<!(?<!\.)\.)([a-z_$][\w$]*)\s*\(/g)) {
        const n = m[1];
        if (!known.has(n) && !KEYWORDS.test(n)) missing.add(n);
    }
    // Member calls are skipped above, which once let window.MMCommon.x() pass
    // as "a property access, not my problem" - while the global it reached for
    // had been replaced by imports. Any window.<name> that is not a browser
    // global, or is assigned nowhere, is a leftover.
    for (const m of src.matchAll(/window\.([A-Z]\w+)/g)) {
        const name = m[1];
        if (!new RegExp(`window\.${name}\s*=`).test(src)) {
            missing.add(`window.${name} (read, never assigned)`);
        }
    }

    if (missing.size) {
        console.log(`FAIL ${f.replace(ROOT, '')}: calls ${[...missing].join(', ')} — not declared or imported`);
        failures += missing.size;
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

// The JavaScript answer to pyflakes.
//
// Identical code with a missing import is still broken, and neither a text
// diff nor a syntax check sees it. Stage 2 only caught that class of mistake
// in Python because pyflakes existed; this is the equivalent for the modules.
//
//   1. every imported name must actually be exported by the file named
//   2. every bare identifier that gets called must be declared, imported,
//      or a known global
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

// --- 2. every called name is known -----------------------------------------
const GLOBALS = new Set(['window', 'document', 'console', 'fetch', 'setTimeout', 'clearTimeout',
    'setInterval', 'clearInterval', 'localStorage', 'navigator', 'URL', 'URLSearchParams',
    'FormData', 'Event', 'MouseEvent', 'IntersectionObserver', 'AbortController', 'Promise',
    'Math', 'JSON', 'Object', 'Array', 'String', 'Number', 'Boolean', 'Date', 'Set', 'Map',
    'RegExp', 'Error', 'TypeError', 'parseInt', 'parseFloat', 'isNaN', 'encodeURIComponent',
    'decodeURIComponent', 'atob', 'btoa', 'alert', 'confirm', 'requestAnimationFrame',
    // provided by the WebUI's own classic scripts
    'gradioApp', 'onUiLoaded', 'onAfterUiUpdate', 'onUiUpdate', 'opts', 'updateInput',
    'selectCheckpoint', 'selectVAE', 'inputAccordionChecked', 'switch_to_txt2img',
    'globalThis', 'structuredClone', 'queueMicrotask']);

const KEYWORDS = /^(if|for|while|switch|catch|return|typeof|await|new|delete|void|in|of|do|else|function|throw|yield|super|case|import)$/;

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
    for (const m of src.matchAll(/const \{([^}]*)\}\s*=\s*await import\(/gs))
        for (const p of m[1].split(',')) known.add(p.trim().split(':').pop().trim());
    // parameters and destructured bindings
    for (const m of src.matchAll(/\(([^)]*)\)\s*(?:=>|\{)/g))
        for (const p of m[1].split(','))
            for (const n of p.matchAll(/[A-Za-z_$][\w$]*/g)) known.add(n[0]);

    const missing = new Set();
    for (const m of src.matchAll(/(?<![.\w$'"`])([a-z_$][\w$]*)\s*\(/g)) {
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

console.log(`${files.length} modules checked — ` +
    (failures === 0 ? 'every name resolves.' : `${failures} unresolved.`));
process.exit(failures ? 1 : 0);

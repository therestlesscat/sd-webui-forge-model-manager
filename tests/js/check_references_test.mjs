// The checker of the modules' names (tests/tools/check_js_references.mjs),
// run on small made-up modules whose right answer is known. It only ever ran
// on the real ones, which hold no missing name: a read it could not see
// (#115's [...currentImages]) passed, and nothing said so (#116).
import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { ROOT, checker } from './harness.mjs';

const { check, done } = checker();
const CHECKER = `${ROOT}/tests/tools/check_js_references.mjs`;
const WORK = `${ROOT}/tests/work/check_references`;

// One module, checked alone: what the checker says of it, and whether it failed.
function verdict(code) {
    rmSync(WORK, { recursive: true, force: true });
    mkdirSync(`${WORK}/javascript`, { recursive: true });
    mkdirSync(`${WORK}/model_manager/ui`, { recursive: true });
    writeFileSync(`${WORK}/javascript/made_up.mjs`, code);
    const env = { ...process.env, MM_ROOT: `${WORK}/javascript` };
    try {
        return { failed: false, said: execFileSync(process.execPath, [CHECKER], { env, encoding: 'utf8' }) };
    } catch (e) {
        return { failed: true, said: String(e.stdout) };
    }
}
const fails = (code, words) => {
    const { failed, said } = verdict(code);
    return failed && said.includes(words);
};
const passes = (code) => !verdict(code).failed;

check('a name read and created nowhere fails, named: the #115 miss',
      fails('export function refresh(images = [...currentImages, 1]) { return images; }\n',
            'reads currentImages (line 1)'),
      true);
check('the same name in a default, a spread, an argument and a shorthand fails, each',
      [fails('export function f(a = gone) { return a; }\n', 'reads gone'),
       fails('export const all = [...gone];\n', 'reads gone'),
       fails('console.log(gone);\n', 'reads gone'),
       fails('export const o = { gone };\n', 'reads gone')],
      [true, true, true, true]);
check('a name called and created nowhere fails',
      fails('export function f() { return gone(); }\n', 'calls gone'), true);
check('a name created in another function, a loop\'s let after the loop, a catch name outside it: each fails',
      [fails('function a() { const images = []; return images; }\nexport function b() { return images; }\n',
             'reads images (line 2)'),
       fails('for (let i = 0; i < 2; i++) {}\nexport const last = i;\n', 'reads i (line 2)'),
       fails('try { JSON.parse(""); } catch (err) {}\nexport const e = err;\n', 'reads err (line 2)')],
      [true, true, true]);

check('an object key, a property after a dot and a method name pass',
      passes('export const o = { images: 1, show() { return this.images; } };\n'
             + 'export const n = o.images + o.show();\n'),
      true);
check('names made by destructuring, as parameters and in a catch pass where they are made',
      passes('export function f({ a, b: [c, ...d] }, e = 1, ...g) { try { return a + c + d + e + g; } '
             + 'catch (err) { return err; } }\n'
             + 'export function h() { var v = 1; { var w = v; } return w + later(); function later() { return 2; } }\n'),
      true);
check('the eight globals the checker did not know pass',
      passes('export const g = [DOMParser, ResizeObserver, MutationObserver, CustomEvent, File, DataTransfer, '
             + 'sessionStorage, restart_reload];\n'),
      true);

rmSync(WORK, { recursive: true, force: true });
done();

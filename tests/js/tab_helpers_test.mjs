// Small helpers the Model Manager and the Civitai Browser each kept a copy of,
// differing only in their ids (#84): applying a card size the server gave,
// greying the checkpoint-type filter where it does not apply, flashing what
// Save Search did, and scrolling to the top of a gallery. And a disabled
// filter's class, which was a tab's own - mm-filter-disabled, cb-filter-disabled
// - though both tabs dim one the same way. Each is written once now.
import { readdirSync, readFileSync } from 'node:fs';
import { ROOT, checker } from './harness.mjs';

const { check, done } = checker();
const files = [...readdirSync(`${ROOT}/javascript`).filter((f) => f.endsWith('.mjs')),
               ...readdirSync(`${ROOT}/javascript/shared`).filter((f) => f.endsWith('.mjs')).map((f) => `shared/${f}`)];
const code = (f) => readFileSync(`${ROOT}/javascript/${f}`, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1');
const writing = (pattern) => files.filter((f) => pattern.test(code(f))).sort();

check('a card size is applied, when it changes, in one place', writing(/\w+ !== \w+\.?[wW]idth \|\| \w+ !== \w+\.?[hH]eight/),
      ['shared/grid.mjs']);
check('the checkpoint-type filter is greyed in one place', writing(/'Only applies when Type is Checkpoint'/),
      ['shared/filters.mjs']);
check('Save Search says what it did in one place', writing(/textContent = 'Save Search'/), ['shared/filters.mjs']);
check('a gallery is scrolled to its top in one place', writing(/window\.scrollTo\(\{ top: targetY, behavior: 'smooth' \}\)/),
      ['shared/gallery.mjs']);

const css = readFileSync(`${ROOT}/style.css`, 'utf8');
check('a disabled filter has one class, a tab\'s own none',
      [writing(/(mm|cb)-filter-disabled/), /(mm|cb)-filter-disabled/.test(css), /\.filter-disabled\b/.test(css)],
      [[], false, true]);

done();

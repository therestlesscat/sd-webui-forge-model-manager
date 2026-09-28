// Loaded into a browser suite's node with --require when run.py records which
// suites a change needs (see --changed): notes the files the suite reads
// through fs - the tab markup the harness takes out of the Python files, the
// stylesheet. Which scripts it ran, Node's own coverage (NODE_V8_COVERAGE)
// says. Written to MM_TRACE_OUT at exit.
const fs = require('fs');
const path = require('path');
const { fileURLToPath } = require('url');

const seen = new Set();
const note = (p) => {
    try {
        if (typeof p === 'string') seen.add(path.resolve(p));
        else if (p instanceof URL) seen.add(fileURLToPath(p));
    } catch (e) { /* not a path */ }
};
for (const name of ['readFileSync', 'readFile', 'openSync', 'createReadStream']) {
    const original = fs[name];
    fs[name] = function (p, ...rest) { note(p); return original.call(this, p, ...rest); };
}
// So `import { readFileSync } from 'fs'` sees these too.
require('module').syncBuiltinESMExports();

const writeFileSync = fs.writeFileSync;
process.on('exit', () => {
    if (process.env.MM_TRACE_OUT) writeFileSync(process.env.MM_TRACE_OUT, JSON.stringify([...seen]));
});

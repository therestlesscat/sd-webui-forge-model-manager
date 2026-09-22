// primaryFile() must agree with DownloadService.pick_file_index for every
// version Civitai actually serves.
const fs = require('fs');
const vm = require('vm');
const { execSync } = require('child_process');

const path = require('path');

// The extension, found from this file rather than from a drive letter, so the
// suite runs wherever the repository happens to be checked out.
const REPO = path.resolve(__dirname, '..', '..').replace(/\\/g, '/');
const src = fs.readFileSync(REPO + '/javascript/civitai_browser.mjs', 'utf8');

const sandbox = { console };
sandbox.window = sandbox;
vm.createContext(sandbox);

function lift(name) {
    const m = src.match(new RegExp('^[ \\t]*(async )?function ' + name + '\\s*\\(', 'm'));
    const isAsync = !!m[1];
    let i = src.indexOf('(', m.index + m[0].length - 1), depth = 0;
    for (;; i++) { if (src[i] === '(') depth++; else if (src[i] === ')' && --depth === 0) break; }
    i = src.indexOf('{', i);
    const start = i;
    depth = 0;
    for (;; i++) { if (src[i] === '{') depth++; else if (src[i] === '}' && --depth === 0) break; }
    return vm.runInContext('(' + (isAsync ? 'async ' : '') + 'function'
        + src.slice(src.indexOf('(', m.index), start) + src.slice(start, i + 1) + ')', sandbox);
}
sandbox.primaryFileIndex = lift('primaryFileIndex');  // primaryFile delegates to it
const primaryFile = lift('primaryFile');

let failures = 0;
const check = (label, cond, extra) => {
    if (!cond) { failures++; console.log('FAIL ' + label + (extra ? '\n  ' + extra : '')); }
};

check('no version', primaryFile(undefined) === undefined);
check('no files key', primaryFile({}) === undefined);
check('empty files', primaryFile({ files: [] }) === undefined);
check('single file', primaryFile({ files: [{ name: 'a' }] }).name === 'a');
check('primary first', primaryFile({ files: [{ name: 'a', primary: true }, { name: 'b' }] }).name === 'a');
check('primary second', primaryFile({ files: [{ name: 'a' }, { name: 'b', primary: true }] }).name === 'b');
check('none primary falls back', primaryFile({ files: [{ name: 'a' }, { name: 'b' }] }).name === 'a');

// Against live data, including the model that started this.
const raw = execSync('curl -s --max-time 40 "https://civitai.com/api/v1/models?limit=100&types=Checkpoint&sort=Most%20Downloaded"',
                     { encoding: 'buffer', maxBuffer: 64 * 1024 * 1024 });
const items = JSON.parse(raw.toString('utf8')).items;

let differs = 0, versions = 0;
for (const m of items) {
    for (const v of m.modelVersions) {
        if (!(v.files || []).length) continue;
        versions++;
        const chosen = primaryFile(v);
        // The same rule the Python side applies.
        const expected = v.files.find(f => f.primary) || v.files[0];
        check('agrees for version ' + v.id, chosen === expected);
        if (chosen !== v.files[0]) differs++;
    }
}
console.log('live versions: ' + versions + ', panel now differs from files[0] for ' + differs);

// The specific model reported: the panel must stop naming the fp32 file.
const cr = JSON.parse(execSync(
    'curl -s --max-time 40 "https://civitai.com/api/v1/models?limit=1&query=CyberRealistic%20Classic"',
    { encoding: 'buffer' }).toString('utf8')).items[0];
for (const v of cr.modelVersions.slice(0, 3)) {
    const chosen = primaryFile(v);
    const md = chosen.metadata || {};
    check('CyberRealistic ' + v.name + ' picks primary', chosen.primary === true,
          chosen.name + ' primary=' + chosen.primary);
    console.log('  ' + v.name.padEnd(22) + ' panel shows: ' + (md.size + '/' + md.fp).padEnd(12)
                + (chosen.sizeKB / 1048576).toFixed(2) + ' GB  (was '
                + (v.files[0].sizeKB / 1048576).toFixed(2) + ' GB)');
}

console.log(failures === 0 ? 'All checks passed.' : failures + ' check(s) failed.');
process.exit(failures ? 1 : 0);

// File picker: labels, default selection, and the in-place update.
const fs = require('fs');
const vm = require('vm');
const { execSync } = require('child_process');

const path = require('path');

// The extension, found from this file rather than from a drive letter, so the
// suite runs wherever the repository happens to be checked out.
const REPO = path.resolve(__dirname, '..', '..').replace(/\\/g, '/');
const src = fs.readFileSync(REPO + '/javascript/civitai_browser.mjs', 'utf8');

const els = {};
const sandbox = {
    console: { log() {}, warn() {} },
    parseInt,
    Number,
    document: {
        getElementById: id => els[id] ?? null,
        createElement: () => {
            const el = { _t: '' };
            Object.defineProperty(el, 'textContent', { set(v) { el._t = String(v); }, get: () => el._t });
            Object.defineProperty(el, 'innerHTML', {
                get: () => el._t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
            });
            return el;
        },
    },
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(REPO + '/javascript/shared/common.mjs', 'utf8')
    .replace(/^export /gm, ''), sandbox);
sandbox.escapeHtml = sandbox.escapeHtml;
// The browser keeps its own formatFileSize (2 decimals) on purpose.
sandbox.formatFileSize = (bytes) => {
    if (!bytes) return 'Unknown';
    if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(2) + ' GB';
    if (bytes >= 1048576) return (bytes / 1048576).toFixed(2) + ' MB';
    if (bytes >= 1024) return (bytes / 1024).toFixed(2) + ' KB';
    return bytes + ' B';
};

function lift(name) {
    const m = src.match(new RegExp('^[ \\t]*(async )?function ' + name + '\\s*\\(', 'm'));
    if (!m) throw new Error('not found: ' + name);
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

sandbox.selectedFileIndex = null;
const primaryFileIndex = lift('primaryFileIndex');
sandbox.primaryFileIndex = primaryFileIndex;
const primaryFile = lift('primaryFile');
const chosenFileIndex = lift('chosenFileIndex');
sandbox.chosenFileIndex = chosenFileIndex;
const describeFile = lift('describeFile');
const selectFile = lift('selectFile');

let failures = 0;
const check = (label, cond, extra) => {
    if (!cond) { failures++; console.log('FAIL ' + label + (extra ? '\n  ' + extra : '')); }
};

const FILES = [
    { id: 852531, name: 'cr_classic40_pruned_fp32.safetensors', sizeKB: 4165134,
      type: 'Model', metadata: { format: 'SafeTensor', size: 'pruned', fp: 'fp32' } },
    { id: 852488, name: 'cr_classic40_pruned_fp16.safetensors', sizeKB: 2082642, primary: true,
      type: 'Model', metadata: { format: 'SafeTensor', size: 'pruned', fp: 'fp16' } },
    { id: 900001, name: 'vae-ft-mse.safetensors', sizeKB: 326000, type: 'VAE', metadata: {} },
];
const version = { id: 42, files: FILES };

// --- default is the primary, not files[0] -----------------------------------
sandbox.selectedFileIndex = null;
check('default index is primary', chosenFileIndex(version) === 1, String(chosenFileIndex(version)));
check('primaryFile is the fp16', primaryFile(version).id === 852488);
check('primaryFileIndex with no primary', primaryFileIndex({ files: [{ id: 1 }, { id: 2 }] }) === 0);
check('empty version safe', primaryFileIndex(undefined) === 0 && primaryFile(undefined) === undefined);

// --- labels -----------------------------------------------------------------
check('fp32 label', describeFile(FILES[0]) === 'pruned fp32 - 3.97 GB', describeFile(FILES[0]));
check('fp16 label', describeFile(FILES[1]) === 'pruned fp16 - 1.99 GB', describeFile(FILES[1]));
check('VAE label falls back to type', describeFile(FILES[2]) === 'VAE - 318.36 MB', describeFile(FILES[2]));
check('no metadata, no type', describeFile({ name: 'thing.zip', sizeKB: 1024 }) === 'thing.zip - 1.00 MB',
      describeFile({ name: 'thing.zip', sizeKB: 1024 }));
check('training data keeps its type',
      describeFile({ name: 'data.zip', sizeKB: 2048, type: 'Training Data' }) === 'Training Data - 2.00 MB',
      describeFile({ name: 'data.zip', sizeKB: 2048, type: 'Training Data' }));
check('model file with metadata keeps no type suffix', !describeFile(FILES[1]).includes('Model'));
check('empty file object', typeof describeFile({}) === 'string');

// --- selectFile updates the panel in place ----------------------------------
sandbox.getSelectedVersion = () => version;
sandbox.selectedModel = { id: 7 };
els.cb_file_name = { textContent: '' };
els.cb_file_size = { textContent: '' };
els.cb_download_btn = { _attrs: {}, setAttribute(k, v) { this._attrs[k] = v; } };

selectFile('0');
check('picked index recorded', sandbox.selectedFileIndex === 0, String(sandbox.selectedFileIndex));
check('name cell updated', els.cb_file_name.textContent === FILES[0].name, els.cb_file_name.textContent);
check('size cell updated', els.cb_file_size.textContent === '3.97 GB', els.cb_file_size.textContent);
check('button carries the file id',
      els.cb_download_btn._attrs.onclick === 'window.cbDownload(7, 42, 852531)',
      els.cb_download_btn._attrs.onclick);
check('chosen index follows the pick', chosenFileIndex(version) === 0);

selectFile('2');
check('switching to the VAE', sandbox.selectedFileIndex === 2);
check('button id follows', els.cb_download_btn._attrs.onclick === 'window.cbDownload(7, 42, 900001)',
      els.cb_download_btn._attrs.onclick);

// Out-of-range and junk must be ignored, leaving the last good pick.
selectFile('9');
check('out of range ignored', sandbox.selectedFileIndex === 2);
selectFile('not a number');
check('junk ignored', sandbox.selectedFileIndex === 2);

// A stale index from a previous version must not leak through.
sandbox.selectedFileIndex = 5;
check('stale index falls back to primary', chosenFileIndex(version) === 1, String(chosenFileIndex(version)));

// --- the dropdown only exists when there is a choice ------------------------
const renderSrc = src.slice(src.indexOf('const fileOptions'), src.indexOf('const fileOptions') + 600);
check('gated on more than one file', /versionFiles\.length > 1/.test(renderSrc), renderSrc.slice(0, 80));

// --- against live data ------------------------------------------------------
const cr = JSON.parse(execSync(
    'curl -s --max-time 40 "https://civitai.com/api/v1/models?limit=1&query=CyberRealistic%20Classic"',
    { encoding: 'buffer' }).toString('utf8')).items[0];
sandbox.selectedFileIndex = null;
for (const v of cr.modelVersions.slice(0, 3)) {
    const files = v.files || [];
    const idx = chosenFileIndex(v);
    check('live default is primary for ' + v.name, files.length === 0 || files[idx].primary === true);
    console.log('  ' + v.name.padEnd(22) + (files.length > 1 ? 'picker: ' : 'single: ')
                + files.map(describeFile).join('  |  '));
}

console.log(failures === 0 ? 'All checks passed.' : failures + ' check(s) failed.');
process.exit(failures ? 1 : 0);

// The long job - Sync with Civitai; Scan Disk too, until 0.48 - in a module of its own
// (#92). Their dialogs, starting one, following it and cancelling it, their
// state, and finding one still running when the page loads lived in the Model
// Manager's script, and the notes reached them through the registry.
//
// Here: the Model Manager's script keeps none of it, only connecting the jobs
// to its status line and its grid; and the notes open the dialogs through the
// module's own API.
import { readFileSync } from 'node:fs';
import { ROOT, checker } from './harness.mjs';

const { check, done } = checker();
const code = (path) => readFileSync(`${ROOT}/javascript/${path}`, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1');
const tab = code('model_manager.mjs');
const JOBS = ['startSync', 'pollSyncProgress', 'cancelSync', 'openSyncDialog', 'closeSyncDialog', 'startSyncFromDialog',
              'startMetadataSync', 'refreshSyncEstimate', 'updateSyncUI', 'checkOngoingProcesses'];
check('the Model Manager\'s script defines none of the jobs',
      JOBS.filter((name) => new RegExp(`function ${name}\\(`).test(tab)), []);
check('nor keeps their state', ['isSyncing', 'syncPollInterval']
    .filter((name) => new RegExp(`let ${name}\\b`).test(tab)), []);
check('it connects them to its status line and its grid', /connectJobs\(\{/.test(tab), true);

const notes = code('shared/notes.mjs');
check('the notes open the dialog through the jobs\' own API, not the registry',
      [/showSyncDialog\(/.test(notes), /call\('modelManager\.open(Sync|Scan)Dialog'/.test(notes)],
      [true, false]);

let jobs = '';
try { jobs = readFileSync(`${ROOT}/javascript/shared/jobs.mjs`, 'utf8'); } catch { /* not there */ }
check('the jobs\' module offers that API',
      ['connectJobs', 'bindJobControls', 'checkOngoingProcesses', 'showSyncDialog']
          .filter((name) => !new RegExp(`export (async )?function ${name}\\(`).test(jobs)), []);
// Every sync walks the library (0.48): Scan Disk is gone, not hidden.
check('and nothing of Scan Disk is left in it',
      ['showScanDialog', 'openScanDialog', 'startScan', 'pollScanProgress', 'isScanning', '/model-manager/scan']
          .filter((name) => jobs.includes(name)), []);

done();

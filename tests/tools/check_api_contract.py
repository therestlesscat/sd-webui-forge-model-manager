"""
Pass 1, continued: the browser and the endpoints agree on parameter names.

A renamed form field is invisible to both pyflakes and to a JS syntax check -
the request simply arrives without it and the endpoint quietly uses its
default. These are the sync endpoints the dialog drives, so check the names
the JS sends against the names the endpoints declare.
"""
import ast
import io
import re
import os
import os
import sys

# tests/tools/<this file> -> three levels up is the extension
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)      # the checks read files by repo-relative path

failures = []


def fail(m):
    failures.append(m)
    print('FAIL %s' % m)


# --- what the endpoints accept ---------------------------------------------
endpoints = {}
for path in ('model_manager/api/jobs.py', 'model_manager/api/models.py'):
    tree = ast.parse(io.open(path, encoding='utf-8').read())
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and dec.args):
                continue
            route = dec.args[0].value
            method = dec.func.attr.upper() if isinstance(dec.func, ast.Attribute) else '?'
            names = {a.arg for a in node.args.args} | {a.arg for a in node.args.kwonlyargs}
            endpoints[(method, route)] = names

print('--- endpoints found ---')
for (method, route), names in sorted(endpoints.items()):
    print('   %-5s %-38s %s' % (method, route, ', '.join(sorted(names)) or '(none)'))

# --- what the browser sends -------------------------------------------------
js = io.open('javascript/model_manager.mjs', encoding='utf-8').read()

print('\n--- the dialog\'s POST body ---')
m = re.search(r"const body = new URLSearchParams\(\{(.*?)\}\);(.*?)body\.set\('(\w+)'",
              js, re.S)
if not m:
    fail('could not find the sync POST body in the JS')
else:
    sent = set(re.findall(r'(\w+):\s', m.group(1))) | {m.group(3)}
    accepted = endpoints.get(('POST', '/model-manager/sync/metadata'), set())
    print('   sends   : %s' % ', '.join(sorted(sent)))
    print('   accepts : %s' % ', '.join(sorted(accepted)))
    for key in sorted(sent - accepted):
        fail('JS posts "%s" to /sync/metadata, which does not accept it' % key)

print('\n--- the estimate query ---')
# anchored inside refreshSyncEstimate - there is another `const params` in
# the file, for the model-details request
estimate_fn = js[js.index('function refreshSyncEstimate'):]
estimate_fn = estimate_fn[:estimate_fn.index('\n}\n')]
m = re.search(r'const params = \{(.*?)\};', estimate_fn, re.S)
if not m:
    fail('could not find the estimate params in the JS')
else:
    sent = set(re.findall(r'(\w+):\s', m.group(1)))
    sent.add('paths')            # added conditionally, just below
    accepted = endpoints.get(('GET', '/model-manager/sync/estimate'), set())
    print('   sends   : %s' % ', '.join(sorted(sent)))
    print('   accepts : %s' % ', '.join(sorted(accepted)))
    for key in sorted(sent - accepted):
        fail('JS asks /sync/estimate for "%s", which it does not accept' % key)

print('\n--- the paths_only request ---')
if 'filters.paths_only = true' not in js:
    fail('the JS no longer sets paths_only')
elif 'paths_only' not in endpoints.get(('GET', '/model-manager/models'), set()):
    fail('/model-manager/models does not accept paths_only')
else:
    print('   paths_only accepted by /model-manager/models')

# --- what the JS reads back -------------------------------------------------
print('\n--- fields the JS reads out of the estimate ---')
read = set(re.findall(r'estimate\.(\w+)', js)) | \
       {'requests.' + k for k in re.findall(r'requests\.(\w+)', js)} | \
       {'seconds.' + k for k in re.findall(r'seconds\.(\w+)', js)}
sync_src = io.open('model_manager/sync_service.py', encoding='utf-8').read()
returned = set(re.findall(r'"(\w+)":', sync_src))
missing = sorted(k for k in read if k.split('.')[-1] not in returned)
print('   reads   : %s' % ', '.join(sorted(read)))
for k in missing:
    fail('JS reads estimate.%s, which estimate_metadata_sync() never returns' % k)
if not missing:
    print('   every field read is one the estimate returns')

print()
print('PASS 1 (contract): %s' % ('browser and endpoints agree' if not failures
                                 else '%d mismatch(es)' % len(failures)))
sys.exit(1 if failures else 0)

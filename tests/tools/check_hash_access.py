"""
Stored hashes are read through model_manager/hashing.py (#62).

They arrive in either case - the hasher writes values upper case, Civitai's
lists and older rows lower - and every reader used to fold them itself; one
that forgot would match nothing. hashing.read_hashes() and hash_key() fold
them once. This fails, naming the line, on:

  1. a row's file_hashes read outside db/ and hashing.py other than straight
     into read_hashes() - or names_this_file() / HashResult.from_stored(),
     which go through it;
  2. SQL that looks inside file_hashes (json_extract, LIKE, =, IN) - it is
     JSON, compared only after it is read;
  3. the resource_hashes table touched outside db/models_ops.py, the one
     place that keeps its keys with hash_key().

A guard against the ordinary slip, read from the source - not a proof.
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACKAGE = os.path.join(ROOT, 'model_manager')
READERS = {'read_hashes', 'names_this_file', 'from_stored'}
# Looking inside it, not setting it: an upsert's "SET file_hashes = ..." is fine.
SQL_INSIDE = re.compile(r'json_extract\([^)]*file_hashes|file_hashes\s+LIKE'
                        r'|\b(WHERE|AND|OR)\s+[\w.]*file_hashes\s*(=|IN\b)', re.I)
RESOURCE_TABLE_HOME = {os.path.join('db', 'models_ops.py'), os.path.join('db', 'migrations.py')}

failures = []


def fail(path, node, why):
    failures.append('%s:%d: %s' % (os.path.relpath(path, ROOT), node.lineno, why))


def call_name(node):
    func = node.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, 'id', '')


def reads_file_hashes(node):
    """row["file_hashes"] or row.get("file_hashes")."""
    if isinstance(node, ast.Subscript):
        key = node.slice
        return isinstance(key, ast.Constant) and key.value == 'file_hashes'
    if isinstance(node, ast.Call) and call_name(node) == 'get' and node.args:
        first = node.args[0]
        return isinstance(first, ast.Constant) and first.value == 'file_hashes'
    return False


for folder, _, files in os.walk(PACKAGE):
    for name in files:
        if not name.endswith('.py'):
            continue
        path = os.path.join(folder, name)
        rel = os.path.relpath(path, PACKAGE)
        tree = ast.parse(open(path, encoding='utf-8').read(), path)
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(tree):
            docstring = isinstance(parents.get(node), ast.Expr)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and not docstring:
                if SQL_INSIDE.search(node.value):
                    fail(path, node, 'SQL looks inside file_hashes; read the column, then read_hashes()')
                if 'resource_hashes' in node.value and rel not in RESOURCE_TABLE_HOME:
                    fail(path, node, 'resource_hashes is db/models_ops.py\'s, which keys it with hash_key()')
            if rel == 'hashing.py' or rel.startswith('db' + os.sep):
                continue
            if reads_file_hashes(node) and not isinstance(getattr(node, 'ctx', None), ast.Store):
                parent = parents.get(node)
                if not (isinstance(parent, ast.Call) and node in parent.args and call_name(parent) in READERS):
                    fail(path, node, 'file_hashes read without read_hashes() - stored hashes come in either case')

print('\n'.join('FAIL ' + f for f in failures) or 'Stored hashes are read through hashing.py.')
sys.exit(1 if failures else 0)

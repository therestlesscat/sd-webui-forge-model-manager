"""
Pass 1: every cross-module reference resolves.

pyflakes checks names within a module. It does not check that
`from .civitai import apply_generation_data` names something the package
actually exports, that a facade method delegates to a method the ops class
has, or that a call site matches the signature it is calling. Those are the
mistakes that survive a move or a rename, so they get their own pass.
"""
import ast
import importlib
import io
import inspect
import os
import sys

# tests/tools/<this file> -> three levels up is the extension
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)      # the checks read files by repo-relative path

failures = []


def fail(what):
    failures.append(what)
    print('FAIL %s' % what)


def py_files(root='model_manager'):
    for dirpath, _, names in os.walk(root):
        for n in names:
            if n.endswith('.py'):
                yield os.path.join(dirpath, n).replace('\\', '/')


def module_name(path):
    return path[:-3].replace('/', '.').replace('.__init__', '')


# ---------------------------------------------------------------- 1. imports
print('--- relative imports resolve to real names ---')
checked = 0
for path in py_files():
    tree = ast.parse(io.open(path, encoding='utf-8').read())
    here = module_name(path)
    package = here.rsplit('.', 1)[0] if '.' in here else here
    if path.endswith('__init__.py'):
        package = here

    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.level:
            continue
        base = package
        for _ in range(node.level - 1):
            base = base.rsplit('.', 1)[0]
        target = '%s.%s' % (base, node.module) if node.module else base
        try:
            mod = importlib.import_module(target)
        except Exception as e:
            # fastapi and friends are WebUI dependencies, absent here
            if 'fastapi' in str(e) or 'No module named' in str(e) and 'model_manager' not in str(e):
                continue
            fail('%s: cannot import %s (%s)' % (path, target, e))
            continue
        for alias in node.names:
            if alias.name == '*':
                continue
            checked += 1
            if not hasattr(mod, alias.name):
                fail('%s: %s has no %s' % (path, target, alias.name))
print('   %d imported names checked' % checked)


# ------------------------------------------------------------ 2. the facade
print('--- ModelsDatabase delegates to methods that exist ---')
from model_manager.db.database import ModelsDatabase

src = io.open('model_manager/db/database.py', encoding='utf-8').read()
tree = ast.parse(src)
ops_attr = {}
for node in ast.walk(tree):
    # self._models = ModelsOps(...)
    if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
        for t in node.targets:
            if (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                    and t.value.id == 'self' and isinstance(node.value.func, ast.Name)):
                ops_attr[t.attr] = node.value.func.id

import model_manager.db.database as dbmod
delegations = 0
for node in ast.walk(tree):
    if not isinstance(node, ast.FunctionDef):
        continue
    for call in ast.walk(node):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
            continue
        owner = call.func.value
        if not (isinstance(owner, ast.Attribute) and isinstance(owner.value, ast.Name)
                and owner.value.id == 'self' and owner.attr in ops_attr):
            continue
        delegations += 1
        cls = getattr(dbmod, ops_attr[owner.attr], None)
        if cls is None:
            fail('database.py: %s is built from unknown class %s'
                 % (owner.attr, ops_attr[owner.attr]))
            continue
        if not hasattr(cls, call.func.attr):
            fail('database.py: %s.%s() -> %s has no %s()'
                 % (owner.attr, call.func.attr, cls.__name__, call.func.attr))
            continue
        # the arity has to agree too
        target = getattr(cls, call.func.attr)
        try:
            sig = inspect.signature(target)
            sig.bind(None, *[None] * len(call.args),
                     **{k.arg: None for k in call.keywords if k.arg})
        except TypeError as e:
            fail('database.py: %s.%s(...) does not fit %s.%s%s - %s'
                 % (owner.attr, call.func.attr, cls.__name__, call.func.attr,
                    inspect.signature(target), e))
print('   %d delegating calls checked across %d ops objects'
      % (delegations, len(ops_attr)))


# ------------------------------------------- 3. call sites fit the signature
print('--- call sites fit the functions they call ---')
WATCHED = {
    'sync_metadata': 'model_manager.sync_service',
    'get_linked_versions': 'model_manager.db.database',
    'count_images_by_version': 'model_manager.db.database',
    'estimate_metadata_sync': 'model_manager.sync_service',
    'sync_window_counts': 'model_manager.sync_service',
    'window_cutoff': 'model_manager.sync_service',
    'apply_generation_data': 'model_manager.civitai.prompt_filter',
    'generation_ids_needing_lookup': 'model_manager.civitai.prompt_filter',
    'enrich_images_with_generation_data': 'model_manager.civitai.prompt_filter',
    'model_level': 'model_manager.nsfw',
    'model_level_sql': 'model_manager.nsfw',
}
sites = 0
for path in py_files():
    tree = ast.parse(io.open(path, encoding='utf-8').read())
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        name = (call.func.id if isinstance(call.func, ast.Name)
                else call.func.attr if isinstance(call.func, ast.Attribute) else None)
        if name not in WATCHED:
            continue
        mod = importlib.import_module(WATCHED[name])
        target = getattr(mod, name, None)
        if target is None:                      # a method on a class
            for obj in vars(mod).values():
                if inspect.isclass(obj) and hasattr(obj, name):
                    target = getattr(obj, name)
                    break
        if target is None:
            fail('%s:%d: %s is not defined in %s' % (path, call.lineno, name, WATCHED[name]))
            continue
        sites += 1
        sig = inspect.signature(target)
        args = [None] * len(call.args)
        if isinstance(call.func, ast.Attribute) and inspect.isfunction(target) \
                and list(sig.parameters)[:1] == ['self']:
            args = [None] + args
        if any(isinstance(a, ast.Starred) for a in call.args) \
                or any(k.arg is None for k in call.keywords):
            continue                            # *args / **kwargs, unresolvable here
        try:
            sig.bind(*args, **{k.arg: None for k in call.keywords})
        except TypeError as e:
            fail('%s:%d: %s%s does not accept this call - %s'
                 % (path, call.lineno, name, sig, e))
print('   %d call sites checked against %d signatures' % (sites, len(WATCHED)))

print()
print('PASS 1: %s' % ('all references resolve' if not failures
                      else '%d problem(s)' % len(failures)))
sys.exit(1 if failures else 0)

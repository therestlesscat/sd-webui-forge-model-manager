"""
Forge is asked through model_manager/forge_host.py (#82).

Twenty files of the extension's package imported Forge's `modules` and
`modules_forge` themselves, each with its own guard for a WebUI that was not
there, and those that asked something Neo and the original Forge keep in
different places each had to know both. This fails, naming the line, on:

  1. an import of `modules` or `modules_forge`, at the top of a file or
     inside a function;
  2. a call that names one of them in a string - sys.modules.get(...),
     importlib.util.find_spec(...), import_module(...) - which reaches Forge
     without an import statement;

anywhere in the package but forge_host.py, and ui/settings.py, which builds
Forge's settings page with Forge's own option types. The entry scripts, in
scripts/, are Forge's callbacks and outside the package.

A guard against the ordinary slip, read from the source - not a proof.
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACKAGE = os.path.join(ROOT, 'model_manager')
ALLOWED = {'forge_host.py', os.path.join('ui', 'settings.py')}
FORGE = ('modules', 'modules_forge')


def names_forge(name):
    return any(name == top or name.startswith(top + '.') for top in FORGE)


def looks_up_a_module(node):
    """sys.modules.get(...), sys.modules[...], find_spec, import_module, __import__."""
    if isinstance(node, ast.Subscript):
        return ast.unparse(node.value) == 'sys.modules'
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == 'get':
        return ast.unparse(func.value) == 'sys.modules'
    return (func.attr if isinstance(func, ast.Attribute) else getattr(func, 'id', '')) in (
        'find_spec', 'import_module', '__import__')


failures = []
for folder, _, files in os.walk(PACKAGE):
    for name in files:
        if not name.endswith('.py'):
            continue
        path = os.path.join(folder, name)
        rel = os.path.relpath(path, PACKAGE)
        if rel in ALLOWED:
            continue
        for node in ast.walk(ast.parse(open(path, encoding='utf-8').read(), path)):
            if isinstance(node, ast.Import):
                found = [alias.name for alias in node.names if names_forge(alias.name)]
            elif isinstance(node, ast.ImportFrom):
                found = [node.module] if not node.level and names_forge(node.module or '') else []
            elif isinstance(node, (ast.Call, ast.Subscript)) and looks_up_a_module(node):
                named = node.args if isinstance(node, ast.Call) else [node.slice]
                found = [arg.value for arg in named
                         if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and names_forge(arg.value)]
            else:
                continue
            for what in found:
                failures.append('%s:%d: reaches %s; ask forge_host.py' % (os.path.relpath(path, ROOT), node.lineno, what))

print('\n'.join('FAIL ' + f for f in failures) or 'Forge is asked through forge_host.py.')
sys.exit(1 if failures else 0)

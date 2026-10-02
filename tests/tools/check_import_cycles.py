"""
The extension's package imports without a cycle (#67).

architecture.py imported file_identity.py, which imported it back. It worked
only because one side imported inside a function, after both had loaded - a
cycle hidden, not removed, and one moved line from failing at startup. So an
import inside a function counts here like any other, and so does a package's
__init__, which importing anything inside the package runs first.

This fails, naming each import on the cycle, when one module of the package
leads back to itself.
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACKAGE = 'model_manager'

modules = {}            # dotted name -> path
for folder, _, files in os.walk(os.path.join(ROOT, PACKAGE)):
    for name in files:
        if name.endswith('.py'):
            path = os.path.join(folder, name)
            dotted = os.path.relpath(path, ROOT)[:-3].replace(os.sep, '.')
            modules[dotted[:-len('.__init__')] if dotted.endswith('.__init__') else dotted] = path


def imported(module, path, node):
    """The package's modules an import statement loads, its packages included."""
    if isinstance(node, ast.Import):
        targets = [alias.name for alias in node.names]
    else:
        base = node.module or ''
        if node.level:
            here = module.split('.') if path.endswith('__init__.py') else module.split('.')[:-1]
            base = '.'.join(here[:len(here) - node.level + 1] + ([base] if base else []))
        # "from .x import y" loads x.y when y is a module, x either way
        targets = [base + '.' + alias.name if base + '.' + alias.name in modules else base
                   for alias in node.names]
    found = []
    for target in targets:
        parts = target.split('.')
        for end in range(2, len(parts) + 1):
            name = '.'.join(parts[:end])
            # A package this module is inside is already running when it imports.
            if name in modules and name != module and not module.startswith(name + '.'):
                found.append(name)
    return found


edges = {}              # module -> {module it imports: line}
for module, path in modules.items():
    for node in ast.walk(ast.parse(open(path, encoding='utf-8').read(), path)):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for target in imported(module, path, node):
                edges.setdefault(module, {}).setdefault(target, node.lineno)


def cycle_from(start):
    """A path of imports from start back to itself, or None."""
    trail, seen = [start], set()

    def walk(module):
        for target in sorted(edges.get(module, {})):
            if target == start:
                return trail + [start]
            if target not in seen:
                seen.add(target)
                trail.append(target)
                found = walk(target)
                if found:
                    return found
                trail.pop()
        return None
    return walk(start)


failures, reported = [], set()
for module in sorted(modules):
    if module in reported:
        continue
    cycle = cycle_from(module)
    if cycle:
        reported.update(cycle)
        failures.append('a cycle:\n' + '\n'.join(
            '   %s:%d imports %s' % (os.path.relpath(modules[a], ROOT), edges[a][b], b)
            for a, b in zip(cycle, cycle[1:])))

print('\n'.join('FAIL ' + f for f in failures)
      or 'The package imports without a cycle (%d modules).' % len(modules))
sys.exit(1 if failures else 0)

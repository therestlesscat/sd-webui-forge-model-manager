"""
The grid's options are declared once: db.GridQuery (#71).

They were restated in four places - the endpoint's call, the database facade
(every keyword re-declared and forwarded), models_ops (**filters) and
query.py - and the facade had the licence choices as bool where query.py
reads "true", "false" and "unknown": a caller trusting it got no filter, and
no error. What is checked: the facade, models_ops and query.py take a
GridQuery and nothing but it (and `counts`, filled on the way out); the
endpoint sets every field of it, so a new option cannot be declared and left
unparsed; and the licence choices are the strings the query reads.
"""
import ast
import dataclasses
import inspect
import os
import sys
import typing

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

webui_stub.install()

from model_manager.db import GridQuery, ModelsDatabase   # noqa: E402
from model_manager.db import query as query_module       # noqa: E402
from model_manager.db.models_ops import ModelsOps        # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


fields = [field.name for field in dataclasses.fields(GridQuery)]
for name, function in (('the facade', ModelsDatabase.query_models_grouped),
                       ('models_ops', ModelsOps.query_models_grouped),
                       ('query.py', query_module.query_models_grouped)):
    parameters = [p for p in inspect.signature(function).parameters if p not in ('self', 'cursor_factory')]
    check('%s takes a GridQuery, and counts' % name, parameters, ['grid', 'counts'])

tree = ast.parse(open(os.path.join(ROOT, 'model_manager', 'api', 'models.py'), encoding='utf-8').read())
made = [node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'GridQuery']
check('the endpoint makes the GridQuery once', len(made), 1)
if made:
    check('and sets every option of it, so none is declared and left unparsed',
          sorted(set(fields) - {keyword.arg for keyword in made[0].keywords}), [])

hints = typing.get_type_hints(GridQuery)
check('the licence choices are the strings the query reads - "true", "false", "unknown"',
      [hints['allow_derivatives'], hints['allow_different_license']], [typing.Optional[str]] * 2)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)

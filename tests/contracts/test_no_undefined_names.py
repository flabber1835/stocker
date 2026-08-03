"""Undefined names in service code — the bug class that only fires in production.

TWICE in one session a NameError reached the live book, and both times the shape
was identical:

    book_size        defined in one function, referenced in another
    actual_weights   the PARAMETER NAME of a callee, written where the local
                     `live_weights` belonged

Both sat inside a branch gated on a config flag. Every unit test passed, because
unit tests exercise the pure helpers rather than the wired call site, and every
chain run passed too — until the day the flag was switched on live. Then the
delta step raised, the book got no target and no trade proposals, and the failure
looked like a strategy problem rather than a typo.

A linter would catch this in a second, but pyflakes/ruff/flake8 are not
dependencies of this repo and adding one to every image for one rule is a worse
trade than 150 lines of AST. So this test IS the rule: it resolves each
function's scope and reports any name that is read but never bound.

Deliberately conservative — every ambiguity resolves toward NOT reporting:

  * comprehension and class scopes are folded into the enclosing function
    (over-permissive, never a false positive)
  * a `global`/`nonlocal` declaration binds the name
  * conditional imports, try/except imports and star-imports all bind
  * attribute access (`x.y`) checks only `x`

A false NEGATIVE costs one missed typo. A false POSITIVE costs trust in the
suite, and a test nobody trusts gets deleted.
"""
from __future__ import annotations

import ast
import builtins
import os

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Every service whose code runs in the live trading chain. Adding a service here
# is the point — the check is worth most exactly where a NameError would stop
# the book.
_TARGETS = [
    "services/pipeline/app/main.py",
    "services/pipeline/app/engine.py",
    "services/pipeline/app/factors.py",
    "services/pipeline/app/factor_inputs.py",
    "services/pipeline/app/vendor_shadow.py",
    "services/scheduler/app/main.py",
    "services/portfolio-builder/app/main.py",
    "services/llm-vetter/app/main.py",
    "services/trade-executor/app/main.py",
    "services/risk-service/app/main.py",
    "services/av-ingestor/app/main.py",
    "services/api/app/main.py",
    "services/bt-engine/app/sim.py",
    "services/bt-engine/app/postmortem.py",
    "services/bt-data/app/main.py",
]

_BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__package__"}


def _bound_by(node: ast.AST) -> set[str]:
    """Every name this node BINDS, looking through nested statements but NOT
    through nested function bodies (those get their own scope pass)."""
    out: set[str] = set()

    def add_target(t: ast.AST) -> None:
        if isinstance(t, ast.Name):
            out.add(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                add_target(e)
        elif isinstance(t, ast.Starred):
            add_target(t.value)
        # Attribute/Subscript targets bind nothing new

    def walk(n: ast.AST, *, top: bool) -> None:
        for child in ast.iter_child_nodes(n):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.add(child.name)          # the def binds its own name
                continue                     # body is a separate scope
            if isinstance(child, ast.ClassDef):
                out.add(child.name)
                walk(child, top=False)       # fold class body in (permissive)
                continue
            if isinstance(child, ast.Lambda):
                continue
            if isinstance(child, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets = (child.targets if isinstance(child, ast.Assign)
                           else [child.target])
                for t in targets:
                    add_target(t)
            elif isinstance(child, (ast.For, ast.AsyncFor)):
                add_target(child.target)
            elif isinstance(child, (ast.With, ast.AsyncWith)):
                for item in child.items:
                    if item.optional_vars is not None:
                        add_target(item.optional_vars)
            elif isinstance(child, ast.ExceptHandler):
                if child.name:
                    out.add(child.name)
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                for a in child.names:
                    if a.name == "*":
                        out.add("*")         # star import → give up on this scope
                    else:
                        out.add(a.asname or a.name.split(".")[0])
            elif isinstance(child, (ast.Global, ast.Nonlocal)):
                out.update(child.names)
            elif isinstance(child, ast.NamedExpr):
                add_target(child.target)
            elif isinstance(child, (ast.comprehension,)):
                add_target(child.target)
            walk(child, top=False)

    walk(node, top=True)
    return out


def _params_of(fn: ast.AST) -> set[str]:
    a = fn.args
    names = {p.arg for p in (*a.posonlyargs, *a.args, *a.kwonlyargs)}
    if a.vararg:
        names.add(a.vararg.arg)
    if a.kwarg:
        names.add(a.kwarg.arg)
    return names


def _loaded_in(fn: ast.AST) -> list[ast.Name]:
    """Name reads in this function's own scope, excluding nested function bodies."""
    out: list[ast.Name] = []

    def walk(n: ast.AST) -> None:
        for child in ast.iter_child_nodes(n):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                out.append(child)
            walk(child)

    for stmt in fn.body:
        walk(ast.Module(body=[stmt], type_ignores=[]))
    return out


def undefined_names(source: str) -> list[tuple[str, int, str]]:
    """[(function, lineno, name)] for every name read but never bound."""
    tree = ast.parse(source)
    module_scope = _bound_by(tree) | _BUILTINS
    findings: list[tuple[str, int, str]] = []

    def visit(node: ast.AST, enclosing: set[str], qual: str) -> None:
        for child in ast.walk(node):
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if child not in set(ast.iter_child_nodes(node)):
                continue
            name = f"{qual}.{child.name}" if qual else child.name
            scope = enclosing | _params_of(child) | _bound_by(child)
            if "*" not in scope:
                for ref in _loaded_in(child):
                    if ref.id not in scope:
                        findings.append((name, ref.lineno, ref.id))
            visit(child, scope, name)

    visit(tree, module_scope, "")
    return findings


# ── the checker has to work before it can be trusted ────────────────────────

class TestTheCheckerItself:
    def test_it_catches_the_actual_weights_bug_verbatim(self):
        """The real defect, reduced. `actual_weights` is the callee's PARAMETER
        name; the local is `live_weights`. Gated on a config flag, so it ran
        green everywhere until the flag went on in production."""
        src = (
            "def delta(cfg):\n"
            "    live_weights = {}\n"
            "    if cfg.enabled and actual_weights:\n"
            "        return sum(actual_weights.values())\n"
            "    return 0\n"
        )
        assert {n for _f, _l, n in undefined_names(src)} == {"actual_weights"}

    def test_it_catches_a_name_defined_in_a_DIFFERENT_function(self):
        """The `book_size` shape: defined over there, used over here."""
        src = (
            "def a():\n"
            "    book_size = 10\n"
            "    return book_size\n"
            "def b():\n"
            "    return book_size * 2\n"
        )
        assert [n for _f, _l, n in undefined_names(src)] == ["book_size"]

    @pytest.mark.parametrize("src", [
        "def f(x):\n    return x\n",                                  # parameter
        "y = 1\ndef f():\n    return y\n",                            # module global
        "def f():\n    z = 1\n    return z\n",                        # local
        "def f():\n    return len([1])\n",                            # builtin
        "def f():\n    for i in range(3):\n        pass\n    return i\n",
        "def f(p):\n    with open(p) as fh:\n        return fh\n",
        "def f():\n    try:\n        pass\n    except ValueError as e:\n        return e\n",
        "def f():\n    return [q for q in range(3)]\n",                # comprehension
        "def f():\n    import os\n    return os\n",                   # local import
        "def f():\n    return [w := 2, w]\n",                         # walrus
        "g = 0\ndef f():\n    global g\n    g = 1\n    return g\n",
        "def outer():\n    v = 1\n    def inner():\n        return v\n    return inner\n",
        "def f():\n    class C:\n        pass\n    return C\n",
        "def f(a):\n    return a.b.c\n",                              # attribute chain
        "def f(*args, **kw):\n    return args, kw\n",
        "def f():\n    return lambda t: t + 1\n",                     # lambda params
    ])
    def test_it_does_not_false_positive_on_ordinary_python(self, src):
        """A false positive costs trust in the suite, and a test nobody trusts
        gets deleted. Every one of these must come back clean."""
        assert undefined_names(src) == []

    def test_a_star_import_disables_the_scope_rather_than_guessing(self):
        src = "from os.path import *\ndef f():\n    return join('a', 'b')\n"
        assert undefined_names(src) == []


# ── the actual contract ─────────────────────────────────────────────────────

@pytest.mark.parametrize("rel", _TARGETS)
def test_service_module_has_no_undefined_names(rel):
    """THE test. A NameError in a flag-gated branch is invisible to unit tests
    and to every chain run until the flag is switched on — at which point it
    stops the live book."""
    path = os.path.join(_ROOT, rel)
    if not os.path.exists(path):
        pytest.skip(f"{rel} not present")
    findings = undefined_names(open(path).read())
    assert not findings, "\n".join(
        f"{rel}:{line}  {fn}() reads undefined name {name!r}"
        for fn, line, name in findings)

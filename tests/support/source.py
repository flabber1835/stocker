"""Read a function's CODE, not its prose.

Several guards in this suite assert that a particular construct is absent —
`fetchall()` in the streaming loader, `utcnow()` in a check that must reason in
exchange time. The obvious implementation greps `inspect.getsource`, and it goes
red on the docstring EXPLAINING why the construct was removed.

That is worse than a flaky test. The cheapest way to make such a guard green is
to stop writing the explanation, so the check actively punishes the comment that
tells the next reader why the rule exists. Both of this batch's source guards hit
it within minutes of being written.

`ast.unparse` discards comments outright; the docstring is a real node and has to
be excised deliberately.
"""
from __future__ import annotations

import ast
import inspect
import textwrap


def code_of(fn) -> str:
    """`fn`'s source with its docstring and every comment removed.

    `textwrap.dedent`, not `inspect.cleandoc`: cleandoc strips the common indent
    from every line AFTER the first, which on a method leaves the `def` at
    column 0 and its body at column 0 too — an IndentationError rather than a
    parse.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    node = tree.body[0]
    body = getattr(node, "body", None)
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        node.body = body[1:]
    return ast.unparse(node)

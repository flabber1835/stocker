"""The original source-fingerprint bytes remain fresh and independently exact."""
from __future__ import annotations

import ast
from functools import lru_cache
import hashlib
import inspect
from pathlib import Path
import textwrap
from types import SimpleNamespace

import pytest

from sentinel import identity


def original_source_hash(root):
    """Independent retained four-update algorithm, without optimized helpers."""
    if root is None or not root.exists():
        return {"root": None if root is None else root.name,
                "path": None if root is None else str(root), "files": 0, "hash": None}
    files = sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)
    result = hashlib.sha256()
    for path in files:
        result.update(path.relative_to(root).as_posix().encode())
        result.update(b"\0")
        result.update(hashlib.sha256(path.read_bytes()).hexdigest().encode())
        result.update(b"\n")
    return {"root": root.name, "path": str(root), "files": len(files), "hash": result.hexdigest()}


def source_tree(tmp_path):
    root = tmp_path / "package"
    for name, raw in (
        ("z.py", b"z = 3\n"), ("a.py", b"a = 1\n"),
        ("nested/empty.py", b""), ("nested/space name.py", b"b = 2\r\n"),
        ("nested/\u03a9\u96ea.py", "value = '\u00e9'\n".encode()),
        ("__pycache__/hidden.py", b"not source\n"),
        ("nested/__pycache__/also-hidden.py", b"not source either\n"),
        ("__pycache__extra/visible.py", b"visible = True\n"),
        ("notes.txt", b"ignored"),
    ):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    return root


def test_original_four_update_oracle_includes_unicode_empty_files_and_exact_exclusions(tmp_path):
    root = source_tree(tmp_path)
    expected = original_source_hash(root)
    assert expected["files"] == 6
    assert identity.source_hash(root) == expected
    assert identity.source_hash(root) == expected


@pytest.mark.parametrize("kind", ["none", "missing", "empty", "file"])
def test_original_absent_and_non_directory_root_results(tmp_path, kind):
    root = {"none": None, "missing": tmp_path / "missing",
            "empty": tmp_path / "empty", "file": tmp_path / "one.py"}[kind]
    if kind == "empty":
        root.mkdir()
    elif kind == "file":
        root.write_bytes(b"not recursively enumerated\n")
    assert identity.source_hash(root) == original_source_hash(root)


def test_relative_root_and_dot_root_preserve_original_names(tmp_path, monkeypatch):
    source_tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert identity.source_hash(Path("package")) == original_source_hash(Path("package"))
    monkeypatch.chdir(tmp_path / "package")
    assert identity.source_hash(Path(".")) == original_source_hash(Path("."))


def test_fresh_enumeration_and_every_file_read_are_retained(tmp_path, monkeypatch):
    root = source_tree(tmp_path)
    expected = original_source_hash(root)
    concrete = type(root)
    rglob, read_bytes = concrete.rglob, concrete.read_bytes
    scans, reads = [], []

    def scanned(path, pattern, *args, **kwargs):
        scans.append((path, pattern))
        return rglob(path, pattern, *args, **kwargs)

    def read(path):
        reads.append(path)
        return read_bytes(path)

    monkeypatch.setattr(concrete, "rglob", scanned)
    monkeypatch.setattr(concrete, "read_bytes", read)
    assert identity.source_hash(root) == expected
    assert identity.source_hash(root) == expected
    ordered = sorted(path for path in rglob(root, "*.py") if "__pycache__" not in path.parts)
    assert scans == [(root, "*.py"), (root, "*.py")]
    assert reads == ordered + ordered


@pytest.mark.parametrize("change", ["content", "add", "delete", "rename"])
def test_changed_source_is_observed_on_the_next_call(tmp_path, change):
    root = source_tree(tmp_path)
    before = identity.source_hash(root)
    if change == "content":
        # Same-length content still changes the fingerprint; no stat-based reuse.
        (root / "a.py").write_bytes(b"a = 9\n")
    elif change == "add":
        (root / "new.py").write_bytes(b"new = True\n")
    elif change == "delete":
        (root / "a.py").unlink()
    else:
        (root / "a.py").rename(root / "renamed.py")
    after = identity.source_hash(root)
    assert after == original_source_hash(root)
    assert after["hash"] != before["hash"]


def test_non_source_mutation_does_not_change_the_original_commitment(tmp_path):
    root = source_tree(tmp_path)
    before = identity.source_hash(root)
    (root / "notes.txt").write_bytes(b"new ignored text")
    (root / "__pycache__/hidden.py").write_bytes(b"new excluded bytes")
    assert identity.source_hash(root) == before == original_source_hash(root)


def test_cross_call_source_cache_is_falsified_by_a_fresh_content_mutation(tmp_path, monkeypatch):
    monkeypatch.setattr(identity, "source_hash", lru_cache(maxsize=1)(identity.source_hash))
    with pytest.raises(AssertionError):
        test_changed_source_is_observed_on_the_next_call(tmp_path, "content")


def test_ordinary_children_avoid_relative_to_but_keep_its_original_bytes(tmp_path, monkeypatch):
    root = source_tree(tmp_path)
    expected = original_source_hash(root)
    concrete = type(root)

    def unnecessary(*args, **kwargs):
        pytest.fail("ordinary child called relative_to")

    with monkeypatch.context() as patch:
        patch.setattr(concrete, "relative_to", unnecessary)
        actual = identity.source_hash(root)
    assert actual == expected


def test_four_update_framing_is_combined_without_changing_a_byte(tmp_path, monkeypatch):
    root = source_tree(tmp_path)
    expected = original_source_hash(root)
    frames = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" not in path.parts:
            frames.append(path.relative_to(root).as_posix().encode() + b"\0"
                          + hashlib.sha256(path.read_bytes()).hexdigest().encode() + b"\n")
    main_updates = []

    class ObservedHash:
        def __init__(self, *args):
            self.main = not args
            self.value = hashlib.sha256(*args)

        def update(self, raw):
            if self.main:
                main_updates.append(raw)
            self.value.update(raw)

        def hexdigest(self):
            return self.value.hexdigest()

    monkeypatch.setattr(identity, "hashlib", SimpleNamespace(sha256=ObservedHash))
    assert identity.source_hash(root) == expected
    assert main_updates == frames


def test_subclass_root_keeps_original_relative_to_dispatch(tmp_path):
    root = source_tree(tmp_path)
    concrete = type(root)
    calls = []

    class SpecialPath(concrete):
        def relative_to(self, *args, **kwargs):
            calls.append((str(self), args))
            return super().relative_to(*args, **kwargs)

    special = SpecialPath(root)
    expected = original_source_hash(special)
    calls.clear()
    assert identity.source_hash(special) == expected
    assert len(calls) == expected["files"]


def test_subclass_child_keeps_original_relative_to_dispatch(tmp_path, monkeypatch):
    root = source_tree(tmp_path)
    concrete = type(root)
    original = concrete.rglob
    calls = []

    class SpecialPath(concrete):
        def relative_to(self, *args, **kwargs):
            calls.append((str(self), args))
            return super().relative_to(*args, **kwargs)

    def children(path, pattern, *args, **kwargs):
        return (SpecialPath(item) for item in original(path, pattern, *args, **kwargs))

    monkeypatch.setattr(concrete, "rglob", children)
    expected = original_source_hash(root)
    calls.clear()
    assert identity.source_hash(root) == expected
    assert len(calls) == expected["files"]


def test_unusual_child_keeps_single_parts_access_and_original_read_order(tmp_path, monkeypatch):
    root = source_tree(tmp_path)
    events = []

    class SpecialPath(type(root)):
        @property
        def parts(self):
            events.append("parts")
            if events.count("parts") > 1:
                raise RuntimeError("unusual child parts accessed a second time")
            return super().parts

        def relative_to(self, *args, **kwargs):
            events.append("relative_to")
            return Path("declared-relative.py")

        def read_bytes(self):
            events.append("read_bytes")
            return b"custom bytes\n"

    child = SpecialPath(root / "virtual.py")
    monkeypatch.setattr(type(root), "rglob", lambda *_args, **_kwargs: iter([child]))
    events.clear()
    expected = original_source_hash(root)
    assert events == ["parts", "relative_to", "read_bytes"]
    events.clear()
    assert identity.source_hash(root) == expected
    assert events == ["parts", "relative_to", "read_bytes"]


def test_standard_foreign_child_keeps_relative_to_refusal(tmp_path, monkeypatch):
    root = source_tree(tmp_path)
    foreign = tmp_path / "elsewhere/inside/foreign.py"
    foreign.parent.mkdir(parents=True)
    foreign.write_bytes(b"foreign = True\n")
    monkeypatch.setattr(type(root), "rglob", lambda *_args, **_kwargs: iter([foreign]))
    with pytest.raises(ValueError) as expected:
        original_source_hash(root)
    with pytest.raises(ValueError) as actual:
        identity.source_hash(root)
    assert actual.value.args == expected.value.args


def test_child_equal_to_root_keeps_original_dot_name(tmp_path, monkeypatch):
    root = tmp_path / "root.py"
    root.write_bytes(b"same = True\n")
    monkeypatch.setattr(type(root), "rglob", lambda *_args, **_kwargs: iter([root]))
    assert identity.source_hash(root) == original_source_hash(root)


@pytest.mark.parametrize("error", [PermissionError("denied"), FileNotFoundError("removed")])
def test_file_read_failures_keep_original_exception(tmp_path, monkeypatch, error):
    root = source_tree(tmp_path)
    concrete = type(root)
    read_bytes = concrete.read_bytes

    def read(path):
        if path.name == "a.py":
            raise error
        return read_bytes(path)

    monkeypatch.setattr(concrete, "read_bytes", read)
    with pytest.raises(type(error)) as expected:
        original_source_hash(root)
    with pytest.raises(type(error)) as actual:
        identity.source_hash(root)
    assert actual.value is expected.value is error


def test_enumeration_failure_keeps_original_exception(tmp_path, monkeypatch):
    root = source_tree(tmp_path)
    error = OSError("enumeration failed")

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(type(root), "rglob", fail)
    with pytest.raises(OSError) as expected:
        original_source_hash(root)
    with pytest.raises(OSError) as actual:
        identity.source_hash(root)
    assert actual.value is expected.value is error


def mutated_hash(monkeypatch, *, transform):
    tree = ast.parse(textwrap.dedent(inspect.getsource(identity.source_hash)))
    transform(tree)
    ast.fix_missing_locations(tree)
    namespace = dict(identity.__dict__)
    exec(compile(tree, "source-hash-falsifier", "exec"), namespace)
    monkeypatch.setattr(identity, "source_hash", namespace["source_hash"])


@pytest.mark.parametrize("defect", ["framing", "ordering", "exclusions", "prefix", "ordinary", "unusual_parts"])
def test_original_oracle_and_path_guards_falsify_broken_bookkeeping(tmp_path, monkeypatch, defect):
    def mutate(tree):
        for node in ast.walk(tree):
            if defect == "framing" and isinstance(node, ast.Constant) and node.value == b"\0":
                node.value = b"/"
            elif defect == "ordering" and isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "sorted":
                node.func.id = "list"
            elif defect == "exclusions" and isinstance(node, ast.comprehension):
                node.ifs = []
            elif defect == "prefix" and isinstance(node, ast.Compare) and isinstance(node.left, ast.Subscript):
                node.left = ast.Constant(value=True)
                node.ops = [ast.Eq()]
                node.comparators = [ast.Constant(value=True)]
            elif defect == "ordinary" and isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == "ordinary_root" for target in node.targets):
                node.value = ast.Constant(value=True)
            elif defect == "unusual_parts" and isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == "parts" for target in node.targets):
                node.value = ast.Attribute(value=ast.Name(id="p", ctx=ast.Load()), attr="parts", ctx=ast.Load())
    mutated_hash(monkeypatch, transform=mutate)
    if defect == "prefix":
        with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
            test_standard_foreign_child_keeps_relative_to_refusal(tmp_path, monkeypatch)
    elif defect == "ordinary":
        with pytest.raises(AssertionError):
            test_subclass_root_keeps_original_relative_to_dispatch(tmp_path)
    elif defect == "unusual_parts":
        with pytest.raises(RuntimeError, match="parts accessed a second time"):
            test_unusual_child_keeps_single_parts_access_and_original_read_order(tmp_path, monkeypatch)
    else:
        if defect == "ordering":
            # Make arrival order independent of filesystem ordering.
            concrete = type(tmp_path)
            original = concrete.rglob
            monkeypatch.setattr(concrete, "rglob", lambda *args, **kwargs: reversed(sorted(original(*args, **kwargs))))
        with pytest.raises(AssertionError):
            test_original_four_update_oracle_includes_unicode_empty_files_and_exact_exclusions(tmp_path)

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from tools.merge_junit import merge


def _write(path: Path, *cases: tuple[str, str]) -> None:
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite", name=path.stem)
    for classname, name in cases:
        ET.SubElement(suite, "testcase", classname=classname, name=name)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def test_merge_preserves_disjoint_testcase_evidence(tmp_path):
    first = tmp_path / "first.xml"
    second = tmp_path / "second.xml"
    output = tmp_path / "merged.xml"
    _write(first, ("tests.a", "test_one"))
    _write(second, ("tests.b", "test_two"), ("tests.b", "test_three"))

    assert merge([first, second], output) == 3
    cases = list(ET.parse(output).getroot().iter("testcase"))
    assert [(case.get("classname"), case.get("name")) for case in cases] == [
        ("tests.a", "test_one"),
        ("tests.b", "test_two"),
        ("tests.b", "test_three"),
    ]


def test_merge_refuses_duplicate_semantic_execution_evidence(tmp_path):
    first = tmp_path / "first.xml"
    second = tmp_path / "second.xml"
    _write(first, ("tests.same", "test_once"))
    _write(second, ("tests.same", "test_once"))

    with pytest.raises(ValueError, match="duplicate JUnit testcase evidence"):
        merge([first, second], tmp_path / "merged.xml")


def test_merge_refuses_empty_or_missing_inputs(tmp_path):
    empty = tmp_path / "empty.xml"
    _write(empty)
    with pytest.raises(ValueError, match="no testcases"):
        merge([empty, empty], tmp_path / "merged.xml")
    with pytest.raises(FileNotFoundError):
        merge([tmp_path / "missing.xml", empty], tmp_path / "merged.xml")

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

import CVisionProcessor as processor


def test_validate_filename_revs_raises_for_missing_suffix():
    with pytest.raises(ValueError, match="Invalid file\\(s\\): NoDocRevSuffix.dxf"):
        processor.validate_filename_revs([Path("NoDocRevSuffix.dxf")])


def test_extract_filename_rev_reads_suffix():
    assert processor.extract_filename_rev("GoodFile_B.dxf") == "B"
    assert processor.extract_filename_rev("GoodFile_AA.dxf") == "AA"


def test_extract_filename_rev_returns_none_without_suffix():
    assert processor.extract_filename_rev("NoDocRevSuffix.dxf") is None


def test_process_dxf_errors_when_no_manufacturing_rev_found(monkeypatch, tmp_path):
    file_path = tmp_path / "NoRevLetter_B.dxf"
    file_path.write_text("stub", encoding="utf-8")

    monkeypatch.setattr(processor, "find_acad_application", lambda: object())
    monkeypatch.setattr(processor, "check_dxf", lambda _path: (False, True))
    monkeypatch.setattr(processor, "read_env_file", lambda: {"USER_INITIALS": "JT"})

    with pytest.raises(RuntimeError, match="No manufacturing rev text"):
        processor.process_dxf(str(file_path), "B")


def test_process_dxf_errors_when_no_table_found(monkeypatch, tmp_path):
    file_path = tmp_path / "NoTable_A.dxf"
    file_path.write_text("stub", encoding="utf-8")

    monkeypatch.setattr(processor, "find_acad_application", lambda: object())
    monkeypatch.setattr(processor, "check_dxf", lambda _path: (True, False))
    monkeypatch.setattr(processor, "read_env_file", lambda: {"USER_INITIALS": "JT"})

    with pytest.raises(RuntimeError, match="No REV table was found"):
        processor.process_dxf(str(file_path), "B")


def test_add_rev_table_entry_sets_requested_cell_alignments():
    table = Mock()
    table.Rows = 1
    table.Columns = 4
    table.GetCellValue.side_effect = lambda row, col: "REV" if (row, col) == (0, 0) else ""

    row = processor.add_rev_table_entry(table, "A", "B", initials="JT")

    assert row == 1
    assert table.SetCellAlignment.call_args_list == [
        call(1, 0, processor.AC_CELL_ALIGNMENT_TOP_CENTER),
        call(1, 1, processor.AC_CELL_ALIGNMENT_MIDDLE_LEFT),
        call(1, 2, processor.AC_CELL_ALIGNMENT_TOP_CENTER),
        call(1, 3, processor.AC_CELL_ALIGNMENT_TOP_CENTER),
    ]


def test_process_dxf_success_path(monkeypatch, tmp_path):
    file_path = tmp_path / "GoodFile_B.dxf"
    file_path.write_text("stub", encoding="utf-8")

    doc = SimpleNamespace(Close=Mock())
    documents = SimpleNamespace(Open=Mock(return_value=doc))
    acad = SimpleNamespace(Documents=documents)
    table = object()

    monkeypatch.setattr(processor, "find_acad_application", lambda: acad)
    monkeypatch.setattr(processor, "check_dxf", lambda _path: (True, True))
    monkeypatch.setattr(processor, "archive_dxf", lambda path: path)
    monkeypatch.setattr(processor, "update_rev_texts", lambda _doc, _rev: [("REV B", "REV C")])
    monkeypatch.setattr(processor, "find_rev_table", lambda _doc: table)
    monkeypatch.setattr(processor, "get_max_table_rev_letter", lambda _table: "A")
    monkeypatch.setattr(processor, "add_rev_table_entry", lambda *_args, **_kwargs: 2)
    monkeypatch.setattr(processor, "save_document", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(processor, "read_env_file", lambda: {"USER_INITIALS": "JT"})

    result = processor.process_dxf(str(file_path), "C")

    assert result["manufacturing_rev"] == "C"
    assert result["document_rev"] == "B"
    assert result["updated"] == [("REV B", "REV C")]

from pathlib import Path

from PyQt6.QtCore import Qt

import CVisionUpRevifier as ui


def test_refresh_file_table_lists_only_dxf(qtbot, monkeypatch, tmp_path):
    (tmp_path / "a.dxf").write_text("x", encoding="utf-8")
    (tmp_path / "b.DXF").write_text("x", encoding="utf-8")
    (tmp_path / "skip.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(ui, "read_env_file", lambda: {"DEFAULT_PATH": str(tmp_path), "USER_INITIALS": "JT"})

    window = ui.CVisionProcessorWindow()
    qtbot.addWidget(window)

    assert window.file_table.rowCount() == 2


def test_execute_selected_files_requires_rev(qtbot, monkeypatch, tmp_path):
    (tmp_path / "GoodFile_B.dxf").write_text("x", encoding="utf-8")
    monkeypatch.setattr(ui, "read_env_file", lambda: {"DEFAULT_PATH": str(tmp_path), "USER_INITIALS": "JT"})
    messages = []
    monkeypatch.setattr(ui, "show_message_box", lambda t, m, l="info": messages.append((t, m, l)))

    window = ui.CVisionProcessorWindow()
    qtbot.addWidget(window)
    window.rev_edit.setText("")
    qtbot.mouseClick(window.execute_button, Qt.MouseButton.LeftButton)

    assert messages
    assert messages[-1][0] == "Rev Required"


def test_execute_selected_files_success_calls_processor(qtbot, monkeypatch, tmp_path):
    (tmp_path / "GoodFile_B.dxf").write_text("x", encoding="utf-8")
    monkeypatch.setattr(ui, "read_env_file", lambda: {"DEFAULT_PATH": str(tmp_path), "USER_INITIALS": "JT"})
    monkeypatch.setattr(ui, "validate_filename_revs", lambda paths: None)
    calls = []
    monkeypatch.setattr(ui, "process_dxf", lambda path, rev, initials: calls.append((Path(path).name, rev, initials)))
    messages = []
    monkeypatch.setattr(ui, "show_message_box", lambda t, m, l="info": messages.append((t, m, l)))
    monkeypatch.setattr(ui, "write_env_value", lambda *_args, **_kwargs: None)

    window = ui.CVisionProcessorWindow()
    qtbot.addWidget(window)
    window.rev_edit.setText("C")
    window.initials_edit.setText("JT")
    qtbot.mouseClick(window.execute_button, Qt.MouseButton.LeftButton)

    assert calls == [("GoodFile_B.dxf", "C", "JT")]
    assert messages[-1][0] == "Processing Complete"


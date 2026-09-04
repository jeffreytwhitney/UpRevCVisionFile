import shutil
from pathlib import Path

import pytest

import CVisionProcessor as processor


@pytest.fixture()
def copied_input_files(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    input_dir = repo_root / "test" / "files" / "input"
    for source in input_dir.glob("*.dxf"):
        shutil.copy2(source, tmp_path / source.name)
    return tmp_path


@pytest.fixture()
def real_processing_env(monkeypatch, copied_input_files):
    archive_dir = copied_input_files / "archive"
    archive_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(
        processor,
        "read_env_file",
        lambda: {
            "USER_INITIALS": "JT",
            "ARCHIVE_ROOT_PATH": str(archive_dir),
        },
    )
    return copied_input_files


def _require_autocad():
    try:
        processor.find_acad_application()
    except Exception as exc:
        pytest.skip(f"AutoCAD COM unavailable for integration test: {exc}")


@pytest.mark.integration
def test_integration_nodocrevsuffix_errors(real_processing_env):
    _require_autocad()
    target = real_processing_env / "NoDocRevSuffix.dxf"
    with pytest.raises(ValueError):
        processor.validate_filename_revs([target])


@pytest.mark.integration
def test_integration_norevletter_errors(real_processing_env):
    _require_autocad()
    target = real_processing_env / "NoRevLetter_B.dxf"

    with pytest.raises(RuntimeError, match="No manufacturing rev text"):
        processor.process_dxf(str(target), "C")


@pytest.mark.integration
def test_integration_notable_errors(real_processing_env):
    _require_autocad()
    target = real_processing_env / "NoTable_A.dxf"

    with pytest.raises(RuntimeError, match="No REV table was found"):
        processor.process_dxf(str(target), "B")


@pytest.mark.integration
def test_integration_goodfile_processes(real_processing_env):
    _require_autocad()
    target = real_processing_env / "GoodFile_B.dxf"
    result = processor.process_dxf(str(target), "C")
    assert result["manufacturing_rev"] == "C"

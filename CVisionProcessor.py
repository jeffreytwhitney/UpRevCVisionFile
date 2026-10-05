import os
import pathlib
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path, WindowsPath

from dotenv import load_dotenv

from app_logging import get_app_dir, get_logger

logger = get_logger("processor")

load_dotenv(get_app_dir() / ".env")

try:
    import win32com.client
except ImportError:  # pragma: no cover - only needed when AutoCAD COM is unavailable.
    win32com = None


def get_env_path():
    return get_app_dir() / ".env"


def read_env_file():
    env_path = get_env_path()
    values = {}
    logger.debug("Reading env file %s", env_path)
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if not line or line.strip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            values[key.strip()] = value
    return values


def write_env_value(key, value):
    env_path = get_env_path()
    values = read_env_file()
    values[key] = str(value)
    lines = [f"{key}={values[key]}" for key in sorted(values)]
    try:
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        logger.exception("Unable to write %s to %s", key, env_path)
        raise
    logger.info("Saved setting %s", key)


def show_message_box(title, message, level="info"):
    logger.info("Message [%s] %s: %s", level, title, message)
    print(f"{title}: {message}")


def confirm_message_box(title, message):
    print(f"{title}: {message}")
    return True


REV_TEXT_PATTERN = re.compile(r"(?i)(?:^|[^A-Z])REV(?:[\s_-])?([A-Z]{1,2})\s*$")
FILENAME_REV_SUFFIX_PATTERN = re.compile(r"_(?P<rev>[A-Z]{1,2})$")
_ACAD_LOCAL = threading.local()  # COM objects cannot cross threads; cache per thread
AC_CELL_ALIGNMENT_TOP_CENTER = 2
AC_CELL_ALIGNMENT_MIDDLE_LEFT = 4


def add_rev_table_entry(table, doc_rev_letter, manufacturing_rev_letter, initials=None):
    initials = (initials or read_env_file().get("USER_INITIALS", "").strip() or "").strip()
    if not initials:
        raise ValueError("USER_INITIALS is required before adding the REV table entry.")

    row_count = int(getattr(table, "Rows", 0))
    last_data_row = find_last_data_row(table)

    if last_data_row < 0:
        insert_row_index = 0
    else:
        insert_row_index = last_data_row + 1

    if insert_row_index >= row_count:
        if hasattr(table, "InsertRows"):
            table.InsertRows(row_count, 1)
            insert_row_index = row_count
        else:
            raise AttributeError(f"Table object {type(table).__name__} does not support InsertRows.")

    reference_height = None
    reference_style = None
    for row_index in range(0, max(1, insert_row_index + 1)):
        for col_index in range(0, 4):
            try:
                height = get_table_cell_text_height(table, row_index, col_index)
                if height is not None:
                    reference_height = height
                    reference_style = get_table_cell_style(table, row_index, col_index)
                    break
            except Exception:
                pass
        if reference_height is not None:
            break

    for col_index in range(0, 4):
        value = ""
        if col_index == 0:
            value = doc_rev_letter
        elif col_index == 1:
            value = f"Up Rev to {manufacturing_rev_letter}. No chg."
        elif col_index == 2:
            value = initials
        elif col_index == 3:
            value = datetime.now().strftime("%m/%d/%Y")
        set_table_cell_text(table, insert_row_index, col_index, value)
        if reference_style is not None:
            set_table_cell_style(table, insert_row_index, col_index, reference_style)
        elif reference_height is not None:
            set_table_cell_text_height(table, insert_row_index, col_index, reference_height)
        alignment = (
            AC_CELL_ALIGNMENT_MIDDLE_LEFT if col_index == 1 else AC_CELL_ALIGNMENT_TOP_CENTER
        )
        table.SetCellAlignment(insert_row_index, col_index, alignment)

    return insert_row_index


def archive_dxf(filepath):
    archive_filepath = get_file_archive_path(filepath)
    incremented_filepath = get_incremented_file_path(filepath)

    logger.info("Archiving %s -> %s, renaming to %s", filepath, archive_filepath, incremented_filepath)
    if os.path.exists(incremented_filepath):
        show_message_box("Error", f"File '{incremented_filepath}' already exists.", "error")
        return ""

    if os.path.exists(archive_filepath):
        user_response = confirm_message_box("Are You Sure?", f"Directory '{archive_filepath}' already exists. Overwrite?")
        if not user_response:
            return ""
    os.makedirs(os.path.dirname(archive_filepath), exist_ok=True)
    shutil.copy(filepath, archive_filepath)
    os.rename(filepath, incremented_filepath)

    return incremented_filepath


def bump_rev_letter(letter):
    normalized = normalize_rev_name(letter)
    value = 0
    for character in normalized:
        value = (value * 26) + (ord(character) - ord("A") + 1)

    value += 1
    result = ""
    while value > 0:
        value, remainder = divmod(value - 1, 26)
        result = chr(ord("A") + remainder) + result

    if len(result) > 2:
        raise ValueError(f"Rev increment exceeds supported range for {letter!r}.")
    return result


def check_dxf(filepath):
    has_rev_text = False
    has_rev_table = False

    logger.info("Checking %s", filepath)
    acad = find_acad_application()
    doc = acad.Documents.Open(filepath)
    try:
        for obj in iter_document_objects(doc):
            try:
                object_name = getattr(obj, "ObjectName", "")
                if object_name.startswith("AcDbText") or object_name.startswith("AcDbMText"):
                    text = get_object_text(obj)
                    if extract_rev_suffix(text) is not None:
                        has_rev_text = True
                elif "Table" in object_name or hasattr(obj, "GetCell") or hasattr(obj, "Cells"):
                    cell_text = get_table_cell_text(obj, 0, 0)
                    if cell_text.upper() == "REV":
                        has_rev_table = True
            except Exception:
                logger.debug("Skipping unreadable object during check", exc_info=True)
                continue
    finally:
        try:
            if doc is not None:
                doc.Close(False)
        except Exception:
            logger.warning("Failed closing %s after check", filepath, exc_info=True)

    logger.info("Check result for %s: rev_text=%s rev_table=%s", filepath, has_rev_text, has_rev_table)
    return has_rev_text, has_rev_table


def extract_rev_suffix(text):
    match = REV_TEXT_PATTERN.search(text.strip())
    if not match:
        return None
    return match.group(1).upper()


def extract_filename_rev(filepath):
    stem = Path(filepath).stem
    match = FILENAME_REV_SUFFIX_PATTERN.search(stem.upper())
    if not match:
        return None
    return match.group("rev")


def validate_filename_revs(filepaths):
    invalid_files = [Path(filepath).name for filepath in filepaths if extract_filename_rev(filepath) is None]
    if invalid_files:
        joined = ", ".join(sorted(invalid_files))
        raise ValueError(
            "Each file name must end with an underscore followed by one or two rev characters before the .dxf extension. "
            f"Invalid file(s): {joined}"
        )


def find_acad_application():
    if win32com is None:
        raise RuntimeError("pywin32 is required to communicate with AutoCAD.")

    cached = getattr(_ACAD_LOCAL, "app", None)
    if cached is not None:
        try:
            if hasattr(cached, "Documents"):
                return cached
        except Exception:
            logger.warning("Cached AutoCAD connection is stale", exc_info=True)
            _ACAD_LOCAL.app = None

    for app_name in ("AutoCAD.Application", "AutoCAD.Application.25.1"):
        try:
            app = win32com.client.GetActiveObject(app_name)
            if hasattr(app, "Documents"):
                _ACAD_LOCAL.app = app
                logger.info("Attached to running %s", app_name)
                return app
        except Exception:
            logger.debug("%s is not a running/registered AutoCAD ProgID", app_name)

    for app_name in ("AutoCAD.Application", "AutoCAD.Application.25.1"):
        try:
            app = win32com.client.Dispatch(app_name)
            if hasattr(app, "Documents"):
                _ACAD_LOCAL.app = app
                logger.info("Started new %s", app_name)
                return app
        except Exception:
            logger.warning("Dispatch failed for %s", app_name, exc_info=True)

    logger.error("AutoCAD unavailable")
    raise RuntimeError("AutoCAD is not running, and a new instance could not be started.")


def find_last_data_row(table):
    if not hasattr(table, "Rows") or not hasattr(table, "Columns"):
        return -1

    row_count = int(getattr(table, "Rows", 0))
    column_count = int(getattr(table, "Columns", 0))

    for row_index in range(row_count - 1, -1, -1):
        for col_index in range(column_count):
            try:
                cell_text = get_table_cell_text(table, row_index, col_index)
            except Exception:
                continue
            if cell_text:
                return row_index
    return -1


def find_rev_table(doc):
    candidates = []
    for obj in iter_document_objects(doc):
        try:
            object_name = str(getattr(obj, "ObjectName", ""))
            if "Table" in object_name or hasattr(obj, "GetCell") or hasattr(obj, "Cells"):
                candidates.append(object_name or type(obj).__name__)
                if "Table" not in object_name:
                    continue
                cell_text = get_table_cell_text(obj, 0, 0)
                if cell_text.upper() == "REV":
                    return obj
        except Exception:
            continue

    return None


def get_incremented_file_path(source_filepath):
    source_path = WindowsPath(source_filepath)
    match = FILENAME_REV_SUFFIX_PATTERN.search(source_path.stem.upper())
    if not match:
        raise ValueError(
            f"File '{source_path.name}' must end with an underscore followed by one or two rev characters."
        )
    current_file_suffix = match.group("rev")
    root_filename = source_path.stem[:-len(current_file_suffix)]
    file_extension = source_path.suffix
    while True:
        incremented_file_suffix = get_incremented_file_suffix(current_file_suffix)
        incremented_filename = root_filename + incremented_file_suffix + file_extension
        incremented_filepath = source_path.with_name(incremented_filename)
        if not os.path.exists(incremented_filepath):
            return_path = incremented_filepath
            break
        else:
            current_file_suffix = incremented_file_suffix
    return return_path


def get_file_archive_path(source_filepath):
    output_path_root = read_env_file().get("ARCHIVE_ROOT_PATH", "").strip()
    return pathlib.Path.joinpath(pathlib.WindowsPath(output_path_root), pathlib.WindowsPath(source_filepath).name)


def get_incremented_file_suffix(file_suffix):
    return bump_rev_letter(file_suffix)


def get_max_table_rev_letter(table):
    row_count = int(getattr(table, "Rows", 0))
    max_letter = None

    for row_index in range(0, row_count):
        value = get_table_cell_text(table, row_index, 0)
        if not value:
            continue
        if value.strip().upper() == "REV":
            continue
        match = re.search(r"(?i)(?:^|[\s_])?([A-Z]{1,2})$", value.strip())
        if not match:
            continue
        letter = match.group(1).upper()
        if max_letter is None or letter > max_letter:
            max_letter = letter

    return max_letter


def get_object_text(obj):
    for attribute in ("TextString", "Text", "Contents"):
        value = getattr(obj, attribute, None)
        if value is not None:
            return str(value)
    return ""


def get_table_cell_style(table, row, col):
    method = getattr(table, "GetCellStyle", None)
    if method is None:
        return None
    try:
        return method(row, col)
    except Exception:
        return None


def get_table_cell_text(table, row, col):
    for method_name in ("GetCellValue", "GetCellText", "GetCell", "Cell"):
        method = getattr(table, method_name, None)
        if method is None:
            continue
        try:
            value = method(row, col)
            if value is None:
                continue
            return str(value).strip()
        except TypeError:
            continue
        except Exception:
            continue

    return ""


def get_table_cell_text_height(table, row, col):
    method = getattr(table, "GetCellTextHeight", None)
    if method is None:
        return None
    try:
        return float(method(row, col))
    except Exception:
        return None


def iter_document_objects(doc):
    for container_name in ("ModelSpace", "PaperSpace"):
        container = getattr(doc, container_name, None)
        if container is None:
            continue
        try:
            for obj in container:
                yield obj
        except Exception:
            pass

    blocks = getattr(doc, "Blocks", None)
    if blocks is None:
        return
    try:
        for block in blocks:
            try:
                entities = getattr(block, "Entities", None)
                if entities is None:
                    continue
                for obj in entities:
                    yield obj
            except Exception:
                continue
    except Exception:
        pass


def normalize_rev_name(rev_name):
    if rev_name is None:
        raise ValueError("A new rev name is required.")

    cleaned = str(rev_name).strip()
    if not cleaned:
        raise ValueError("A new rev name is required.")
    if not re.fullmatch(r"[A-Za-z]{1,2}", cleaned):
        raise ValueError("Rev values must be one or two letters.")

    return cleaned.upper()


def replace_rev_suffix(text, old_letter, new_letter):
    match = re.search(r"(?i)(REV)([\s_-]?)\s*([A-Z]{1,2})\s*$", text)
    if match is None:
        pattern = re.compile(rf"(?i)(REV)(?:[\s_-])?{re.escape(old_letter)}\s*$")
        return pattern.sub(lambda match: f"{match.group(1)} {new_letter}", text, count=1)

    separator = match.group(2) or " "
    return re.sub(r"(?i)(REV)([\s_-]?)\s*[A-Z]{1,2}\s*$", rf"\1{separator}{new_letter}", text, count=1)


def save_document(doc, filepath):
    file_path = Path(filepath)
    temp_dir = file_path.parent
    stem = file_path.stem.replace(" ", "_")
    temp_name = f"{stem}_uprev_{datetime.now().strftime('%Y%m%d%H%M%S')}{file_path.suffix}"
    temp_path = temp_dir / temp_name

    try:
        logger.info("Saving %s via %s", file_path, temp_path)
        doc.SaveAs(str(temp_path))
        try:
            doc.Close(False)
        except Exception:
            pass
        if temp_path.exists():
            os.replace(str(temp_path), str(file_path))
        return
    except Exception as exc:
        logger.exception("Save failed for %s", filepath)
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        raise RuntimeError(
            f"Unable to save the DXF file '{filepath}'. AutoCAD rejected the save. Original error: {exc}"
        ) from exc


def set_object_text(obj, new_text):
    for attribute in ("TextString", "Text", "Contents"):
        if hasattr(obj, attribute):
            setattr(obj, attribute, new_text)
            return
    raise AttributeError(f"Object type {getattr(obj, 'ObjectName', type(obj).__name__)} has no editable text property.")


def set_table_cell_style(table, row, col, style):
    method = getattr(table, "SetCellStyle", None)
    if method is None:
        return False
    try:
        method(row, col, style)
        return True
    except Exception:
        return False


def set_table_cell_text(table, row, col, value):
    value = str(value)

    for method_name in ("SetCellValueFromText", "SetCellValue", "SetText"):
        method = getattr(table, method_name, None)
        if method is None:
            continue
        try:
            method(row, col, value)
            return
        except TypeError:
            try:
                method(row, col, value, 0)
                return
            except Exception:
                pass
        except Exception:
            pass

    raise AttributeError(f"Table object {type(table).__name__} does not support setting cell values.")


def set_table_cell_text_height(table, row, col, height):
    method = getattr(table, "SetCellTextHeight", None)
    if method is None:
        return False
    try:
        method(row, col, float(height))
        return True
    except TypeError:
        try:
            method(row, col, float(height), 0)
            return True
        except Exception:
            return False
    except Exception:
        return False


def update_rev_texts(doc, manufacturing_rev_letter=None):
    updated = []
    for obj in iter_document_objects(doc):
        try:
            object_name = getattr(obj, "ObjectName", "")
            if object_name.startswith("AcDbText") or object_name.startswith("AcDbMText"):
                text = get_object_text(obj)
                if not text:
                    continue
                old_letter = extract_rev_suffix(text)
                if old_letter is None:
                    continue
                new_letter = (manufacturing_rev_letter if manufacturing_rev_letter is not None
                              else bump_rev_letter(old_letter))
                new_text = replace_rev_suffix(text, old_letter, new_letter)
                set_object_text(obj, new_text)
                logger.info("Rev text updated: %r -> %r", text, new_text)
                updated.append((text, new_text))
        except Exception:
            logger.warning("Failed updating a rev text object", exc_info=True)
            continue
    return updated


def process_dxf(filepath, new_rev_name, initials=None):
    logger.info("process_dxf start: %s rev=%s", filepath, new_rev_name)
    filepath = str(Path(filepath).resolve())
    validate_filename_revs([filepath])
    initials = (initials or read_env_file().get("USER_INITIALS", "").strip() or "").strip()
    if not initials:
        raise ValueError("USER_INITIALS is required before processing DXF files.")

    acad = find_acad_application()
    has_manufacturing_rev, has_rev_table = check_dxf(filepath)
    if not has_manufacturing_rev:
        raise RuntimeError("No manufacturing rev text (Rev A/B/C style) was found in the drawing.")
    if not has_rev_table:
        raise RuntimeError("No REV table was found in the drawing.")

    working_filepath = archive_dxf(filepath)
    if not working_filepath:
        raise RuntimeError("The file could not be archived (target already exists or overwrite declined).")
    doc = acad.Documents.Open(working_filepath)

    try:
        manufacturing_rev = None
        if new_rev_name is not None:
            manufacturing_rev = normalize_rev_name(new_rev_name)

        updated = update_rev_texts(doc, manufacturing_rev)

        table = find_rev_table(doc)
        max_doc_rev = get_max_table_rev_letter(table)
        next_doc_rev = "AA" if max_doc_rev is None else bump_rev_letter(max_doc_rev)
        add_rev_table_entry(table, next_doc_rev, new_rev_name, initials=initials)
        save_document(doc, working_filepath)
        doc = None  # save_document already closed it
        logger.info("process_dxf done: %s (doc rev %s)", working_filepath, next_doc_rev)
        return {
            "updated": updated,
            "manufacturing_rev": new_rev_name,
            "document_rev": next_doc_rev,
        }
    except Exception:
        logger.exception("process_dxf failed for %s", filepath)
        raise
    finally:
        try:
            if doc is not None:
                doc.Close(False)
        except Exception:
            logger.debug("Close after save raised (document likely already closed)", exc_info=True)

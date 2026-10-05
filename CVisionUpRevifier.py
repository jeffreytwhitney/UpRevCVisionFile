import os
import sys
import threading
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app_logging import get_logger, setup_logging
from CVisionProcessor import (
    find_acad_application,
    normalize_rev_name,
    process_dxf,
    read_env_file,
    validate_filename_revs,
    write_env_value,
)


logger = get_logger("ui")


def show_message_box(title, message, level="info"):
    logger.info("Message [%s] %s: %s", level, title, message)
    box = QMessageBox()
    box.setWindowTitle(title)
    box.setText(message)
    if level == "warning":
        box.setIcon(QMessageBox.Icon.Warning)
    elif level == "error":
        box.setIcon(QMessageBox.Icon.Critical)
    else:
        box.setIcon(QMessageBox.Icon.Information)
    box.exec()


class CVisionProcessorWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Up Rev DXF Processor")
        self.resize(760, 560)

        self.input_folder_edit = QLineEdit()
        self.input_folder_edit.setReadOnly(True)
        self.input_folder_button = QPushButton("...")
        self.input_folder_button.clicked.connect(self.choose_input_folder)

        self.initials_edit = QLineEdit()
        self.rev_edit = QLineEdit()
        self.select_all_checkbox = QCheckBox("Select All Files")
        self.select_all_checkbox.toggled.connect(self.toggle_all_rows)
        self.execute_button = QPushButton("Execute")
        self.execute_button.clicked.connect(self.execute_selected_files)

        self.file_table = QTableWidget(0, 2)
        self.file_table.setHorizontalHeaderLabels(["File Name", "Process File"])
        self.file_table.setAlternatingRowColors(True)
        self.file_table.setSelectionBehavior(self.file_table.SelectionBehavior.SelectRows)
        self.file_table.verticalHeader().setVisible(False)
        self.file_table.setColumnWidth(0, 500)
        self.file_table.horizontalHeader().setStretchLastSection(True)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Input Folder"))
        folder_row.addWidget(self.input_folder_edit, 1)
        folder_row.addWidget(self.input_folder_button)

        form_layout = QFormLayout()
        form_layout.addRow("Initials", self.initials_edit)
        form_layout.addRow("Rev", self.rev_edit)

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(folder_row)
        main_layout.addLayout(form_layout)
        main_layout.addWidget(self.select_all_checkbox)
        main_layout.addWidget(self.file_table)
        main_layout.addWidget(self.execute_button)

        self.load_defaults()
        self.refresh_file_table()

    def load_defaults(self):
        try:
            values = read_env_file()
            self.input_folder_edit.setText(values.get("DEFAULT_PATH", "").strip())
            self.initials_edit.setText(values.get("USER_INITIALS", "").strip())
        except Exception:
            logger.exception("Failed loading defaults")

    def choose_input_folder(self):
        try:
            starting_path = self.input_folder_edit.text().strip()
            if not starting_path or not os.path.isdir(starting_path):
                starting_path = os.getcwd()
            logger.info("Choosing input folder, starting at %s", starting_path)
            selected_folder = QFileDialog.getExistingDirectory(self, "Select Input Folder", starting_path)
            if not selected_folder:
                logger.info("Folder selection cancelled")
                return
            logger.info("Input folder selected: %s", selected_folder)
            self.input_folder_edit.setText(selected_folder)
            try:
                write_env_value("DEFAULT_PATH", selected_folder)
            except Exception:
                show_message_box(
                    "Settings Not Saved",
                    "The selected folder could not be remembered for next time. See error.log for details.",
                    "warning",
                )
            self.refresh_file_table()
        except Exception:
            logger.exception("Failed choosing input folder")
            show_message_box("Error", "Unable to change the input folder. See error.log for details.", "error")

    def refresh_file_table(self):
        try:
            self._refresh_file_table()
        except Exception:
            logger.exception("Failed refreshing file table")
            show_message_box("Error", "Unable to list the DXF files in that folder. See error.log for details.", "error")

    def _refresh_file_table(self):
        folder_path = self.input_folder_edit.text().strip()
        logger.info("Refreshing file table for %s", folder_path)
        self.file_table.setRowCount(0)
        if not folder_path or not os.path.isdir(folder_path):
            self.select_all_checkbox.setChecked(False)
            return

        files = sorted(
            [path for path in Path(folder_path).iterdir() if path.is_file() and path.suffix.lower() == ".dxf"],
            key=lambda path: path.name.lower(),
        )
        self.file_table.setRowCount(len(files))

        for row_index, file_path in enumerate(files):
            name_item = QTableWidgetItem(file_path.name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.file_table.setItem(row_index, 0, name_item)

            process_item = QTableWidgetItem()
            process_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            process_item.setCheckState(Qt.CheckState.Checked)
            self.file_table.setItem(row_index, 1, process_item)

        self.file_table.resizeColumnsToContents()
        self.select_all_checkbox.setChecked(True)

    def toggle_all_rows(self, is_checked):
        state = Qt.CheckState.Checked if is_checked else Qt.CheckState.Unchecked
        for row_index in range(self.file_table.rowCount()):
            item = self.file_table.item(row_index, 1)
            if item is not None:
                item.setCheckState(state)

    def execute_selected_files(self):
        try:
            self._execute_selected_files()
        except Exception:
            logger.exception("Unexpected failure while executing")
            show_message_box("Error", "An unexpected error occurred. See error.log for details.", "error")

    def _execute_selected_files(self):
        folder_path = self.input_folder_edit.text().strip()
        if not folder_path or not os.path.isdir(folder_path):
            show_message_box("Input Folder Required", "Select a valid input folder before executing.", "warning")
            return

        initials_value = self.initials_edit.text().strip()
        if not initials_value:
            show_message_box("Initials Required", "Enter initials before processing files.", "warning")
            return

        rev_value = self.rev_edit.text().strip()
        if not rev_value:
            show_message_box("Rev Required", "Enter the target Rev before processing files.", "warning")
            return

        try:
            normalize_rev_name(rev_value)
        except ValueError as exc:
            show_message_box("Invalid Rev", str(exc), "error")
            return

        selected_paths = []
        for row_index in range(self.file_table.rowCount()):
            item = self.file_table.item(row_index, 1)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                filename_item = self.file_table.item(row_index, 0)
                if filename_item is not None:
                    selected_paths.append(Path(folder_path) / filename_item.text())

        if not selected_paths:
            show_message_box("No Files Selected", "Choose at least one DXF file to process.", "warning")
            return

        try:
            validate_filename_revs(selected_paths)
        except ValueError as exc:
            show_message_box("Invalid File Name", str(exc), "error")
            return

        write_env_value("DEFAULT_PATH", folder_path)
        write_env_value("USER_INITIALS", initials_value)

        try:
            find_acad_application()
        except Exception as exc:
            show_message_box("AutoCAD Error", str(exc), "error")
            return

        total = len(selected_paths)
        logger.info("Processing %d file(s), rev=%s", total, rev_value)

        self._progress = QProgressDialog("Starting...", "Cancel", 0, total, self)
        self._progress.setWindowTitle("Processing")
        self._progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        self._progress.setMinimumDuration(0)
        self._progress.setAutoClose(False)
        self._progress.setAutoReset(False)
        self._progress.setValue(0)

        self._thread = QThread()
        self._worker = ProcessWorker(selected_paths, rev_value, initials_value)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_worker_progress)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.finished.connect(self._thread.quit)
        self._progress.canceled.connect(self._on_cancel_requested)

        self.execute_button.setEnabled(False)
        self._progress.show()
        self._thread.start()

    def _on_worker_progress(self, index, total, name):
        self._progress.setLabelText(f"Processing file {index} of {total}\n{name}")
        self._progress.setValue(index - 1)

    def _on_cancel_requested(self):
        logger.info("Cancel requested by user")
        self._worker.cancel()
        self._progress.setLabelText("Cancelling after the current file finishes...")
        self._progress.show()

    def _on_worker_finished(self, successful_files, total, status, failed_name, error_text):
        self._progress.canceled.disconnect(self._on_cancel_requested)
        self._progress.close()
        self._thread.wait()
        self.execute_button.setEnabled(True)
        logger.info("Processing finished: status=%s, %d/%d succeeded", status, successful_files, total)

        if status == "failed":
            show_message_box(
                "Processing Error",
                f"Failed to process '{failed_name}': {error_text}\n\n"
                f"Processing stopped. {successful_files} of {total} file(s) were processed before the error.",
                "error",
            )
        elif status == "cancelled":
            show_message_box(
                "Processing Cancelled",
                f"Cancelled. Processed {successful_files} of {total} file(s) before stopping.",
                "warning",
            )
        else:
            show_message_box("Processing Complete", f"Processed {successful_files} file(s) successfully.", "info")


class ProcessWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(int, int, str, str, str)

    def __init__(self, paths, rev_value, initials_value):
        super().__init__()
        self._paths = paths
        self._rev_value = rev_value
        self._initials_value = initials_value
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()

    def run(self):
        total = len(self._paths)
        successful = 0
        status = "done"
        failed_name = ""
        error_text = ""
        com_initialized = False
        try:
            try:
                import pythoncom

                pythoncom.CoInitialize()
                com_initialized = True
            except ImportError:
                pass

            for index, file_path in enumerate(self._paths, start=1):
                if self._cancel_event.is_set():
                    status = "cancelled"
                    break
                self.progress.emit(index, total, file_path.name)
                try:
                    process_dxf(str(file_path), self._rev_value, self._initials_value)
                    successful += 1
                except Exception as exc:
                    logger.exception("Failed processing %s", file_path)
                    status = "failed"
                    failed_name = file_path.name
                    error_text = str(exc)
                    break
        except Exception as exc:
            logger.exception("Worker crashed")
            status = "failed"
            error_text = str(exc)
        finally:
            if com_initialized:
                pythoncom.CoUninitialize()
            self.finished.emit(successful, total, status, failed_name, error_text)


def main():
    setup_logging()
    logger.info("Application starting")
    try:
        app = QApplication(sys.argv)
        window = CVisionProcessorWindow()
        window.show()
        result = app.exec()
        logger.info("Application exited with code %s", result)
        return result
    except Exception:
        logger.critical("Fatal error in main", exc_info=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())

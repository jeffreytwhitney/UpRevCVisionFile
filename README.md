# CVision UpRevifier

CVision UpRevifier is a Windows desktop application for updating manufacturing revision text and revision-table entries in AutoCAD DXF drawings. It provides a PyQt6 interface for selecting a folder, choosing DXF files, entering the target revision and operator initials, and processing the selected files.

## Requirements

- Windows
- Python 3.10 or later
- AutoCAD installed and available through its Windows COM automation interface

The application uses PyQt6 for its interface, `pywin32` to automate AutoCAD, and `python-dotenv` to read environment settings.

## Setup

Clone or download the project, then create and activate a virtual environment and install the dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install PyQt6 pywin32 python-dotenv
```

Create a `.env` file beside `CVisionProcessor.py`:

```dotenv
DEFAULT_PATH=C:\path\to\dxf-files
ARCHIVE_ROOT_PATH=C:\path\to\archive
USER_INITIALS=AB
```

`DEFAULT_PATH` and `USER_INITIALS` are loaded into the application when it starts and saved when changed. `ARCHIVE_ROOT_PATH` must point to an existing folder where source drawings can be archived.

## Run

Start the application from the project directory:

```powershell
python CVisionUpRevifier.py
```

Select the folder containing the drawings, enter operator initials and the target manufacturing revision, check the files to process, and click **Execute**. The application accepts `.dxf` files, including uppercase `.DXF` extensions. Each selected filename must end with an underscore and a one- or two-letter revision, for example `Part_B.dxf`. The target revision must also be one or two letters.

For each drawing, the application uses AutoCAD to locate and update revision text and add an entry to the drawing's `REV` table. It copies the original drawing to the archive folder, then advances the revision suffix of the working file to the next available revision (for example, `Part_B.dxf` becomes `Part_C.dxf`). The drawing must contain both revision text and a `REV` table to be processed.

## Tests

Install the test dependencies and run the unit and UI tests:

```powershell
python -m pip install pytest pytest-qt
python -m pytest
```

The integration tests use AutoCAD through COM and are skipped when AutoCAD is unavailable.

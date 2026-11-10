# Installation

## Windows executable (recommended)

No Python installation is needed.

1. Download `Moby-DIC-<version>-windows-x64.zip` and extract it anywhere (for example
   `C:\Programs\Moby-DIC` or your Documents folder). Keep the `Moby-DIC` folder together: the
   executable needs the `_internal` folder next to it.
2. Double-click `Moby-DIC.exe`.
3. A console window opens and shows the local address (`http://127.0.0.1:8770/`); the interface
   opens in your default web browser. If it does not, copy the address into the browser.
4. On the first start, choose the language (English or Português). It can be changed later in the
   top bar.

To quit, click **Quit** in the top bar of the page, or close the console window.

> **Windows SmartScreen.** The executable is not digitally signed, so on the first run Windows may
> show *"Windows protected your PC"*. Click **More info → Run anyway**. You can check the
> integrity of the download against the checksum published with the release.

> **First analysis.** The correlation kernel is compiled for your processor the first time an
> analysis runs (about 30 s). The compiled code is cached in `%APPDATA%\Moby-DIC\numba_cache`, so
> later analyses start immediately.

### System requirements

| | Minimum | Recommended |
|---|---|---|
| OS | Windows 10, 64-bit | Windows 10/11, 64-bit |
| CPU | 2 cores | 8 or more cores (the correlation is parallel) |
| RAM | 4 GB | 16 GB for sequences of several hundred 5-megapixel images |
| Disk | 700 MB for the program | plus ~10–200 MB per result |
| Browser | any recent Chrome, Edge or Firefox | Chrome or Edge (MP4 video export) |

## From source (Windows, Linux, macOS)

Requires Python 3.10–3.12.

```bash
git clone <repository-url> moby-dic
cd moby-dic
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt      # Linux/macOS: .venv/bin/python
.venv/Scripts/python -m mobydic                              # opens the interface
```

On Windows, `Moby-DIC.bat` runs the last command. The package can also be installed with
`pip install .`, which provides the `moby-dic` command.

Optional extras (`requirements-extra.txt`): the muDIC backend, the test suite, the documentation
builder and the executable packager.

```bash
.venv/Scripts/python -m pip install -r requirements-extra.txt
.venv/Scripts/python -m pytest tests        # synthetic accuracy tests
.venv/Scripts/python docs/build_docs.py     # builds docs/html
empacotamento\construir_exe.bat             # builds the Windows executable and ZIP
```

## Where Moby-DIC stores files

| What | Location |
|---|---|
| Preferences (language, last scale, last folders, list of results) | `%APPDATA%\Moby-DIC\config.json` (Linux/macOS: `~/.config/moby-dic/`) |
| Compiled kernel cache | `%APPDATA%\Moby-DIC\numba_cache` |
| Results (default working folder) | `Documents\Moby-DIC\<analysis name>` |
| Example datasets | `Documents\Moby-DIC\examples\<name>` |

Deleting `config.json` resets the preferences (the language question is asked again).

## Uninstalling

Delete the `Moby-DIC` program folder and, if you wish, `%APPDATA%\Moby-DIC`. Your results in the
working folder are not touched.

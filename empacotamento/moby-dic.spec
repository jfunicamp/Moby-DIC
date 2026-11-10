# PyInstaller: gera dist\Moby-DIC\Moby-DIC.exe (pasta autocontida, sem precisar de Python instalado).
# Uso: empacotamento\construir_exe.bat
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

RAIZ = Path(SPECPATH).parent
icone = str(RAIZ / "mobydic" / "assets" / "moby-dic.ico")

ocultos = collect_submodules("mobydic")
try:
    import muDIC  # noqa: F401
    ocultos += collect_submodules("muDIC")
except ImportError:
    pass

a = Analysis(
    [str(RAIZ / "empacotamento" / "moby_dic_entry.py")],
    pathex=[str(RAIZ)],
    datas=[
        (str(RAIZ / "mobydic" / "web" / "app.html"), "mobydic/web"),
        (str(RAIZ / "mobydic" / "assets"), "mobydic/assets"),
        (str(RAIZ / "docs" / "html"), "mobydic/docs"),          # documentação (docs/build_docs.py)
        # código-fonte do núcleo numba: permite o cache de compilação no executável
        (str(RAIZ / "mobydic" / "subsets.py"), "mobydic"),
    ],
    hiddenimports=ocultos + ["skimage.registration"],
    excludes=["tkinter", "h5py", "IPython", "PyQt5", "PySide6", "notebook", "pytest", "nose", "playwright", "markdown", "imageio_ffmpeg"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Moby-DIC",
    icon=icone,
    console=True,        # janela de console mostra o endereço local e o log; fechá-la encerra o programa
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Moby-DIC")

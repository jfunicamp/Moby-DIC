"""Ponto de entrada do executável (PyInstaller)."""

import multiprocessing
import sys

from mobydic.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main() or 0)

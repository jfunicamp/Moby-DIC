# Third-party software

Moby-DIC is distributed under the MIT License (see `LICENSE`). The Windows executable bundles the
Python interpreter and the libraries below, each under its own permissive license. Their license
texts are included in the executable folder (`_internal\*.dist-info`) and are available from the
projects' websites.

| Component | License | Use in Moby-DIC |
|---|---|---|
| Python | PSF License | interpreter (executable only) |
| NumPy | BSD-3-Clause (bundles OpenBLAS, BSD-3-Clause, and GCC runtime libraries under the GCC Runtime Library Exception) | arrays, linear algebra |
| SciPy | BSD-3-Clause | B-spline prefiltering, image filters |
| Numba / llvmlite | BSD-2-Clause (llvmlite bundles LLVM, Apache-2.0 with LLVM exception) | compiled, parallel correlation kernels |
| scikit-image | BSD-3-Clause | phase correlation (global jump detection) |
| imageio, tifffile | BSD-2-Clause, BSD-3-Clause | image reading (via scikit-image) |
| Pillow | MIT-CMU (HPND) | image reading and writing |
| Matplotlib (with contourpy, cycler, kiwisolver, fonttools, pyparsing, python-dateutil) | Matplotlib License (PSF-based), BSD, MIT | static figures |
| natsort | MIT | natural sorting of file names |
| OpenCV (opencv-python-headless) | Apache-2.0; its video module loads FFmpeg from a separate DLL (`opencv_videoio_ffmpeg`), built by the OpenCV project under the LGPL-2.1 without GPL components | reading video files (frame extraction) |
| muDIC (optional) | MIT | global FE-DIC backend, only if installed |
| PyInstaller bootloader | GPL-2.0-or-later with the PyInstaller bootloader exception (allows distribution of the generated executable under any license) | executable packaging |

The interactive viewer (`visualizador.html`) is self-contained and uses no third-party JavaScript.
Colormap lookup tables in the viewer are sampled from Matplotlib (jet, turbo, viridis, plasma,
inferno, magma, cividis, coolwarm, RdBu_r, seismic, bwr, gray).

## Scientific references

The methods implemented follow the open literature; see `docs/theory.md` for the full list
(Sutton, Orteu & Schreier 2009; Pan et al. 2009, 2013; Baker & Matthews 2004; Blaber et al. 2015;
Olufsen et al. 2020; iDICs Good Practices Guide 2018).

# Changelog

## 1.1.0 — 2026-11-10

- **Video input**: step 1 has a *Video file* tab. Moby-DIC measures the motion along the video and
  recommends the test interval (start, end, stopping before fracture) and the number of frames;
  the frames are extracted to PNG with their times (`frames.csv`). Command `moby-dic video`.
- **Digital extensometer** in the viewer: two material points picked in the initial frame (or an
  automatic suggestion) give the engineering and true strain over the test, plotted against frame
  or video time, drawn on the maps and exported to CSV.
- The source launcher `Moby-DIC.bat` creates its Python environment on the first run.

## 1.0.0 — 2026-11-10

First public release.

- Guided workflow (images, scale, ROI, method and grid, reference, output, run, view) with
  automatic values for every parameter.
- Local subset DIC: IC-GN, ZNSSD, affine shape function, cubic B-spline interpolation, numba
  parallel kernels.
- Robustness: automatic reference updating (median ZNCC, p05 ZNCC and failure fraction), rejection
  of false matches (degenerate warps and points inconsistent with their neighbours), lost-point
  recovery, rescue against the previous frame, global-jump detection by phase correlation,
  sharpness matching for refocused frames, bad frames never used as references.
- True strains from local plane fitting; rotation; derived fields in the viewer.
- Self-contained interactive viewer: 1/2/4 panels, 18 fields, 13 colormaps, zoom, animation,
  PNG / ZIP / video export.
- English and Portuguese interface, log messages, figures and viewer; language chosen at the first
  start.
- Synthetic example datasets with exact solutions (`moby-dic example`), used by the tutorials.
- Command line with English option names (Portuguese aliases kept).
- Optional muDIC backend (Q4 and B-spline global DIC).
- Windows executable; MIT License.

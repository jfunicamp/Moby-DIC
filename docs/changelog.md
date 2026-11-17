# Changelog

## 1.3.1 — 2026-11-17

Project infrastructure; the program is unchanged.

- **Contributing:** `CONTRIBUTING.md` explains how to report problems, set up a development
  environment, run the tests and propose changes, and how AI assistance is used in development.
- **Continuous integration:** the test suite runs on Linux and Windows for every push and pull request.
- **Citation:** complete `CITATION.cff` (authors, affiliation, repository, abstract); releases are
  archived on Zenodo with a DOI.

## 1.3.0 — 2026-11-17

- **Viewer: stress vs crosshead position.** New option in the chart menu: the whole machine curve
  (stress, or load, against crosshead position in mm) with the analysed frames and the current frame
  marked, like the stress–strain chart of the extensometer. It needs no extensometer and is exported
  with figures and videos. The frame line shows the crosshead position and the extensometer CSV has
  a `crosshead_mm` column. `ensaio.json` now keeps the position in the reduced machine curve.
- **Acquisition rate for videos** (*Acquisition rate* in step 1; `moby-dic video --acquisition-fps`):
  places the k-th real frame at k/rate s instead of using the recorder's clock, for recorders whose
  clock disagrees with the camera (a microscope AVI stored 4.78 frames/s for a 5 frames/s
  acquisition). `video_source.json` records the time base. Changing the rate does not read the video
  again (the motion curve is cached).
- **Viewer: frames before the analysis.** When the analysis starts after the first image (for example
  Nomarski videos, where the DIC only holds near maximum stress), the earlier images of the folder
  are included as image-only frames: the microstructure, the time and the point on the machine curve
  (stress vs time or vs crosshead position), with *no DIC in this frame* on the map and a *DIC starts*
  line on the chart. `moby-dic viewer --no-pre-frames` leaves them out.

## 1.2.0 — 2026-11-16

- **Tensile test correlation** (step 8 *Tensile test*; command `moby-dic tensile`): reads the machine
  curve (CSV/TXT, any separator and decimal mark, columns recognised by name), detects the fracture
  in the curve and in the images (motion jump between consecutive frames, distinguished from
  refocusing), and aligns them with the recording frame rate; manual synchronisation by the time of
  the first image. Writes `ensaio_por_quadro.csv` and `ensaio.json`.
- **Viewer**: stress–strain chart of the digital extensometer, machine curve with the analysed
  frames, test time and stress of every frame in the frame line and exported figures; extensometer
  CSV with load and stress.
- Video extraction records the exact fracture time in the video, so results from videos are
  synchronised without a frame rate.
- Unreadable (corrupted) images are skipped with a warning instead of stopping the analysis.
- **Viewer layout**: specimen map on the left, extensometer / stress–strain chart on the right, one
  timeline bar; display settings, 2/4-panel comparison and the extensometer gauge definition in a
  collapsible Options panel; per-map colour-scale controls behind a *scale* button. Exported figures
  and videos use the same side-by-side layout.
- **Extensometer gauge definition**: L₀, centre and averaging band, editable and written to the CSV
  header, for reproducible gauges across specimens.
- Image-scan motion measurement corrected (OpenCV phase correlation returned a constant 0.5 px offset
  for odd block sizes); 16-bit images keep their contrast in the scan.
- **Variable-frame-rate videos** (microscope cameras that write a nominal rate with empty frames):
  real frame times are read from the file and used for the motion curve, the extraction,
  `frames.csv` and the fracture time.
- **Pattern quality**: predicted displacement error of each subset (√2·noise/√SSSIG) summarised in
  step 1 and drawn as a map over the step 4 preview, to judge natural textures such as etched
  microstructures.
- The automatic ROI uses the whole image when the specimen fills the field of view (microscopy).
- **Reference bridge**: the correlation no longer stays stuck on a reference that stopped matching
  (for example a blurred frame just before a refocus). After three bad frames in a row against the
  last good frame, the current frame becomes the reference (state `ponte`, listed in
  `parametros.json`) if it measured at least half of the minimum fraction.

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

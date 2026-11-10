# Troubleshooting and FAQ

## The program

**The browser does not open.** Copy the address shown in the console window
(`http://127.0.0.1:8770/`, or the next free port) into any browser.

**"Windows protected your PC".** The executable is not signed. Click *More info → Run anyway*.

**The first analysis seems stuck at the beginning.** The correlation kernel is being compiled
(~30 s, only once per installation).

**The language question appears again.** The preferences file `%APPDATA%\Moby-DIC\config.json` was
deleted or could not be written (check folder permissions).

**How do I change the language?** With the selector in the top bar of the application, and in the
viewer with its own *Language* selector.

**Can I run Moby-DIC on another computer of the network?** The server only listens on
`127.0.0.1` for safety; run Moby-DIC on the computer that has the images.

**Can several analyses run at once?** One at a time per application. Use the
[command line](command-line.md) to run several in parallel (they share the CPU).

## Images and ROI

**"no images in this folder".** Supported formats: PNG, TIF/TIFF, BMP, JPG/JPEG. All images in the
sequence must have the same size.

**The automatic ROI is wrong.** The detector looks for a bright specimen on a darker background
with the load along x. For other set-ups (dark specimen, vertical loading, full-field speckle),
draw the ROI by hand in step 3.

**Holes at the edges of the maps.** Subsets near the specimen edges leave the speckle as the
specimen contracts. Shrink the ROI by a few subset half-widths.

## Correlation

**Many lost points in some frames.** Look at `convergencia.csv`. Typical causes: a sudden change of
focus or lighting, motion blur, reflections, paint cracking at large strains. Check that
*Rescue lost points* and automatic reference updating are on; enable *Match sharpness on every
frame* if focus varies. Points that cannot be measured are reported as missing, not guessed.

**Frames marked `quadro_ruim` (bad frame).** Fewer than 50 % of the points were measured. These
frames never become references; the analysis continues with the next frames. If they are at the
end of the test (fracture), drop them from the viewer with `--until-frame`.

**Noisy strain maps.** Increase the strain window (7 or 9), then the subset. Check the speckle size
and the image noise ([Good practice](good-practice.md)).

**Strain appears in a specimen that is not loaded.** Out-of-plane motion (apparent strain Δz/Z),
lens distortion or a thermal drift of the camera. These are optical, not software, effects.

**The peak strain seems too low.** The strain spatial resolution (virtual strain gauge) is larger
than the feature; see [Theory § 9](theory.md#spatial-resolution).

**Results disagree with a commercial DIC system.** Compare with the same subset, step, strain
window, strain measure (true vs engineering, Green-Lagrange vs logarithmic) and reference. Also
check that both use the same image orientation and origin (Moby-DIC: lower-left origin, y up).

## Results

**Where are the results?** In the working folder chosen in step 6 (default
`Documents\Moby-DIC\<name>`). The viewer step lists them and opens the folder.

**The viewer file is large.** Rebuild it with a larger display cell or a smaller background:
`moby-dic viewer FOLDER --cell 8 --background-width 480`.

**Video export does not offer MP4.** MP4 recording is supported by recent Chrome and Edge; other
browsers record WebM, which most players and presentation software accept.

**Why are file and column names in Portuguese?** They are kept stable for compatibility between
versions and languages; [Output files](output-files.md) translates them.

## Reporting a problem

Include the Moby-DIC version (*About*), `parametros.json` and `convergencia.csv` of the result and,
if possible, two or three images that reproduce the problem.

# Good experimental practice

DIC measures what the camera sees. The quality of the images matters far more than any software
parameter. The recommendations below summarise the iDICs *Good Practices Guide* (2018) for 2D DIC.

## Speckle pattern

- **Random, isotropic, high contrast**: dark dots on a white background (or the reverse), with
  about 50 % coverage. Avoid regular patterns.
- **Size: 3–5 pixels per dot** in the image. Smaller dots alias (the camera cannot resolve them);
  much larger dots force large subsets and reduce the spatial resolution. Moby-DIC reports the
  measured speckle size in step 4; the subset is ≈ 3.25 times that.
- **Thin and adherent**: the paint must follow the surface without cracking or peeling at the
  strains of interest. Apply a thin, matte white base coat, then the black speckle with an airbrush
  or spray can held far from the specimen.
- **Matte**: glossy paint creates specular reflections that move with the surface orientation.

## Camera and optics

- **Perpendicular** to the specimen surface, with the surface in the focal plane. Small
  misalignments cause apparent strains.
- **Out-of-plane motion** is the main error source in 2D DIC: an apparent strain of about Δz/Z.
  Use a long working distance (a longer focal length further away), or a **telecentric lens**.
  Check by translating the specimen towards the camera by a known amount without load.
- **Lens distortion**: prefer good-quality fixed focal-length lenses and keep the region of
  interest near the image centre.
- **Depth of field**: close the aperture enough that the surface stays in focus throughout the
  test, especially if the specimen necks or the grips move it. Do not refocus during a test if you
  can avoid it.
- **Resolution**: choose the magnification so that the smallest feature you need to resolve spans
  several virtual strain gauges.

## Lighting and exposure

- Uniform, diffuse, **constant** light; LED panels are better than flicker-prone lamps.
- Use the full dynamic range (histogram spread over the grey levels) **without saturation**:
  saturated pixels carry no information.
- Short exposure times avoid motion blur in fast tests; compensate with light, not with gain
  (gain increases noise).
- Save images in a **lossless** format (TIFF, PNG). 12- or 16-bit TIFFs are read directly.

## Acquisition

- Take a few **static images before loading**. Correlating them against each other gives the
  noise floor of your set-up (displacement and strain resolution), which should be reported with
  the results.
- Acquire images at a rate such that the strain increment between consecutive images is well below
  1 %; you can always analyse one image every N later.
- Synchronise images with the load signal (time stamps or a trigger), so that stress and strain can
  be combined.
- Record the calibration image (ruler or target in the specimen plane) with the same set-up.

## Choosing analysis parameters

- Start with the automatic values.
- If maps are noisy, increase the strain window first (5 → 7 or 9), then the subset.
- If features are smoothed (sharp necks, thin layers, cracks), reduce the window and the step, then
  the subset, and accept more noise.
- Always report subset, step, strain window (or the virtual strain gauge size), the reference
  strategy and the noise floor alongside DIC results.

## Reporting checklist

| Item | Example |
|---|---|
| Software and version | Moby-DIC 1.1.0, subset DIC (IC-GN, ZNSSD, affine, cubic B-spline) |
| Camera, lens, resolution, scale | 5 MP, 100 mm macro, 1.76 µm/px |
| Speckle technique and size | airbrushed black on white, 4 px |
| Subset, step, strain window, VSG | 25 px, 5 px, 5 points, 45 px (79 µm) |
| Strain measure | true (logarithmic) strain, plane-fit differentiation |
| Reference strategy | automatic updating (ZNCC thresholds 0.98 / 0.95) |
| Noise floor | std of εxx on static images: 0.03 % |

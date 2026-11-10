# Command line and Python

Everything the interface does is available from the command line, for batch processing or
scripted studies. In the commands below `moby-dic` stands for `Moby-DIC.exe` (executable, run in
its folder or with its full path) or `python -m mobydic` (source).

```text
moby-dic                     open the application
moby-dic gui [--port N] [--no-browser]
moby-dic subsets ...         subset DIC
moby-dic viewer FOLDER ...   (re)build the viewer of a result
moby-dic mudic ...           muDIC backend (if installed)
moby-dic example [NAME]      generate a synthetic example dataset
moby-dic --version | --help
```

Messages and figures follow the language saved in the preferences; set the environment variable
`MOBYDIC_LANG=en` (or `pt`) to force one. Portuguese option names (`--imagens`, `--saida`, …) are
accepted as aliases of the English ones.

## subsets

```bash
moby-dic subsets --images IMAGES_FOLDER --output RESULT_FOLDER --scale-um-px 1.76
```

Without `--roi`, the ROI is detected automatically; without `--scale-um-px`, results are in pixels.
The output folder must not exist.

| Option | Default | Description |
|---|---|---|
| `--images DIR` | required | folder with the image sequence |
| `--output DIR` | required | result folder (created) |
| `--scale-um-px S` | none | calibration, µm per pixel |
| `--roi X1 Y1 X2 Y2` | automatic | ROI in px, origin at the **lower-left** corner |
| `--subset N` | 25 | subset side, px (odd ≥ 7) |
| `--step N` | 5 | grid spacing, px |
| `--strain-window N` | 5 | plane-fit window, grid points (odd ≥ 3) |
| `--reference-every N` | 0 | 0 = automatic updating; N = every N frames; a very large N = fixed reference |
| `--zncc-ref`, `--zncc-ref-p05`, `--fail-ref` | 0.98, 0.95, 0.003 | automatic-update thresholds |
| `--zncc-min` | 0.8 | minimum ZNCC to accept a point |
| `--match-sharpness` | off | sharpness matching on every frame |
| `--no-rescue` | | disable the rescue against the previous frame |
| `--min-fraction` | 0.5 | minimum measured fraction for a frame to become a reference |
| `--search N` | 6 | integer search radius for recovery, px |
| `--maxit N` | 50 | maximum IC-GN iterations |
| `--threads N` | half of the cores | parallel threads |
| `--first N`, `--last N`, `--every N` | 1, last, 1 | frame selection (1-based image numbers) |
| `--limit N` | | maximum number of frames (after `--every`) |

The subset command does not build the viewer; run `moby-dic viewer` afterwards.

Note that the interface asks for ROI coordinates with the origin at the top-left corner of the
displayed image, whereas `--roi` uses the lower-left origin of the results: y_cli = height − 1 −
y_image.

## viewer

```bash
moby-dic viewer RESULT_FOLDER [--lang en] [--cmap jet] [--until-frame N] [--cell 6] [--background-width 640] [--quality 65]
```

`--cell` is the display grid cell (px of the original image): smaller is sharper and larger.
`--until-frame` drops the last frames (e.g. after fracture). Several folders can be given.

## example

```bash
moby-dic example                       # list the examples
moby-dic example necking               # writes Documents\Moby-DIC\examples\necking
moby-dic example all --output D:\tmp   # all examples in another folder
```

## Batch processing

A PowerShell loop over the specimens of a campaign:

```powershell
foreach ($d in Get-ChildItem D:\campaign -Directory) {
  & "C:\Programs\Moby-DIC\Moby-DIC.exe" subsets --images $d.FullName --output "D:\results\$($d.Name)" --scale-um-px 1.76
  & "C:\Programs\Moby-DIC\Moby-DIC.exe" viewer "D:\results\$($d.Name)" --lang en
}
```

The same in bash (source installation):

```bash
for d in campaign/*/; do
  n=$(basename "$d")
  python -m mobydic subsets --images "$d" --output "results/$n" --scale-um-px 1.76
  python -m mobydic viewer "results/$n" --lang en
done
```

## Using Moby-DIC from Python

```python
from mobydic import subsets
subsets.main(["--images", "imgs", "--output", "res", "--scale-um-px", "2.0", "--threads", "8"])

from mobydic.viewer import gerar
gerar("res", 6.0, 640, 65, cmap_padrao="viridis", idioma="en")   # cell, background width, JPEG quality
```

Reading and post-processing results is shown in
[Tutorial 4](tutorials/04-python-post-processing.md).

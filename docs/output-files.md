# Output files

Each analysis writes one folder. File names are the same in both interface languages.

| File | Content |
|---|---|
| `visualizador.html` | interactive [viewer](viewer.md) (self-contained) |
| `campos.npz` | all fields on the measurement grid (NumPy archive, see below) |
| `resumo_por_quadro.csv` | per frame: number of valid points, mean / 5th / 95th percentile of uₓ, u_y, εxx, εyy, minimum det F |
| `campos_por_ponto.csv` | one row per point and frame (all frames when the table is small, otherwise the frames of the static maps) |
| `convergencia.csv` | per frame: reference frame used, state, active fraction, rescued points, ZNCC median and p05, median iterations, sharpness-matching σ, time |
| `qualidade_subsets.npz` | ZNCC and iteration count of every point and frame |
| `parametros.json` | every parameter used by the correlation, the reference frames and the list of bad frames |
| `config_analise.json` | the configuration chosen in the interface, including which values were automatic |
| `malha_referencia.png` | the first image with the measurement points |
| `mapas_<frame>.png` | uₓ, u_y, εxx, εyy maps of a few frames |
| `evolucao_por_quadro.png` | mean and p05–p95 band of uₓ, u_y, εxx, εyy over the frames |

Together, `parametros.json` and `config_analise.json` are enough to reproduce an analysis.

### Frames extracted from a video

| File (frame folder) | Content |
|---|---|
| `frame_0001.png` … | extracted frames, 8-bit grey |
| `frames.csv` | per frame: index, file, frame number in the video, time (s) |
| `video_source.json` | video path, frame rate, start/end time, number of frames, codec |

## campos.npz

Arrays are indexed `[frame, row, column, ...]`. Rows run along y and columns along x of the
measurement grid. Coordinates use the Moby-DIC system: origin at the **lower-left** corner of the
image, x to the right, y up; row 0 is the bottom row of the grid.

| Key | Shape | Description |
|---|---|---|
| `centro_xy_px` | T × ny × nx × 2 | current position (x, y) of each point, px |
| `deslocamento_xy_px` | T × ny × nx × 2 | total displacement (uₓ, u_y), px |
| `deslocamento_xy_um` | T × ny × nx × 2 | total displacement, µm (equals px when uncalibrated) |
| `deformacao_xx`, `deformacao_yy` | T × ny × nx | true strains εxx, εyy (dimensionless, not %) |
| `deformacao_xy` | T × ny × nx | shear strain εxy (dimensionless) |
| `rotacao` | T × ny × nx | local rotation ω, radians |
| `valido` | T × ny × nx, bool | point measured in that frame (use it as a mask) |
| `arquivos` | T | image file name of each frame |
| `estado` | T | frame state: `referencia`, `convergiu` (converged) or `quadro_ruim` (bad frame) |
| `escala_um_px`, `calibrado` | scalars | scale and whether it was supplied |

The initial position of each point is `centro_xy_px[0]`. Values where `valido` is False are not
measurements and must be ignored. See [Tutorial 4](tutorials/04-python-post-processing.md) for
examples.

## CSV conventions

UTF-8, comma-separated, decimal point. Column suffixes give the unit: `_um` micrometres, `_px`
pixels (uncalibrated), `_pct` percent. Portuguese column names: *indice* = frame index, *arquivo*
= file, *linha/coluna* = grid row/column, *media* = mean, *pontos_validos* = valid points.

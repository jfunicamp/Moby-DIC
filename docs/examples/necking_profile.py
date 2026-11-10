"""Tutorial 4: strain profile through the neck, compared with the exact solution.

    python necking_profile.py RESULT_FOLDER [EXAMPLE_FOLDER]

RESULT_FOLDER   a Moby-DIC result of the "necking" example (contains campos.npz)
EXAMPLE_FOLDER  the example images (contains ground_truth.json);
                default: Documents/Moby-DIC/examples/necking
"""

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def main(resultado, exemplo):
    with np.load(Path(resultado) / "campos.npz") as z:
        d = {k: z[k] for k in z.files}
    gt = json.loads((Path(exemplo) / "ground_truth.json").read_text())

    valid, exx = d["valido"], d["deformacao_xx"]
    pos = d["centro_xy_px"]                   # [frame, row, col, (x, y)]
    t = len(exx) - 1                          # last frame
    x = pos[0, 0, :, 0]                       # initial x of each grid column, px

    # mean over the rows (height of the ROI), measured points only
    prof = np.nanmean(np.where(valid[t], exx[t], np.nan), axis=0)

    xe = np.linspace(x.min(), x.max(), 600)
    exact = np.log1p(gt["e0"][t] + gt["a"][t] * np.exp(-((xe - gt["xc_px"]) / gt["s_px"]) ** 2))
    print(f"peak: measured {100 * np.nanmax(prof):.2f} %, exact {100 * exact.max():.2f} %")

    # virtual extensometer between x = 200 and 800 px (middle row)
    row = pos.shape[1] // 2
    c1, c2 = np.argmin(abs(x - 200)), np.argmin(abs(x - 800))
    L0 = pos[0, row, c2, 0] - pos[0, row, c1, 0]
    ext = (pos[:, row, c2, 0] - pos[:, row, c1, 0]) / L0 - 1
    print("virtual extensometer (engineering strain, %):", np.round(100 * ext, 2))

    plt.plot(xe, 100 * exact, "k-", label="exact")
    plt.plot(x, 100 * prof, "o", ms=3, label="Moby-DIC")
    plt.xlabel("initial position x (px)")
    plt.ylabel("εxx (%)")
    plt.legend()
    plt.title("Necking example, last frame")
    plt.show()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    padrao = Path.home() / "Documents" / "Moby-DIC" / "examples" / "necking"
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else padrao)

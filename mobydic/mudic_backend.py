"""Moby-DIC · backend opcional muDIC: correlaciona a sequência com o muDIC (malha Q4 ou B-spline) e exporta campos x/y.

Sistema de coordenadas
----------------------
O leitor de imagens do muDIC inverte as imagens verticalmente: a linha 0 do array é a
última linha do PNG. As coordenadas do muDIC são, portanto, um sistema cartesiano com
origem no canto inferior esquerdo da imagem, x para a direita e y PARA CIMA. Todos os
resultados do Moby-DIC usam esse sistema.

Malha B-spline
--------------
O muDIC 0.2.1 trata a malha B-spline como UMA superfície que cobre a ROI e monta matrizes
densas (3 × pontos de controle × pixels da ROI). A memória limita o número de pontos de
controle; com 10 × 8 o pico fica perto de 3 GB. O mesher troca os argumentos n_elx/n_ely
no caso spline, e o modo de precisão "single" falha; ambos são tratados aqui.
"""

import argparse
import csv
import json
import logging
import re
from importlib.metadata import version
from pathlib import Path

import numpy as np

from .export import exportar
from .i18n import t as tx
from .imagens import listar_imagens

try:
    import muDIC as dic
except ImportError:  # muDIC é opcional
    dic = None

ROI = dict(Xc1=200, Xc2=1500, Yc1=100, Yc2=1000)
ELEMENTO_PX = 30
PASSO_GRADE_SPLINE_PX = 10


class RegistroSolver(logging.Handler):
    """Captura os estados por quadro que o muDIC registra apenas no log."""

    def __init__(self, maxit):
        super().__init__()
        self.maxit = maxit
        self.quadro = 0
        self.estados = {0: ("referencia", None)}

    def emit(self, record):
        mensagem = record.getMessage()
        if mensagem.startswith("Processing frame nr: "):
            self.quadro = int(mensagem.rsplit(" ", 1)[1])
        elif match := re.fullmatch(r"(?:Frame c|C)onverged in (\d+) iterations", mensagem):
            self.estados[self.quadro] = ("convergiu", int(match[1]) + 1)
        elif mensagem.startswith(("Did not converged in ", "Frame did not converge")):
            self.estados[self.quadro] = ("nao_convergiu", self.maxit)
        elif record.levelno >= logging.ERROR:
            self.estados[self.quadro] = ("erro", None)


def criar_malha(images, tipo, elemento_px, pontos_controle):
    if tipo == "q4":
        n_elx = max(1, round((ROI["Xc2"] - ROI["Xc1"]) / elemento_px))
        n_ely = max(1, round((ROI["Yc2"] - ROI["Yc1"]) / elemento_px))
        mesh = dic.Mesher().mesh(images, **ROI, n_ely=n_ely, n_elx=n_elx, GUI=False)
        if type(mesh.element_def).__name__ != "Q4" or mesh.n_elms != n_elx * n_ely:
            raise RuntimeError("Esperava a malha Q4 padrão.")
        return mesh, {"elementos_xy": [n_elx, n_ely],
                      "tamanho_elemento_px": [(ROI["Xc2"] - ROI["Xc1"]) / n_elx,
                                              (ROI["Yc2"] - ROI["Yc1"]) / n_ely]}
    nx, ny = pontos_controle
    # O muDIC 0.2.1 associa n_ely à direção e (x) e n_elx à direção n (y) no caso spline.
    mesh = dic.Mesher(deg_e=3, deg_n=3, type="spline").mesh(
        images, **ROI, n_elx=ny, n_ely=nx, GUI=False)
    el = mesh.element_def
    if (el.n_nodes_e, el.n_nodes_n) != (nx, ny):
        raise RuntimeError("Pontos de controle não correspondem ao pedido.")
    return mesh, {"pontos_controle_xy": [nx, ny], "grau": [3, 3],
                  "vaos_de_no_px": [(ROI["Xc2"] - ROI["Xc1"]) / (nx - 3),
                                    (ROI["Yc2"] - ROI["Yc1"]) / (ny - 3)]}


def grade_spline(fields):
    """Converte a saída de Fields (B-spline, 1 elemento) para [T, linha_y, coluna_x, ...]."""
    coords = fields.coords()[0]            # [2, A, B, T]
    grad = fields.F()[0]                   # [2, 2, A, B, T]
    x = coords[0, ..., 0]
    eixo_a_e_x = abs(x[1, 0] - x[0, 0]) > abs(x[0, 1] - x[0, 0])
    coords = coords.transpose(3, 1, 2, 0)  # [T, A, B, 2]
    grad = grad.transpose(4, 2, 3, 0, 1)   # [T, A, B, 2, 2]
    if eixo_a_e_x:
        coords = coords.swapaxes(1, 2)
        grad = grad.swapaxes(1, 2)
    return coords, grad


def selecionar_imagens(pasta, saida, inicio, fim, a_cada):
    """O muDIC lê a pasta inteira; para usar um subconjunto, cria uma pasta com links/cópias."""
    todos = listar_imagens(pasta)
    sel = todos[inicio - 1:(fim or len(todos))][::a_cada]
    if len(sel) == len(todos):
        return pasta, sel
    destino = saida / "_imagens_selecionadas"
    destino.mkdir(exist_ok=True)
    import os
    import shutil
    for f in sel:
        alvo = destino / f.name
        if not alvo.exists():
            try:
                os.link(f, alvo)
            except OSError:
                shutil.copy2(f, alvo)
    return destino, sel


def correlacionar(args):
    pasta, saida = args.imagens.resolve(), args.saida
    pasta_leitura, arquivos = selecionar_imagens(pasta, saida, args.inicio, args.fim, args.a_cada)
    images = dic.IO.image_stack_from_folder(str(pasta_leitura), file_type=arquivos[0].suffix.lower())
    if len(images) != len(arquivos) or len(arquivos) < 2:
        raise ValueError("A pasta precisa conter uma sequência de pelo menos dois PNGs.")
    altura, largura = images[0].shape
    if largura <= ROI["Xc2"] or altura <= ROI["Yc2"]:
        raise ValueError(f"ROI fora da imagem de {largura} x {altura} px.")

    mesh, info_malha = criar_malha(images, args.malha, args.elemento_px, args.pontos_controle)

    settings = dic.DICInput(mesh, images)
    settings.max_nr_im = min(args.limite, len(images)) if args.limite else len(images)
    settings.ref_update = list(range(args.passo_referencia, settings.max_nr_im, args.passo_referencia))
    settings.maxit = 100
    settings.tol = 1e-6
    settings.interpolation_order = 4
    settings.store_internals = False
    settings.noconvergence = "ignore"

    registro = RegistroSolver(settings.maxit)
    logger = logging.getLogger()
    logger.addHandler(registro)
    try:
        resultado = dic.DICAnalysis(settings).run()
    finally:
        logger.removeHandler(registro)

    n = settings.max_nr_im
    estados = [registro.estados.get(i, ("sem_registro", None)) for i in range(n)]
    with (saida / "convergencia.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["indice", "arquivo", "estado", "iteracoes", "indice_referencia"])
        indice_referencia = 0
        for i, (estado, iteracoes) in enumerate(estados):
            if i in settings.ref_update:
                indice_referencia = i - 1
            writer.writerow([i, arquivos[i].name, estado, iteracoes, indice_referencia])

    if resultado.xnodesT.shape[1] != n or any(
        estado in {"erro", "sem_registro"} for estado, _ in estados
    ):
        raise RuntimeError("O solver retornou resultados incompletos. Consulte o log.")

    np.savez_compressed(
        saida / "nos.npz", x_px=resultado.xnodesT, y_px=resultado.ynodesT,
        conectividade=mesh.ele.T, arquivos=[p.name for p in arquivos[:n]],
        escala_um_px=args.escala_um_px, malha=args.malha,
    )
    metadados = {
        "metodo": f"muDIC {args.malha}", "muDIC": version("muDIC"), "pasta_imagens": str(pasta),
        "tamanho_imagem_px": [largura, altura],
        "roi_xyxy_px_origem_inferior": [ROI["Xc1"], ROI["Yc1"], ROI["Xc2"], ROI["Yc2"]],
        "malha": args.malha, **info_malha, "nos": int(mesh.n_nodes),
        "escala_um_px": args.escala_um_px, "calibrado": args.calibrado,
        "quadros": n, "referencia_inicial_indice": 0, "ref_update": settings.ref_update,
        "maxit": settings.maxit, "tol_px": settings.tol,
        "interpolation_order": settings.interpolation_order,
        "filtro_previo": None, "noconvergence": settings.noconvergence,
        "eixos": "origem no canto inferior esquerdo da imagem; x para a direita, y para cima",
        "deformacao": "verdadeira (logarítmica), referida ao primeiro quadro",
    }
    (saida / "parametros.json").write_text(
        json.dumps(metadados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    if args.malha == "q4":
        fields = dic.post.viz.Fields(resultado)
        # Formato nativo Q4 [1, componente(s), x, y, quadro] -> [quadro, linha_y, coluna_x, ...].
        coords = fields.coords()[0].transpose(3, 2, 1, 0)
        grad = fields.F()[0].transpose(4, 3, 2, 0, 1)
        nos = np.stack((resultado.xnodesT[:, 0], resultado.ynodesT[:, 0]), axis=-1)
        poligonos, pontos = nos[mesh.ele.T], None
        titulo = tx("Região analisada e malha Q4", "Analysed region and Q4 mesh")
    else:
        # Fields usa seed[0] na direção y e seed[1] na direção x para este mesher.
        seed = [int((ROI["Yc2"] - ROI["Yc1"]) / PASSO_GRADE_SPLINE_PX) + 1,
                int((ROI["Xc2"] - ROI["Xc1"]) / PASSO_GRADE_SPLINE_PX) + 1]
        fields = dic.post.viz.Fields(resultado, seed=seed)
        coords, grad = grade_spline(fields)
        poligonos = None
        pontos = np.stack((resultado.xnodesT[:, 0], resultado.ynodesT[:, 0]), axis=-1)
        titulo = tx("Região analisada e pontos de controle B-spline", "Analysed region and B-spline control points")
    if not np.allclose(grad[0], np.eye(2), atol=1e-6):
        raise RuntimeError("Gradiente inicial diferente da identidade.")
    disp = coords - coords[:1]
    exportar(saida, lambda i: images[i], arquivos[:n], [e for e, _ in estados], args.escala_um_px,
             coords, disp, grad, calibrado=args.calibrado,
             poligonos_ref=poligonos, pontos_ref=pontos, titulo_malha=titulo)


def main(argv=None):
    if dic is None:
        raise SystemExit(tx("O backend muDIC não está instalado (pip install muDIC). Use o método por subsets.",
                            "The muDIC backend is not installed (pip install muDIC). Use the subset method."))
    parser = argparse.ArgumentParser(prog="Moby-DIC mudic", description=tx(__doc__, "Moby-DIC · optional muDIC backend: global FE-DIC with a Q4 or B-spline mesh."),
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--images", "--imagens", metavar="IMAGES", dest="imagens", type=Path, required=True)
    parser.add_argument("--output", "--saida", metavar="OUTPUT", dest="saida", type=Path, required=True)
    parser.add_argument("--mesh", "--malha", dest="malha", choices=["q4", "spline"], default="q4")
    parser.add_argument("--scale-um-px", "--escala-um-px", metavar="SCALE_UM_PX", dest="escala_um_px", type=float, help=tx("Calibração em µm/px (sem ela, resultados em pixels).", "Calibration in µm/px (without it, results in pixels)."))
    parser.add_argument("--element-px", "--elemento-px", metavar="ELEMENT_PX", dest="elemento_px", type=float, default=ELEMENTO_PX,
                        help=tx("Q4: tamanho aproximado do elemento em pixels (padrão 30).", "Q4: approximate element size in pixels (default 30)."))
    parser.add_argument("--control-points", "--pontos-controle", dest="pontos_controle", type=int, nargs=2, default=[10, 8], metavar=("NX", "NY"),
                        help=tx("B-spline: pontos de controle em x e y (padrão 10 8).", "B-spline: control points in x and y (default 10 8)."))
    parser.add_argument("--limit", "--limite", metavar="LIMIT", dest="limite", type=int, help=tx("Limita o número de quadros para diagnóstico.", "Limit the number of frames (diagnostics)."))
    parser.add_argument("--roi", type=float, nargs=4, metavar=("X1", "Y1", "X2", "Y2"),
                        help=tx("ROI em px, origem no canto inferior esquerdo. Sem ela, é detectada automaticamente.", "ROI in px, origin at the lower-left corner. Detected automatically if omitted."))
    parser.add_argument("--every", "--a-cada", metavar="EVERY", dest="a_cada", type=int, default=1, help=tx("Usa uma imagem a cada N.", "Use one image every N."))
    parser.add_argument("--first", "--inicio", metavar="FIRST", dest="inicio", type=int, default=1, help=tx("Primeira imagem usada (1 = primeira).", "First image used (1 = first)."))
    parser.add_argument("--last", "--fim", metavar="LAST", dest="fim", type=int, help=tx("Última imagem usada.", "Last image used."))
    parser.add_argument("--reference-every", "--passo-referencia", metavar="REFERENCE_EVERY", dest="passo_referencia", type=int, default=2,
                        help=tx("Atualiza a referência a cada N quadros (padrão 2).", "Update the reference every N frames (default 2)."))
    args = parser.parse_args(argv)
    args.calibrado = args.escala_um_px is not None
    if not args.calibrado:
        args.escala_um_px = 1.0
    if args.limite is not None and args.limite < 2:
        parser.error("--limite deve ser maior ou igual a 2")
    if args.passo_referencia < 1:
        parser.error("--passo-referencia deve ser positivo")
    if args.elemento_px < 8:
        parser.error("--elemento-px deve ser pelo menos 8")
    if min(args.pontos_controle) < 4:
        parser.error("--pontos-controle precisa de pelo menos 4 em cada direção (grau 3)")
    if args.escala_um_px <= 0:
        parser.error("--escala-um-px deve ser positiva")
    if not args.roi:
        from .auto import sugerir
        args.roi = sugerir(args.imagens, args.inicio, args.fim, args.a_cada)["roi"]
    if args.roi:
        ROI.update(Xc1=float(args.roi[0]), Yc1=float(args.roi[1]), Xc2=float(args.roi[2]), Yc2=float(args.roi[3]))
    args.saida.mkdir(parents=True, exist_ok=False)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(args.saida / "analise.log", encoding="utf-8")],
        force=True,
    )
    correlacionar(args)


if __name__ == "__main__":
    main()

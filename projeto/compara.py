"""
Compara SIMULAÇÃO x BANCADA para um ensaio gravado pela interface.

Uso:  python compara.py ../dados/resultado_m1.csv  [mais arquivos ...]

O modo (m1..m4) é lido do próprio CSV; a referência usada na simulação é
exatamente a que foi gravada, então as curvas ficam diretamente comparáveis.
Os ganhos abaixo devem ser OS MESMOS que estavam na bancada no ensaio
(são os padrões do firmware; se você trocou, troque aqui também).
"""
import os
import sys
import numpy as np
import matplotlib.pyplot as plt
import planta as P
from planta import carrega

# ---------- ganhos que estavam na bancada ----------
CV = ([0.010070, -0.003592, 0], [1, -1.0, 0])         # cv b0,b1,b2,a1,a2
CP = ([0.897000, -0.319938, 0], [1, 0.0, 0])          # cp
EV = (0.006694, 0.295139, 0.0)                         # ev k1,ki,nv
EP = (0.649990, 0.009648, 2.057970)                    # ep k1,k2,ki
ZM, ZS, BANDA = 3.0, 4.0, 0.10


class EEVel:
    def __init__(s): s.xi = 0
    def __call__(s, k, r, w, th):
        k1, ki, nv = EV
        e = r - w
        v = -k1 * w + ki * s.xi + nv * r
        vs = float(np.clip(v, -12, 12))
        if vs == v or (v > 0) != (e > 0):
            s.xi += P.TS * e
        return vs


class EEPos:
    def __init__(s): s.xi = 0
    def __call__(s, k, r, w, th):
        k1, k2, ki = EP
        e = r - th
        if abs(e) <= BANDA:
            return 0.0
        v = k1 * e - k2 * w + ki * s.xi
        vs = float(np.clip(v, -12, 12))
        if vs == v or (v > 0) != (e > 0):
            s.xi += P.TS * e
        return vs


class LGRPos(P.ControladorZ):
    def __call__(s, k, r, w, th):
        v = super().__call__(k, r, w, th)
        if abs(r - th) <= BANDA:
            s.u[0] = 0
            return 0.0
        return v


NOMES = {1: "m1 velocidade LGR", 2: "m2 posição LGR", 3: "m3 velocidade EE", 4: "m4 posição EE"}

arqs = sys.argv[1:] or [os.path.join(os.path.dirname(__file__), "..", "dados", f"resultado_m{i}.csv")
                        for i in (1, 2, 3, 4)]
fig, axs = plt.subplots(len(arqs), 1, figsize=(10, 3 * len(arqs)), squeeze=False)
for ax, arq in zip(axs[:, 0], arqs):
    d = carrega(arq)
    modo = int(d["modo"][-1])
    ctrl = {1: lambda: P.ControladorZ(*CV, usa="w"), 2: lambda: LGRPos(*CP, usa="th"),
            3: EEVel, 4: EEPos}[modo]()
    r = d["r"]
    sim = P.simula(ctrl, lambda t: r[min(int(round(t / P.TS)), len(r) - 1)],
                   T=len(r) * P.TS, comp_zm=ZM, comp_zs=ZS)
    y = "w" if modo in (1, 3) else "th"
    ax.plot(d["t"], r, "k--", lw=1, label="referência")
    ax.plot(d["t"], d[y], lw=1.6, label="bancada")
    ax.plot(sim["t"], sim[y], lw=1.2, alpha=.8, label="simulação")
    ax.set_ylabel("ω [rad/s]" if y == "w" else "θ [rad]")
    ax.set_title(NOMES.get(modo, f"modo {modo}")); ax.grid(alpha=.3); ax.legend(loc="lower right", fontsize=8)
axs[-1, 0].set_xlabel("t [s]")
fig.tight_layout()
nome = "comparacao_bancada.png" if not sys.argv[1:] else \
    "comparacao_" + "_".join(os.path.splitext(os.path.basename(a))[0] for a in arqs) + ".png"
saida = os.path.join(os.path.dirname(__file__), "..", "docs", "figuras", nome)
fig.savefig(saida, dpi=110)
print("figura salva em", os.path.normpath(saida))
if os.environ.get("SEM_JANELA") is None:
    plt.show()

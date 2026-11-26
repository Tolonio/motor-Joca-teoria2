"""
Gera as figuras do guia dos modos (README.md): para cada modo, "como deveria ficar" (simulação
com o modelo não linear da planta) x "como fica" (ensaio real gravado na bancada).

Uso:  python figuras_modos.py        (salva docs/figuras/modo_m0.png ... modo_m4.png)
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import planta as P
from compara import CV, CP, ZM, ZS, EEVel, EEPos, LGRPos

AQUI = os.path.dirname(os.path.abspath(__file__))
DADOS = os.path.join(AQUI, "..", "dados")
FIG = os.path.join(AQUI, "..", "docs", "figuras")

COR_REF, COR_BANCADA, COR_SIM, COR_U = "0.25", "#2a78d6", "#eb6834", "#1baf7a"


def trecho(arq, t0, t1):
    d = P.carrega(os.path.join(DADOS, arq))
    s = (d["t"] >= t0) & (d["t"] <= t1)
    return {k: (v[s] - t0 if k == "t" else v[s]) for k, v in d.items()}


def simula_igual(d, ctrl, comp=True):
    """Simula com a MESMA referência gravada no ensaio."""
    r = d["r"]
    return P.simula(ctrl, lambda t: r[min(int(round(t / P.TS)), len(r) - 1)], T=len(r) * P.TS,
                    comp_zm=ZM if comp else 0.0, comp_zs=ZS if comp else 0.0)


def figura(nome, titulo, d, sim, y, ylab):
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 5.6), sharex=True,
                                 gridspec_kw={"height_ratios": [3, 2]})
    a1.plot(d["t"], d["r"], "--", color=COR_REF, lw=1.2, label="referência (pedido)")
    a1.plot(sim["t"], sim[y], color=COR_SIM, lw=1.4, label="simulação (como deveria ficar)")
    a1.plot(d["t"], d[y], color=COR_BANCADA, lw=1.8, label="bancada (como fica)")
    a1.set_ylabel(ylab); a1.set_title(titulo); a1.legend(loc="best", fontsize=8)
    a2.plot(sim["t"], sim["u"], color=COR_SIM, lw=1.2, label="u simulado")
    a2.plot(d["t"], d["u"], color=COR_U, lw=1.6, label="u na bancada")
    a2.set_ylabel("u [V]"); a2.set_xlabel("t [s]"); a2.legend(loc="best", fontsize=8)
    for a in (a1, a2):
        a.grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, nome), dpi=110)
    plt.close(fig)
    print("salvo", nome)


def figura_m0():
    # velocidade em regime para cada tensão (ensaios de degrau em malha aberta)
    pts = [(0.0, 0.0)]
    for v in (3, 4, 5, 6, 7.5, 9, 12, -6, -9):
        d = P.carrega(os.path.join(DADOS, f"degrau_malha_aberta_{v}.csv"))
        on = np.isclose(d["u"], v)
        ok = [i for i in np.where(on)[0] if i >= 15 and on[i - 15:i + 1].all()]   # ≥ 0,3 s no patamar
        pts.append((v, float(np.mean(d["w"][ok]))))
    pts = np.array(sorted(pts))
    uu = np.linspace(-12, 12, 400)
    teo = np.where(np.abs(uu) > P.V0, P.K * (uu - np.sign(uu) * P.V0), 0)

    d = trecho("degrau_malha_aberta_6.csv", 0.9, 3.2)
    sim = P.simula(lambda k, r, w, th: r, lambda t: d["r"][min(int(round(t / P.TS)), len(d["r"]) - 1)],
                   T=len(d["r"]) * P.TS)

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.2))
    a1.axvspan(-P.V0, P.V0, color="#e34948", alpha=.12, label=f"zona morta (±{P.V0:.1f} V)")
    a1.plot(uu, teo, color=COR_SIM, lw=1.4, label=f"modelo: ω = {P.K:.1f}·(u − {P.V0:.2f})")
    a1.plot(pts[:, 0], pts[:, 1], "o", color=COR_BANCADA, ms=7, label="bancada")
    a1.set_xlabel("tensão u [V]"); a1.set_ylabel("velocidade em regime ω [rad/s]")
    a1.set_title("m0: velocidade final x tensão"); a1.legend(fontsize=8); a1.grid(alpha=.3)
    a2.plot(d["t"], d["r"] * 20, "--", color=COR_REF, lw=1.2, label="u = referência (×20)")
    a2.plot(sim["t"], sim["w"], color=COR_SIM, lw=1.4, label="simulação")
    a2.plot(d["t"], d["w"], color=COR_BANCADA, lw=1.8, label="bancada")
    a2.set_xlabel("t [s]"); a2.set_ylabel("ω [rad/s]"); a2.set_title("m0: degraus 0 → 6 V")
    a2.legend(fontsize=8); a2.grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "modo_m0.png"), dpi=110)
    plt.close(fig)
    print("salvo modo_m0.png")


if __name__ == "__main__":
    figura_m0()
    d = trecho("resultado_m1.csv", 0.1, 3.2)
    figura("modo_m1.png", "m1: velocidade, LGR (PI) | onda quadrada 100 ↔ 250 rad/s",
           d, simula_igual(d, P.ControladorZ(*CV, usa="w")), "w", "ω [rad/s]")
    d = trecho("resultado_m2_longo.csv", 0.1, 10.3)
    figura("modo_m2.png", "m2: posição, LGR (avanço) | onda quadrada ±π/2 rad",
           d, simula_igual(d, LGRPos(*CP, usa="th")), "th", "θ [rad]")
    d = trecho("resultado_m3.csv", 0.1, 3.2)
    figura("modo_m3.png", "m3: velocidade, espaço de estados | onda quadrada 100 ↔ 250 rad/s",
           d, simula_igual(d, EEVel()), "w", "ω [rad/s]")
    d = trecho("resultado_m4_longo.csv", 0.1, 10.3)
    figura("modo_m4.png", "m4: posição, espaço de estados | onda quadrada ±π/2 rad",
           d, simula_igual(d, EEPos()), "th", "θ [rad]")

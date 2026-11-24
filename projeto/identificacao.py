"""
Identificação da planta a partir de ensaios em MALHA ABERTA (modo m0).

Como gerar os dados (pela interface ou pelo monitor serial):
    m0                 (malha aberta: u = referência em volts)
    q0,6,1000          (onda quadrada 0 V <-> 6 V, 1 s em cada nível)
  grave uns 4 s e salve como  dados/degrau_malha_aberta_6.csv
  Repita para vários níveis (4, 5, 6, 7.5, 9, 12, -6, -9 ...).

O que este script faz:
  1. Para cada nível V, mede a velocidade de regime ω_ss.
  2. Ajusta uma reta ω_ss = K (|V| - V0): K é o ganho e V0 a zona morta
     causada pelo atrito seco (abaixo de V0 o motor não gira).
  3. Ajusta a constante de tempo TAU comparando o degrau medido com o
     modelo K/(TAU s + 1) simulado COM a mesma forma de medida do firmware
     (velocidade = média no intervalo de 20 ms). Sem isso o ajuste "vê"
     um atraso falso de ~1,5 amostra.

Execute:  python identificacao.py [pasta_dos_csv]
Copie K, TAU e V0 impressos para planta.py.
"""
import glob
import os
import sys
import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import least_squares
from planta import carrega

TS = 0.02
PASTA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "dados")
FIG = os.path.join(os.path.dirname(__file__), "..", "docs", "figuras")


def degraus(d, V):
    """Trechos de 8 amostras logo após cada subida 0 -> V da tensão."""
    u, w = d["u"], d["w"]
    out = []
    for i in np.where((np.abs(u[1:] - V) < 1e-3) & (np.abs(u[:-1]) < 1e-3))[0] + 1:
        if i + 9 < len(w):
            out.append(w[i + 1:i + 9])       # w[i+1] = média no 1º intervalo com u = V
    return out


def simula_degrau(K, tau, Vef, n=8, sub=200):
    dt = TS / sub
    w = th = 0.0
    ths = [0.0]
    for j in range(n * sub):
        w += dt * (K * Vef - w) / tau
        th += dt * w
        if (j + 1) % sub == 0:
            ths.append(th)
    return np.diff(ths) / TS


arquivos = sorted(glob.glob(os.path.join(PASTA, "degrau_malha_aberta_*.csv")))
if not arquivos:
    sys.exit("Nenhum arquivo degrau_malha_aberta_*.csv em " + PASTA)

niveis, wss, trechos = [], [], []
for arq in arquivos:
    d = carrega(arq)
    V = float(os.path.basename(arq)[len("degrau_malha_aberta_"):-4])
    alto = np.abs(d["u"] - V) < 1e-3
    # regime = últimas 15 amostras de cada patamar alto
    idx = np.where(alto)[0]
    blocos = np.split(idx, np.where(np.diff(idx) > 1)[0] + 1)
    reg = np.mean([d["w"][b[-15:]].mean() for b in blocos if len(b) > 20])
    niveis.append(V); wss.append(reg)
    trechos += [(V, t) for t in degraus(d, V)]
    print(f"V = {V:6.2f} V   ω_ss = {reg:8.2f} rad/s")

niveis, wss = np.array(niveis), np.array(wss)
gira = np.abs(wss) > 5
A = np.c_[np.abs(niveis[gira]), np.ones(gira.sum())]
K, b = np.linalg.lstsq(A, np.abs(wss[gira]), rcond=None)[0]
V0 = -b / K
print(f"\nGanho K = {K:.3f} rad/s/V    zona morta V0 = {V0:.3f} V")

uteis = [(V, t) for V, t in trechos if abs(V) > V0 + 0.8]
res = least_squares(
    lambda p: np.concatenate([(simula_degrau(K, p[0], np.sign(V) * (abs(V) - V0)) - t) / abs(V)
                              for V, t in uteis]), [0.03], bounds=([0.002], [0.5]))
TAU = res.x[0]
print(f"Constante de tempo TAU = {TAU * 1000:.1f} ms")
print(f"\n=> W(s)/U(s) = {K:.2f} / ({TAU:.4f} s + 1)   (copie para planta.py)")

os.makedirs(FIG, exist_ok=True)
fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
vv = np.linspace(-12, 12, 200)
ax[0].plot(niveis, wss, "o", label="medido")
ax[0].plot(vv, np.sign(vv) * K * np.maximum(np.abs(vv) - V0, 0), label=f"K={K:.1f}, V0={V0:.2f} V")
ax[0].set_xlabel("u [V]"); ax[0].set_ylabel("ω regime [rad/s]"); ax[0].grid(alpha=.3); ax[0].legend()
ax[0].set_title("Ganho estático e zona morta")
for V, t in uteis[::2]:
    k = np.arange(1, 9) * TS
    l, = ax[1].plot(k, t, "o", ms=4)
    ax[1].plot(k, simula_degrau(K, TAU, np.sign(V) * (abs(V) - V0)), "-", c=l.get_color())
ax[1].set_xlabel("tempo após o degrau [s]"); ax[1].set_ylabel("ω medida [rad/s]")
ax[1].set_title(f"Degraus: pontos = bancada, linhas = modelo (τ = {TAU*1000:.1f} ms)")
ax[1].grid(alpha=.3)
fig.tight_layout(); fig.savefig(os.path.join(FIG, "identificacao.png"), dpi=120)
if os.environ.get("SEM_JANELA") is None:
    plt.show()

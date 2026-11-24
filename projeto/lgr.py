"""
ETAPA 1 - Projeto por Lugar Geométrico das Raízes (LGR) no plano z.

Por que no plano z e não em s?
  A constante de tempo do motor (TAU ≈ 19 ms) é praticamente igual ao período
  de amostragem (Ts = 20 ms). Projetar em s e depois discretizar (Tustin,
  emulação) só funciona bem quando Ts é ~10x menor que a dinâmica. Aqui não
  é, então discretizamos a PLANTA (ZOH, exato) e fazemos o LGR direto em z.

Execute:  python lgr.py
Gera as figuras em ../docs/figuras/ e imprime os comandos para a serial.
"""
import os
import numpy as np
import matplotlib.pyplot as plt
import planta as P

FIG = os.path.join(os.path.dirname(__file__), "..", "docs", "figuras")
os.makedirs(FIG, exist_ok=True)

# ===================== Especificações (mude aqui) =====================
VEL_POLO_DOMINANTE = 0.62      # polo real dominante desejado da malha de velocidade
POS_ZETA = 0.70                # amortecimento desejado da malha de posição
POS_POLO_AVANCO = 0.0          # polo do compensador de avanço (z = p)
ZM = 3.0                       # compensação de atrito com o motor girando (comando zm)
ZS = 4.0                       # compensação com o motor parado (comando zs)
BANDA = 0.10                   # banda morta do erro de posição (comando bp)


def lgr(num_ol, den_ol, ganhos):
    """Polos de malha fechada de 1 + Kc·N(z)/D(z) = 0 para cada Kc."""
    return np.array([np.roots(np.polyadd(den_ol, k * np.asarray(num_ol))) for k in ganhos])


def zeta_de(p):
    s = np.log(np.asarray(p, dtype=complex)) / P.TS
    return -s.real / np.maximum(np.abs(s), 1e-12)


def grade_z(ax):
    th = np.linspace(0, 2 * np.pi, 400)
    ax.plot(np.cos(th), np.sin(th), "k", lw=0.8)
    for z in (0.3, 0.5, 0.7, 0.9):       # curvas de amortecimento constante
        wn = np.linspace(0, np.pi / P.TS, 200)
        s = -z * wn + 1j * wn * np.sqrt(1 - z ** 2)
        zz = np.exp(s * P.TS)
        ax.plot(zz.real, zz.imag, ":", c="gray", lw=0.7)
        ax.plot(zz.real, -zz.imag, ":", c="gray", lw=0.7)
        ax.text(zz.real[60], zz.imag[60], f"ζ={z}", fontsize=7, color="gray")
    ax.axhline(0, c="k", lw=0.4); ax.axvline(0, c="k", lw=0.4)
    ax.set_aspect("equal"); ax.set_xlim(-1.1, 1.1); ax.set_ylim(-1.1, 1.1)
    ax.set_xlabel("Re(z)"); ax.set_ylabel("Im(z)")


def desenha_lgr(ax, num_ol, den_ol, kmax, k_escolhido, titulo):
    ks = np.concatenate([np.linspace(0, kmax, 3000)])
    raizes = lgr(num_ol, den_ol, ks)
    grade_z(ax)
    ax.plot(raizes.real, raizes.imag, ".", ms=1.2, c="C0")
    ax.plot(np.roots(den_ol).real, np.roots(den_ol).imag, "x", ms=9, mew=2, c="k", label="polos MA")
    zs = np.roots(num_ol)
    ax.plot(zs.real, zs.imag, "o", ms=8, mfc="none", mew=2, c="k", label="zeros MA")
    pf = np.roots(np.polyadd(den_ol, k_escolhido * np.asarray(num_ol)))
    ax.plot(pf.real, pf.imag, "s", c="C3", ms=7, label=f"Kc = {k_escolhido:.4g}")
    ax.set_title(titulo); ax.legend(fontsize=8, loc="lower left")
    return pf


# ============================ VELOCIDADE ============================
num_w, den_w = P.tf_velocidade_z()
a = np.exp(-P.TS / P.TAU)
print("Planta de velocidade  Gw(z) = (%.4f z + %.4f) / (z (z - %.4f))" % (num_w[0], num_w[1], a))

# PI discreto: C(z) = Kc (z - a) / (z - 1). O zero cancela o polo da planta em z = a,
# o integrador (z = 1) zera o erro em regime para degrau.
num_ol = np.polymul([1, -a], num_w)
den_ol = np.polymul([1, -1], den_w)
ks = np.linspace(1e-5, 0.03, 30000)
r = lgr(num_ol, den_ol, ks)
dom = np.max(np.abs(r), axis=1)
Kc_v = ks[np.argmin(np.abs(dom - VEL_POLO_DOMINANTE))]
b_v, a_v = [Kc_v, -Kc_v * a], [1, -1]

fig, ax = plt.subplots(1, 2, figsize=(11, 5))
pf = desenha_lgr(ax[0], num_ol, den_ol, 0.03, Kc_v, "LGR - velocidade com PI")
print("Velocidade: Kc = %.5f  polos MF = %s" % (Kc_v, np.round(pf, 3)))

sim = P.simula(P.ControladorZ(b_v, a_v, "w"), P.quadrada(100, 250, 0.5), T=2.0, comp_zm=ZM, comp_zs=ZS)
ax[1].plot(sim["t"], sim["r"], "k--", label="referência")
ax[1].plot(sim["t"], sim["w"], label="ω simulada (não linear)")
ax[1].set_xlabel("t [s]"); ax[1].set_ylabel("ω [rad/s]"); ax[1].grid(alpha=.3); ax[1].legend()
ax2 = ax[1].twinx(); ax2.plot(sim["t"], sim["u"], c="C2", alpha=.5); ax2.set_ylabel("u [V]", color="C2")
fig.tight_layout(); fig.savefig(os.path.join(FIG, "lgr_velocidade.png"), dpi=120)

# ============================ POSIÇÃO ============================
num_t, den_t = P.tf_posicao_z()
print("Planta de posição  Gθ(z) = (%.4f z + %.4f) / ((z - 1)(z - %.4f))" % (num_t[0], num_t[1], a))

# Avanço de fase: C(z) = Kc (z - a) / (z - p). O zero cancela o polo lento da
# planta e o polo p (mais rápido) o substitui -> resposta mais rápida.
# A planta já tem integrador (polo em z = 1), então o erro a degrau é zero.
p = POS_POLO_AVANCO
num_ol = np.polymul([1, -a], num_t)
den_ol = np.polymul([1, -p], den_t)
ks = np.linspace(1e-4, 4, 40000)
r = lgr(num_ol, den_ol, ks)
zmin = np.array([np.min(zeta_de(x[np.abs(x - a) > 1e-3])) for x in r])
Kc_p = ks[np.argmin(np.abs(zmin - POS_ZETA))]
b_p, a_p = [Kc_p, -Kc_p * a], [1, -p]

fig, ax = plt.subplots(1, 2, figsize=(11, 5))
pf = desenha_lgr(ax[0], num_ol, den_ol, 4, Kc_p, "LGR - posição com avanço")
print("Posição: Kc = %.5f  polos MF = %s" % (Kc_p, np.round(pf, 3)))

class LGRPos(P.ControladorZ):          # com a banda morta de erro, igual ao firmware
    def __call__(s, k, r, w, th):
        v = super().__call__(k, r, w, th)
        if abs(r - th) <= BANDA:
            s.u[0] = 0
            return 0.0
        return v


sim = P.simula(LGRPos(b_p, a_p, "th"), P.quadrada(0, np.pi, 1.0), T=3.0, comp_zm=ZM, comp_zs=ZS)
ax[1].plot(sim["t"], sim["r"], "k--", label="referência")
ax[1].plot(sim["t"], sim["th"], label="θ simulada (não linear)")
ax[1].set_xlabel("t [s]"); ax[1].set_ylabel("θ [rad]"); ax[1].grid(alpha=.3); ax[1].legend()
ax2 = ax[1].twinx(); ax2.plot(sim["t"], sim["u"], c="C2", alpha=.5); ax2.set_ylabel("u [V]", color="C2")
fig.tight_layout(); fig.savefig(os.path.join(FIG, "lgr_posicao.png"), dpi=120)

print("\nComandos para a bancada (cole na interface ou no monitor serial):")
print("  cv " + P.comando_cz(b_v, a_v))
print("  cp " + P.comando_cz(b_p, a_p))
print("  zm %.2f" % ZM)
print("  zs %.2f" % ZS)
print("  bp %.2f" % BANDA)

if __name__ == "__main__" and os.environ.get("SEM_JANELA") is None:
    plt.show()

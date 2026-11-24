"""
ETAPA 2 - Projeto em Espaço de Estados (alocação de polos no plano z).

Velocidade:  estado x = ω,       + integrador xi do erro (r - ω)
             u = -k1·ω + ki·xi (+ nv·r, pré-alimentação opcional)
Posição:     estado x = [θ, ω],  + integrador xi do erro (r - θ)
             u = k1·(r - θ) - k2·ω + ki·xi
             ω (e θ) podem vir de um OBSERVADOR de estados (oe 1), que
             estima ω a partir de θ e de u, com bem menos ruído que (θ[k]-θ[k-1])/Ts.

O integrador é o que elimina o erro em regime causado pelo atrito seco e
por erros de modelo. Os ganhos saem pela fórmula de Ackermann aplicada ao
sistema AUMENTADO (planta + integrador).

Execute:  python espaco_estados.py
"""
import os
import numpy as np
import matplotlib.pyplot as plt
import planta as P

FIG = os.path.join(os.path.dirname(__file__), "..", "docs", "figuras")
os.makedirs(FIG, exist_ok=True)

# ===================== Especificações (mude aqui) =====================
# Polos desejados em s (contínuo) -> mapeados para z = e^(s·Ts)
VEL_POLOS_S = [-25.0, -30.0]                 # velocidade: 2 polos reais (ω e integrador)
POS_ZETA, POS_WN = 0.90, 40.0                # posição: par dominante
POS_POLO_INTEGRADOR_S = -4.0                 # 3º polo (integrador): lento de propósito,
                                             # integrador rápido + atrito estático = stick-slip
OBS_POLOS_Z = [0.25, 0.30]                   # observador: bem mais rápido que a malha
ZM = 3.0                                     # compensação de atrito girando (comando zm)
ZS = 4.0                                     # compensação de atrito parado  (comando zs)
BANDA = 0.10                                 # banda morta do erro de posição (comando bp)


def ackermann(A, B, polos_z):
    """Ganho K tal que eig(A - B K) = polos_z (sistema de 1 entrada)."""
    n = A.shape[0]
    B = B.reshape(n, 1)
    Wc = np.hstack([np.linalg.matrix_power(A, i) @ B for i in range(n)])
    if abs(np.linalg.det(Wc)) < 1e-12:
        raise ValueError("sistema não controlável")
    coef = np.real(np.poly(polos_z))
    phiA = sum(c * np.linalg.matrix_power(A, n - i) for i, c in enumerate(coef))
    en = np.zeros((1, n)); en[0, -1] = 1
    return (en @ np.linalg.inv(Wc) @ phiA).ravel()


Phi, Gam = P.modelo_discreto()
a, bw = Phi[1, 1], Gam[1]
Ts = P.TS

# ============================ VELOCIDADE ============================
# ω[k+1] = a ω[k] + bw u[k]      xi[k+1] = xi[k] + Ts (r - ω[k])
A = np.array([[a, 0.0], [-Ts, 1.0]])
B = np.array([bw, 0.0])
pz = np.exp(np.array(VEL_POLOS_S) * Ts)
Kaug = ackermann(A, B, pz)          # u = -Kaug·[ω, xi]
k1_v, ki_v = Kaug[0], -Kaug[1]
print("Velocidade: polos z =", np.round(pz, 4), " k1 = %.6f  ki = %.6f" % (k1_v, ki_v))
print("  verificação eig(A-BK) =", np.round(np.linalg.eigvals(A - np.outer(B, Kaug)), 4))


class SSVel:
    def __init__(s): s.xi = 0
    def __call__(s, k, r, w, th):
        e = r - w
        v = -k1_v * w + ki_v * s.xi
        vs = float(np.clip(v, -P.V_MAX, P.V_MAX))
        if vs == v or (v > 0) != (e > 0):
            s.xi += Ts * e
        return vs


# ============================ POSIÇÃO ============================
# x = [θ, ω, xi]
A = np.zeros((3, 3)); A[:2, :2] = Phi; A[2, 0] = -Ts; A[2, 2] = 1
B = np.array([Gam[0], Gam[1], 0.0])
wd = POS_WN * np.sqrt(1 - POS_ZETA ** 2)
ps = [-POS_ZETA * POS_WN + 1j * wd, -POS_ZETA * POS_WN - 1j * wd, POS_POLO_INTEGRADOR_S]
pz = np.exp(np.array(ps) * Ts)
Kaug = ackermann(A, B, pz)
k1_p, k2_p, ki_p = Kaug[0], Kaug[1], -Kaug[2]
print("Posição: polos z =", np.round(pz, 4))
print("  k1 = %.6f  k2 = %.6f  ki = %.6f" % (k1_p, k2_p, ki_p))
print("  verificação eig(A-BK) =", np.round(np.linalg.eigvals(A - np.outer(B, Kaug)), 4))

# Observador preditor:  x^[k+1] = Φ x^ + Γ u + L (θ - θ^)
# Polos de (Φ - L C) por dualidade: L = ackermann(Φ', C', polos)'
C = np.array([[1.0, 0.0]])
L = ackermann(Phi.T, C.T, OBS_POLOS_Z)
print("Observador: polos z =", OBS_POLOS_Z, " L1 = %.6f  L2 = %.6f" % (L[0], L[1]))


class SSPos:
    def __init__(s, obs=True):
        s.xi = 0; s.obs = obs; s.xh = np.zeros(2)
    def __call__(s, k, r, w, th):
        thu, wu = (s.xh if s.obs else (th, w))
        e = r - th
        if abs(e) <= BANDA:                       # igual ao firmware
            s.xh = Phi @ s.xh + L * (th - s.xh[0])
            return 0.0
        v = k1_p * (r - thu) - k2_p * wu + ki_p * s.xi
        vs = float(np.clip(v, -P.V_MAX, P.V_MAX))
        if vs == v or (v > 0) != (e > 0):
            s.xi += Ts * e
        # O observador usa o u "linear" (antes da compensação de zona morta),
        # pois a compensação existe para cancelar o atrito: igual ao firmware.
        s.xh = Phi @ s.xh + Gam * vs + L * (th - s.xh[0])
        return vs


# ============================ Simulações ============================
fig, ax = plt.subplots(2, 1, figsize=(10, 7))
sim = P.simula(SSVel(), P.quadrada(100, 250, 0.5), T=2.0, comp_zm=ZM, comp_zs=ZS)
ax[0].plot(sim["t"], sim["r"], "k--", label="referência")
ax[0].plot(sim["t"], sim["w"], label="ω simulada")
ax[0].set_ylabel("ω [rad/s]"); ax[0].legend(); ax[0].grid(alpha=.3)
ax[0].set_title("Espaço de estados - velocidade")
ax2 = ax[0].twinx(); ax2.plot(sim["t"], sim["u"], c="C2", alpha=.5); ax2.set_ylabel("u [V]", color="C2")

for obs, cor in ((True, "C0"), (False, "C1")):
    sim = P.simula(SSPos(obs), P.quadrada(0, np.pi, 1.0), T=3.0, comp_zm=ZM, comp_zs=ZS)
    ax[1].plot(sim["t"], sim["th"], c=cor, label="θ " + ("com observador" if obs else "ω por diferença"))
ax[1].plot(sim["t"], sim["r"], "k--", label="referência")
ax[1].set_ylabel("θ [rad]"); ax[1].set_xlabel("t [s]"); ax[1].legend(); ax[1].grid(alpha=.3)
ax[1].set_title("Espaço de estados - posição")
fig.tight_layout(); fig.savefig(os.path.join(FIG, "ee_simulacao.png"), dpi=120)

print("\nComandos para a bancada:")
print("  ev %.6f,%.6f,0" % (k1_v, ki_v))
print("  ep %.6f,%.6f,%.6f" % (k1_p, k2_p, ki_p))
print("  ob %.6f,%.6f" % (L[0], L[1]))
print("  pl %.4f,%.5f" % (P.K, P.TAU))
print("  zm %.2f" % ZM)
print("  zs %.2f" % ZS)
print("  bp %.2f" % BANDA)
print("  oe 0      (observador: oe 1 liga; veja docs/03-espaco-de-estados.md)")

if __name__ == "__main__" and os.environ.get("SEM_JANELA") is None:
    plt.show()

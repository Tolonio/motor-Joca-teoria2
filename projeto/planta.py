"""
Modelo da planta (motor DC da bancada) e simulador não linear.

Todos os outros scripts importam daqui, então se você reidentificar a
planta (identificacao.py) basta trocar K, TAU e V0 abaixo.

Modelo linear (velocidade):      W(s)/U(s) = K / (TAU s + 1)      [rad/s / V]
Modelo linear (posição):         Θ(s)/U(s) = K / (s (TAU s + 1))  [rad / V]
Não linearidades reais incluídas na simulação:
  - atrito seco (Coulomb, V0 volts) e estático (VS volts para sair do repouso)
  - saturação da tensão em ±12 V
  - encoder com 128 contagens/volta (quantização)
  - a velocidade é medida como (θ[k] - θ[k-1]) / Ts  (média no intervalo)
"""
import numpy as np

# ---------------- Parâmetros identificados (bancada nº 5, 2026-11-24) ----------------
K = 46.75        # ganho estático incremental  [rad/s por V]
TAU = 0.0194     # constante de tempo mecânica [s]
V0 = 2.94        # atrito seco (Coulomb) com o motor girando [V]
VS = 3.6         # atrito estático: tensão para TIRAR o motor do repouso [V]
                 # (estimado comparando compara.py com a bancada; varia com o ângulo)

TS = 0.02        # período de amostragem do firmware [s]
V_MAX = 12.0     # saturação
CPR = 128        # contagens por volta (encoder 32 pulsos x 4 bordas)
RAD_POR_CONT = 2 * np.pi / CPR


def modelo_discreto(K=K, tau=TAU, Ts=TS):
    """Discretização exata (ZOH) de x = [θ, ω]:  x[k+1] = Φ x[k] + Γ u[k]."""
    a = np.exp(-Ts / tau)
    Phi = np.array([[1.0, tau * (1 - a)],
                    [0.0, a]])
    Gam = np.array([K * (Ts - tau * (1 - a)),
                    K * (1 - a)])
    return Phi, Gam


def tf_posicao_z(K=K, tau=TAU, Ts=TS):
    """Θ(z)/U(z) com ZOH. Retorna (num, den) em potências decrescentes de z."""
    Phi, Gam = modelo_discreto(K, tau, Ts)
    a = Phi[1, 1]
    # C (zI-Φ)^-1 Γ, C = [1 0]
    b1 = Gam[0]
    b0 = Phi[0, 1] * Gam[1] - a * Gam[0]
    num = np.array([b1, b0])
    den = np.array([1.0, -(1 + a), a])      # (z-1)(z-a)
    return num, den


def tf_velocidade_z(K=K, tau=TAU, Ts=TS):
    """W_medida(z)/U(z), com W_medida = (1 - z^-1)/Ts · Θ(z).

    O polo em z=1 de Θ(z) cancela com o zero do derivador e aparece um polo
    em z=0 (o atraso de meia amostra da medida por média)."""
    num, _ = tf_posicao_z(K, tau, Ts)
    a = np.exp(-Ts / tau)
    return num / Ts, np.array([1.0, -a, 0.0])   # z (z - a)


def simula(controle, referencia, T=2.0, Kp=K, tau=TAU, v0=V0, vs=VS, sub=50, comp_zm=0.0, comp_zs=0.0):
    """Simulação não linear da bancada.

    controle(k, r, w_med, th_med) -> u        (chamado a cada Ts, como no firmware)
    referencia(t) -> r
    comp_zm: compensação de atrito com o motor girando (comando zm)
    comp_zs: compensação com o motor parado (comando zs); 0 = usa comp_zm
    Retorna dict com t, r, u, w (medida), th (medida).
    """
    n = int(round(T / TS))
    dt = TS / sub
    w = 0.0
    th = 0.0
    th_ant_med = 0.0
    out = {k: np.zeros(n) for k in ("t", "r", "u", "w", "th")}
    for k in range(n):
        t = k * TS
        th_med = np.round(th / RAD_POR_CONT) * RAD_POR_CONT
        w_med = (th_med - th_ant_med) / TS
        th_ant_med = th_med
        r = referencia(t)
        u = controle(k, r, w_med, th_med)
        u = float(np.clip(u, -V_MAX, V_MAX))
        comp = comp_zs if (w_med == 0 and comp_zs > comp_zm) else comp_zm
        if comp > 0 and abs(u) > 0.05:
            u = float(np.clip(u + np.sign(u) * comp, -V_MAX, V_MAX))
        out["t"][k], out["r"][k], out["u"][k] = t, r, u
        out["w"][k], out["th"][k] = w_med, th_med
        for _ in range(sub):          # integra a planta "contínua"
            if w == 0.0 and abs(u) <= vs:
                continue              # parado e sem torque suficiente: atrito estático segura
            s = np.sign(w) if w != 0.0 else np.sign(u)
            dw = (Kp * (u - v0 * s) - w) / tau
            w_novo = w + dt * dw
            if w != 0.0 and np.sign(w_novo) != np.sign(w) and abs(u) <= v0:
                w_novo = 0.0          # atrito parou o motor
            th += dt * (w + w_novo) / 2
            w = w_novo
    return out


def degrau(valor, t0=0.1):
    return lambda t: valor if t >= t0 else 0.0


def quadrada(a, b, meio):
    return lambda t: b if int(t // meio) % 2 else a


class ControladorZ:
    """Mesma equação a diferenças do firmware (com anti-windup pela saturação)."""

    def __init__(self, b, a, usa="w"):
        self.b = list(b) + [0] * (3 - len(b))
        self.a = list(a) + [0] * (3 - len(a))   # a = [1, a1, a2]
        self.usa = usa
        self.e = [0, 0]
        self.u = [0, 0]

    def __call__(self, k, r, w, th):
        y = w if self.usa == "w" else th
        e = r - y
        b0, b1, b2 = self.b
        _, a1, a2 = self.a
        v = b0 * e + b1 * self.e[0] + b2 * self.e[1] - a1 * self.u[0] - a2 * self.u[1]
        v = float(np.clip(v, -V_MAX, V_MAX))
        self.e = [e, self.e[0]]
        self.u = [v, self.u[0]]
        return v


def comando_cz(b, a):
    """Texto do comando serial para um C(z) (b0,b1,b2 / 1,a1,a2)."""
    b = list(b) + [0] * (3 - len(b))
    a = list(a) + [0] * (3 - len(a))
    return ",".join(f"{x:.6f}" for x in (b[0], b[1], b[2], a[1], a[2]))


def carrega(arq):
    """Lê o CSV da telemetria (ignora cabeçalho e linhas '#')."""
    linhas = []
    for l in open(arq, encoding="utf-8", errors="ignore"):
        p = l.strip().split(",")
        if len(p) == 6:
            try:
                linhas.append([float(x) for x in p])
            except ValueError:
                pass
    d = np.array(linhas)
    return {"t": (d[:, 0] - d[0, 0]) / 1000, "modo": d[:, 1], "r": d[:, 2],
            "u": d[:, 3], "w": d[:, 4], "th": d[:, 5]}

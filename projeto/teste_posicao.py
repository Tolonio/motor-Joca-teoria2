"""
Teste estatístico do controle de posição.

Um único degrau diz pouco nesta bancada, porque o atrito estático varia de 2,4 V a 5,7 V
conforme o ponto. Este script manda N alvos aleatórios (sempre os mesmos, semente fixa) e mede
em cada um:
  - erro final  |r - θ| no fim do patamar
  - tempo de acomodação: a partir de quando |erro| <= TOL até o fim do patamar
  - sobressinal: quanto passou do alvo, em rad

Uso:
  python teste_posicao.py "m4"                       # configuração atual da placa
  python teste_posicao.py "m4;zs 3;zr 30" -n 20      # testando outros parâmetros
  python teste_posicao.py "m2" -o ../dados/pos_m2.csv
"""
import argparse
import numpy as np
from ensaio import Bancada, salva

TOL = 0.15          # rad: considerado "chegou" (≈ 3 contagens do encoder)


def metricas(d, alvos, t_alvo, T):
    t = (d[:, 0] - d[0, 0]) / 1000
    th, r = d[:, 5], d[:, 2]
    res = []
    for k, (alvo, t0) in enumerate(zip(alvos, t_alvo)):
        m = (t >= t0) & (t < t0 + T - 0.02)
        if m.sum() < 10:
            continue
        tt, y = t[m] - t0, th[m]
        ini = th[np.searchsorted(t, t0) - 1] if np.searchsorted(t, t0) > 0 else 0.0
        e = alvo - y
        fora = np.where(np.abs(e) > TOL)[0]
        ts = 0.0 if len(fora) == 0 else (tt[fora[-1]] + 0.02 if fora[-1] < len(tt) - 1 else np.nan)
        sentido = np.sign(alvo - ini)
        sob = max(0.0, np.max(sentido * (y - alvo))) if sentido != 0 else 0.0
        res.append((abs(e[-1]), ts, sob, abs(alvo - ini)))
    return np.array(res)


def roda(cmds, n=15, T=1.5, porta="/dev/ttyACM1", semente=1, saida=None):
    rng = np.random.default_rng(semente)
    alvos = []
    atual = 0.0
    for _ in range(n):                     # degraus de 0,3 a 3 rad, para os dois lados
        passo = rng.uniform(0.3, 3.0) * rng.choice([-1, 1])
        atual = float(np.clip(atual + passo, -6, 6))
        alvos.append(atual)
    b = Bancada(porta)
    dados, t_alvo = [], []
    try:
        b.envia("z", cmds, "r0")
        dados.append(b.coleta(0.5))
        t_ini = dados[0][0, 0] / 1000 if len(dados[0]) else 0
        for a in alvos:
            b.envia(f"r{a:.4f}")
            bloco = b.coleta(T)
            if len(bloco):
                t_alvo.append(bloco[0, 0] / 1000 - t_ini)
            dados.append(bloco)
    finally:
        b.fecha()
    d = np.vstack([x for x in dados if len(x)])
    if saida:
        salva(d, saida)
    return metricas(d, alvos, t_alvo, T), d


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("comandos")
    ap.add_argument("-n", type=int, default=15)
    ap.add_argument("-T", type=float, default=1.5, help="segundos em cada alvo")
    ap.add_argument("-o", "--saida")
    ap.add_argument("--porta", default="/dev/ttyACM1")
    a = ap.parse_args()
    m, _ = roda(a.comandos, a.n, a.T, a.porta, saida=a.saida)
    ok = np.isfinite(m[:, 1])
    print(f"[{a.comandos}]  {len(m)} alvos")
    print(f"  erro final  : mediana {np.median(m[:,0]):.3f}  média {m[:,0].mean():.3f}  máx {m[:,0].max():.3f} rad")
    print(f"  chegou (<{TOL}) : {np.mean(m[:,0] <= TOL)*100:.0f}% dos alvos")
    print(f"  acomodação  : mediana {np.median(m[ok,1]) if ok.any() else np.nan:.2f} s"
          f"   (não acomodou em {(~ok).sum()})")
    print(f"  sobressinal : mediana {np.median(m[:,2]):.3f}  máx {m[:,2].max():.3f} rad")

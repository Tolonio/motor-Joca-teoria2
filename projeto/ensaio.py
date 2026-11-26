"""
Ensaios automáticos na bancada pela linha de comando (sem o painel).

Exemplos:
  python ensaio.py "m1;q100,250,750" 6 -o ../dados/teste_m1.csv
  python ensaio.py "z;m4;q-1.5708,1.5708,1500" 9 --grafico
  python ensaio.py "z;m2;q-1.5708,1.5708,1500" 9 --porta /dev/ttyACM0

Os comandos (separados por ';') são enviados logo depois que a placa reinicia.
Ao final o motor volta para malha aberta com referência zero (m0, r0).

Também pode ser importado:  from ensaio import Bancada
"""
import argparse
import os
import sys
import time

import numpy as np
import serial

CABECALHO = "t_ms,modo,referencia,u,velocidade,posicao"


class Bancada:
    """Conexão com a placa: envia comandos e coleta a telemetria."""

    def __init__(self, porta="/dev/ttyACM1", baud=115200):
        self.s = serial.Serial(porta, baud, timeout=0.05)
        time.sleep(2.5)                  # abrir a porta reinicia a placa
        self.s.reset_input_buffer()
        self.info = []

    def envia(self, *cmds):
        for c in cmds:
            for parte in c.split(";"):
                if parte.strip():
                    self.s.write((parte.strip() + "\n").encode())
                    time.sleep(0.03)

    def coleta(self, duracao):
        """Lê a telemetria por `duracao` segundos. Retorna array N x 6."""
        fim = time.time() + duracao
        linhas = []
        while time.time() < fim:
            l = self.s.readline().decode(errors="ignore").strip()
            if not l:
                continue
            if l.startswith("#"):
                self.info.append(l)
                continue
            p = l.split(",")
            if len(p) == 6:
                try:
                    linhas.append([float(x) for x in p])
                except ValueError:
                    pass
        return np.array(linhas).reshape(-1, 6)

    def para(self):
        self.envia("m0", "r0")
        time.sleep(0.1)

    def fecha(self):
        try:
            self.para()
        finally:
            self.s.close()


def salva(d, arq):
    os.makedirs(os.path.dirname(os.path.abspath(arq)), exist_ok=True)
    np.savetxt(arq, d, delimiter=",", header=CABECALHO, comments="",
               fmt=["%d", "%d", "%.3f", "%.3f", "%.2f", "%.4f"])


def grafico(d, titulo="", arq=None):
    import matplotlib
    if arq:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    t = (d[:, 0] - d[0, 0]) / 1000
    modo = int(d[-1, 1])
    pos = modo in (2, 4)
    y = d[:, 5] if pos else d[:, 4]
    fig, ax = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    ax[0].plot(t, d[:, 2], "k--", lw=1, label="referência")
    ax[0].plot(t, y, lw=1.5, label="θ [rad]" if pos else "ω [rad/s]")
    ax[0].legend(); ax[0].grid(alpha=.3); ax[0].set_title(titulo)
    ax[1].plot(t, d[:, 3], "C2"); ax[1].set_ylabel("u [V]"); ax[1].grid(alpha=.3)
    ax[1].set_xlabel("t [s]")
    fig.tight_layout()
    if arq:
        fig.savefig(arq, dpi=80)
    else:
        plt.show()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("comandos", help="comandos separados por ';'")
    ap.add_argument("duracao", type=float, help="segundos de gravação")
    ap.add_argument("-o", "--saida", help="arquivo CSV de saída")
    ap.add_argument("--porta", default="/dev/ttyACM1")
    ap.add_argument("--grafico", action="store_true", help="mostra o gráfico ao final")
    ap.add_argument("--png", help="salva o gráfico neste arquivo em vez de mostrar")
    a = ap.parse_args()

    b = Bancada(a.porta)
    try:
        b.envia(a.comandos)
        d = b.coleta(a.duracao)
    finally:
        b.fecha()
    print(f"{len(d)} amostras")
    if a.saida:
        salva(d, a.saida); print("salvo em", a.saida)
    if a.grafico or a.png:
        grafico(d, a.comandos, a.png)
    sys.exit(0 if len(d) else 1)

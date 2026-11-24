"""
Painel da bancada de motor DC: visualiza e controla tudo pela serial.

Requisitos:  pip install pyserial matplotlib numpy
Execute:     python painel.py

- Gráficos ao vivo (referência x saída, tensão u, a outra grandeza)
- Botões para os 5 modos, referência (pot / fixa / onda quadrada)
- Todos os ganhos editáveis e enviados para a placa
- Gravação em CSV (dados/...) para usar em projeto/compara.py e no relatório
"""
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from collections import deque

import serial
import serial.tools.list_ports
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

PASTA_DADOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dados")
JANELA_S = 8.0                       # segundos visíveis no gráfico
N = int(JANELA_S / 0.02)

MODOS = [
    (0, "m0  Malha aberta (u = ref, V)"),
    (1, "m1  Velocidade - LGR (PI)"),
    (2, "m2  Posição - LGR (avanço)"),
    (3, "m3  Velocidade - Espaço de Estados"),
    (4, "m4  Posição - Espaço de Estados"),
]
# referências padrão sugeridas para a onda quadrada em cada modo
QUADRADA_PADRAO = {0: ("0", "6", "1000"), 1: ("100", "250", "750"), 2: ("-1.5708", "1.5708", "750"),
                   3: ("100", "250", "750"), 4: ("-1.5708", "1.5708", "750")}
UNIDADE = {0: "V", 1: "rad/s", 2: "rad", 3: "rad/s", 4: "rad"}

# parâmetros: (comando, rótulo, nº de valores, dica)
PARAMS = [
    ("cv", "C(z) velocidade  b0,b1,b2,a1,a2", "PI projetado em lgr.py"),
    ("cp", "C(z) posição     b0,b1,b2,a1,a2", "avanço projetado em lgr.py"),
    ("ev", "EE velocidade    k1,ki,nv", "espaco_estados.py"),
    ("ep", "EE posição       k1,k2,ki", "espaco_estados.py"),
    ("ob", "Observador       L1,L2", "espaco_estados.py"),
    ("oe", "Observador ligado (0/1)", "só no m4"),
    ("pl", "Modelo planta    K,tau", "identificacao.py"),
    ("zm", "Compensação atrito girando (V)", "0 desliga"),
    ("zs", "Compensação atrito parado (V)", "0 = usa zm"),
    ("bp", "Banda morta de posição (rad)", "0 desliga"),
]


class Painel(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Bancada motor DC - painel de controle")
        self.geometry("1350x820")
        self.ser = None
        self.fila = queue.Queue()
        self.rodando = False
        self.gravando = None
        self.modo = 0
        self.dados = {k: deque(maxlen=N) for k in ("t", "r", "u", "w", "th")}
        self._monta_interface()
        self._atualiza_portas()
        self.after(50, self._tick)
        self.protocol("WM_DELETE_WINDOW", self._fechar)

    # ------------------------------------------------------------------ UI
    def _monta_interface(self):
        esq = ttk.Frame(self, padding=6)
        esq.pack(side=tk.LEFT, fill=tk.Y)
        dir_ = ttk.Frame(self)
        dir_.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # Conexão
        f = ttk.LabelFrame(esq, text="Conexão", padding=6); f.pack(fill=tk.X)
        self.cb_porta = ttk.Combobox(f, width=18); self.cb_porta.grid(row=0, column=0)
        ttk.Button(f, text="↻", width=3, command=self._atualiza_portas).grid(row=0, column=1)
        self.bt_con = ttk.Button(f, text="Conectar", command=self._conectar); self.bt_con.grid(row=0, column=2)
        self.lb_status = ttk.Label(f, text="desconectado", foreground="gray"); self.lb_status.grid(row=1, column=0, columnspan=3, sticky="w")

        # Modo
        f = ttk.LabelFrame(esq, text="Modo de controle", padding=6); f.pack(fill=tk.X, pady=4)
        self.var_modo = tk.IntVar(value=0)
        for m, txt in MODOS:
            ttk.Radiobutton(f, text=txt, value=m, variable=self.var_modo,
                            command=self._muda_modo).pack(anchor="w")

        # Motor
        f = ttk.LabelFrame(esq, text="Motor", padding=6); f.pack(fill=tk.X)
        ttk.Button(f, text="Liga (l)", command=lambda: self.envia("l")).grid(row=0, column=0)
        ttk.Button(f, text="DESLIGA (d)", command=lambda: self.envia("d")).grid(row=0, column=1)
        ttk.Button(f, text="Zerar posição (z)", command=lambda: self.envia("z")).grid(row=0, column=2)

        # Referência
        f = ttk.LabelFrame(esq, text="Referência", padding=6); f.pack(fill=tk.X, pady=4)
        ttk.Button(f, text="Potenciômetro (p)", command=lambda: self.envia("p")).grid(row=0, column=0, columnspan=4, sticky="we")
        ttk.Label(f, text="Fixa:").grid(row=1, column=0, sticky="e")
        self.e_ref = ttk.Entry(f, width=9); self.e_ref.insert(0, "0"); self.e_ref.grid(row=1, column=1)
        ttk.Button(f, text="Enviar", command=lambda: self.envia("r" + self.e_ref.get())).grid(row=1, column=2)
        self.lb_un = ttk.Label(f, text="V"); self.lb_un.grid(row=1, column=3)
        ttk.Label(f, text="Quadrada a,b,ms:").grid(row=2, column=0, sticky="e")
        self.e_qa = ttk.Entry(f, width=9); self.e_qa.grid(row=2, column=1)
        self.e_qb = ttk.Entry(f, width=9); self.e_qb.grid(row=2, column=2)
        self.e_qt = ttk.Entry(f, width=7); self.e_qt.grid(row=2, column=3)
        ttk.Button(f, text="Enviar onda quadrada", command=self._envia_quadrada).grid(row=3, column=0, columnspan=4, sticky="we")
        self._preenche_quadrada(0)

        # Parâmetros
        f = ttk.LabelFrame(esq, text="Parâmetros (Enter envia)", padding=6); f.pack(fill=tk.X)
        self.e_par = {}
        for i, (cmd, rot, dica) in enumerate(PARAMS):
            ttk.Label(f, text=rot, font=("TkFixedFont", 8)).grid(row=2 * i, column=0, columnspan=2, sticky="w")
            e = ttk.Entry(f, width=36); e.grid(row=2 * i + 1, column=0, sticky="we")
            e.bind("<Return>", lambda ev, c=cmd: self._envia_param(c))
            ttk.Button(f, text="→", width=3, command=lambda c=cmd: self._envia_param(c)).grid(row=2 * i + 1, column=1)
            self.e_par[cmd] = e
        ttk.Button(f, text="Ler parâmetros da placa (?)", command=lambda: self.envia("?")).grid(row=99, column=0, columnspan=2, sticky="we", pady=3)

        # Gravação
        f = ttk.LabelFrame(esq, text="Gravação CSV", padding=6); f.pack(fill=tk.X, pady=4)
        self.e_nome = ttk.Entry(f, width=24); self.e_nome.insert(0, "ensaio"); self.e_nome.grid(row=0, column=0)
        self.bt_grav = ttk.Button(f, text="● Gravar", command=self._grava); self.bt_grav.grid(row=0, column=1)

        # Gráficos
        self.fig = Figure(figsize=(8, 6), dpi=95)
        self.ax1 = self.fig.add_subplot(311)
        self.ax2 = self.fig.add_subplot(312, sharex=self.ax1)
        self.ax3 = self.fig.add_subplot(313, sharex=self.ax1)
        self.l_r, = self.ax1.plot([], [], "k--", lw=1, label="referência")
        self.l_y, = self.ax1.plot([], [], "C0", lw=1.5, label="saída")
        self.l_u, = self.ax2.plot([], [], "C2", lw=1.2)
        self.l_o, = self.ax3.plot([], [], "C1", lw=1.2)
        self.ax1.legend(loc="upper left", fontsize=8)
        self.ax2.set_ylabel("u [V]")
        self.ax3.set_xlabel("t [s]")
        for a in (self.ax1, self.ax2, self.ax3):
            a.grid(alpha=.3)
        self.fig.tight_layout()
        self.canvas = FigureCanvasTkAgg(self.fig, master=dir_)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Valores numéricos + console
        baixo = ttk.Frame(dir_); baixo.pack(fill=tk.X)
        self.lb_val = ttk.Label(baixo, text="", font=("TkFixedFont", 11)); self.lb_val.pack(anchor="w", padx=6)
        self.txt = tk.Text(baixo, height=7, font=("TkFixedFont", 9)); self.txt.pack(fill=tk.X, padx=6)
        lin = ttk.Frame(baixo); lin.pack(fill=tk.X, padx=6, pady=3)
        ttk.Label(lin, text="Comando:").pack(side=tk.LEFT)
        self.e_cmd = ttk.Entry(lin); self.e_cmd.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.e_cmd.bind("<Return>", lambda ev: (self.envia(self.e_cmd.get()), self.e_cmd.delete(0, tk.END)))
        self._eixos_modo(0)

    def _preenche_quadrada(self, m):
        a, b, t = QUADRADA_PADRAO[m]
        for e, v in ((self.e_qa, a), (self.e_qb, b), (self.e_qt, t)):
            e.delete(0, tk.END); e.insert(0, v)

    def _eixos_modo(self, m):
        un = UNIDADE[m]
        self.lb_un.config(text=un)
        if m in (2, 4):
            self.ax1.set_ylabel("θ [rad]"); self.ax3.set_ylabel("ω [rad/s]")
        else:
            self.ax1.set_ylabel("ω [rad/s]" if m else "ref [V] / ω"); self.ax3.set_ylabel("θ [rad]")
        self.ax1.set_title(MODOS[m][1], fontsize=10)

    # ------------------------------------------------------------------ serial
    def _atualiza_portas(self):
        ps = [p.device for p in serial.tools.list_ports.comports()]
        self.cb_porta["values"] = ps
        if ps and not self.cb_porta.get():
            pref = [p for p in ps if "ACM" in p or "USB" in p or "COM" in p]
            self.cb_porta.set(pref[-1] if pref else ps[0])

    def _conectar(self):
        if self.ser:
            self.rodando = False
            time.sleep(0.1)
            self.ser.close(); self.ser = None
            self.bt_con.config(text="Conectar"); self.lb_status.config(text="desconectado", foreground="gray")
            return
        try:
            self.ser = serial.Serial(self.cb_porta.get(), 115200, timeout=0.1)
        except Exception as e:
            messagebox.showerror("Erro", f"Não abriu a porta:\n{e}\n\nNo Linux: sudo usermod -aG dialout $USER (e reentre)")
            return
        self.rodando = True
        threading.Thread(target=self._leitor, daemon=True).start()
        self.bt_con.config(text="Desconectar")
        self.lb_status.config(text=f"conectado em {self.ser.port}", foreground="green")
        self.log("(a placa reinicia ao conectar; aguarde ~2 s)")
        self.after(2500, lambda: self.envia("?"))

    def _leitor(self):
        while self.rodando and self.ser:
            try:
                l = self.ser.readline().decode(errors="ignore").strip()
            except Exception:
                break
            if l:
                self.fila.put(l)

    def envia(self, cmd):
        cmd = cmd.strip()
        if not cmd:
            return
        if not self.ser:
            self.log("não conectado: " + cmd); return
        self.ser.write((cmd + "\n").encode())

    def _envia_param(self, c):
        self.envia(c + " " + self.e_par[c].get().replace(" ", ""))

    def _envia_quadrada(self):
        self.envia(f"q{self.e_qa.get()},{self.e_qb.get()},{self.e_qt.get()}")

    def _muda_modo(self):
        m = self.var_modo.get()
        self.envia(f"m{m}")
        self._preenche_quadrada(m)
        self._eixos_modo(m)

    def log(self, s):
        self.txt.insert(tk.END, s + "\n"); self.txt.see(tk.END)

    # ------------------------------------------------------------------ gravação
    def _grava(self):
        if self.gravando:
            self.gravando.close(); self.log("gravação salva: " + self.arq_grav)
            self.gravando = None; self.bt_grav.config(text="● Gravar"); return
        os.makedirs(PASTA_DADOS, exist_ok=True)
        nome = self.e_nome.get().strip() or "ensaio"
        self.arq_grav = os.path.normpath(os.path.join(PASTA_DADOS, f"{nome}_{time.strftime('%H%M%S')}.csv"))
        self.gravando = open(self.arq_grav, "w")
        self.gravando.write("t_ms,modo,referencia,u,velocidade,posicao\n")
        self.bt_grav.config(text="■ Parar")
        self.log("gravando em " + self.arq_grav)

    # ------------------------------------------------------------------ laço
    def _tick(self):
        novos = 0
        while not self.fila.empty():
            l = self.fila.get()
            if l.startswith("#"):
                self._trata_info(l)
                continue
            p = l.split(",")
            if len(p) != 6:
                continue
            try:
                t, m, r, u, w, th = (float(x) for x in p)
            except ValueError:
                continue
            if self.gravando:
                self.gravando.write(l + "\n")
            if int(m) != self.modo:
                self.modo = int(m); self.var_modo.set(self.modo); self._eixos_modo(self.modo)
            for k, v in zip(("t", "r", "u", "w", "th"), (t / 1000, r, u, w, th)):
                self.dados[k].append(v)
            novos += 1
        if novos:
            self._redesenha()
        self.after(60, self._tick)

    def _trata_info(self, l):
        self.log(l)
        partes = l[1:].split(" ", 1)
        if len(partes) == 2 and partes[0] in self.e_par:
            e = self.e_par[partes[0]]
            e.delete(0, tk.END); e.insert(0, partes[1].strip())

    def _redesenha(self):
        d = self.dados
        t = list(d["t"])
        pos = self.modo in (2, 4)
        y, o = (d["th"], d["w"]) if pos else (d["w"], d["th"])
        self.l_r.set_data(t, d["r"]); self.l_y.set_data(t, y)
        self.l_u.set_data(t, d["u"]); self.l_o.set_data(t, o)
        for a in (self.ax1, self.ax2, self.ax3):
            a.relim(); a.autoscale_view()
        self.ax1.set_xlim(max(t[-1] - JANELA_S, t[0]), t[-1] + 0.05)
        self.ax2.set_ylim(-12.5, 12.5)
        self.canvas.draw_idle()
        e = d["r"][-1] - y[-1]
        self.lb_val.config(text=f"ref = {d['r'][-1]:8.3f}   saída = {y[-1]:8.3f}   erro = {e:8.3f}   "
                                f"u = {d['u'][-1]:6.2f} V   ω = {d['w'][-1]:7.1f} rad/s   θ = {d['th'][-1]:7.3f} rad")

    def _fechar(self):
        if self.ser:
            try:
                self.envia("d")
            except Exception:
                pass
        if self.gravando:
            self.gravando.close()
        self.rodando = False
        self.destroy()


if __name__ == "__main__":
    Painel().mainloop()

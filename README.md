# Controle de motor DC: LGR e Espaço de Estados (bancada nº 5)

Firmware, interface gráfica e scripts de projeto para controlar **velocidade** e **posição**
de um motor DC com encoder. Tudo é feito de duas formas:

| Etapa | Abordagem | Velocidade | Posição |
|---|---|---|---|
| 1 | Funções de transferência, **Lugar Geométrico das Raízes (LGR)** | `m1`: PI discreto | `m2`: compensador de avanço |
| 2 | **Espaço de estados**, alocação de polos + integrador | `m3` | `m4` (observador opcional) |

Os quatro controladores ficam no mesmo firmware. Você troca entre eles e ajusta qualquer
ganho **pela serial, sem recompilar**, usando o painel gráfico (`interface/painel.py`).

![comparação simulação x bancada](docs/figuras/comparacao_bancada.png)

> **Primeira vez na bancada? Comece por [docs/05-modos.md](docs/05-modos.md).** Ele explica o que
> cada modo (m0 a m4) faz, o que esperar nos gráficos e no terminal, e responde às perguntas que
> surgiram nos primeiros testes ("nada muda quando giro o potenciômetro", "por que ω varia tanto",
> "por que o m4 mal responde"...). Versão interativa:
> <https://tolonio.github.io/motor-Joca-teoria2/docs/modos.html>

---

## Sumário

1. [Estrutura do repositório](#estrutura-do-repositório)
2. [Início rápido](#início-rápido)
3. [Como o sistema funciona (resumo)](#como-o-sistema-funciona-resumo)
4. [Resultados na bancada](#resultados-na-bancada)
5. [Comandos da serial](#comandos-da-serial)
6. Documentação detalhada:
   - [docs/01-hardware.md](docs/01-hardware.md): circuito, encoder, PWM, potenciômetro, temporização
   - [docs/02-identificacao-e-lgr.md](docs/02-identificacao-e-lgr.md): **Etapa 1** passo a passo
   - [docs/03-espaco-de-estados.md](docs/03-espaco-de-estados.md): **Etapa 2** passo a passo
   - [docs/04-github.md](docs/04-github.md): como versionar e publicar este projeto no GitHub
   - [docs/05-modos.md](docs/05-modos.md): **o que cada modo (m0 a m4) faz**, como a onda deveria ficar
     (simulação) e como ela fica na bancada, com exemplos da saída do terminal
   - [docs/modos.html](docs/modos.html): a mesma explicação em página interativa (gráficos com os
     valores ao passar o mouse) e **as perguntas que surgiram nos testes, respondidas em cada modo**.
     **Abra online:** <https://tolonio.github.io/motor-Joca-teoria2/docs/modos.html>

---

## Estrutura do repositório

```
controle_motor/
├── src/main.cpp            firmware (PlatformIO / Arduino): os 5 modos de controle
├── platformio.ini          placa LGT8F328P, porta serial, biblioteca TimerOne
├── interface/painel.py     painel gráfico: gráficos ao vivo, histórico de 30 min, botões, ganhos, CSV
├── projeto/
│   ├── planta.py           modelo da planta + simulador não linear (usado por todos)
│   ├── identificacao.py    obtém K, τ e a zona morta a partir de ensaios em malha aberta
│   ├── lgr.py              ETAPA 1: projeto por LGR no plano z
│   ├── espaco_estados.py   ETAPA 2: alocação de polos (Ackermann) + observador
│   ├── compara.py          sobrepõe simulação e dados da bancada
│   ├── figuras_modos.py    figuras de docs/05-modos.md (simulação x bancada, m0 a m4)
│   ├── ensaio.py           ensaios automáticos pela linha de comando, sem o painel
│   └── teste_posicao.py    teste estatístico do controle de posição (alvos aleatórios)
├── dados/                  ensaios gravados (CSV)
├── docs/                   explicações e figuras
└── backup/                 firmware ORIGINAL da bancada (.hex) para restaurar
```

## Início rápido

### 1. Instalar o software

```bash
# PlatformIO (compila e grava o firmware). No VS Code basta instalar a extensão "PlatformIO IDE".
pip install platformio

# Python para a interface e os scripts de projeto
pip install -r requirements.txt
```

> **Linux:** para acessar a porta serial sem `sudo`, rode `sudo usermod -aG dialout $USER`
> e faça logout/login.

### 2. Gravar o firmware

Ajuste `upload_port`/`monitor_port` em [platformio.ini](platformio.ini) (`/dev/ttyACM1` no Linux,
`COM5` etc. no Windows) e rode:

```bash
pio run -t upload
```

### 3. Abrir o painel

```bash
python interface/painel.py
```

Escolha a porta e clique em **Conectar**. A placa reinicia e o painel lê os ganhos atuais.
Em seguida, escolha o modo (m0 a m4), a referência (potenciômetro, valor fixo ou onda quadrada)
e acompanhe os gráficos. **● Gravar** salva um CSV em `dados/`.

* O painel escolhe sozinho a porta da placa (chip USB 1A86, "USB CDC-Serial"). Se houver outros
  dispositivos seriais (GPS, modem), confira a porta. Se a placa reconectar com outro nome, clique em **↻**.
* Cada linha recebida também é impressa no terminal que abriu o painel (formato em
  [docs/05-modos.md](docs/05-modos.md#como-ler-a-telemetria-terminal)). Comandos vão no campo **Comando:**.
* **Histórico:** o painel guarda os últimos 30 min. **⏸ Pausar gráfico** congela a tela; a lupa e a
  cruz da barra acima dos gráficos dão zoom e arrastam para o passado. **Salvar trecho visível** ou
  **Salvar últimos N s** gravam esse pedaço em `dados/`.

### 4. Refazer o projeto (opcional, mas é o trabalho!)

```bash
cd projeto
python identificacao.py      # 1) modelo da planta a partir de dados/degrau_malha_aberta_*.csv
python lgr.py                # 2) Etapa 1: imprime os comandos "cv ..." e "cp ..."
python espaco_estados.py     # 3) Etapa 2: imprime "ev ...", "ep ...", "ob ..."
python compara.py            # 4) simulação x bancada
```

Cole os comandos impressos no campo **Comando** do painel (ou nos campos de parâmetros).

## Como o sistema funciona (resumo)

```
 potenciômetro ─┐                         ┌──────────── Ts = 20 ms ─────────────┐
 serial (r, q) ─┴─► referência r ──► (+)─►│ controlador (m1..m4) │─► u (V) ─► PWM ─► ponte H ─► motor
                                      ▲ - └──────────────────────┘                          │
                                      │                                                       │
                                      └──── θ (rad), ω (rad/s) ◄── contagem do encoder ◄──────┘
```

* **Medida:** o encoder tem 32 pulsos por volta no canal A. Contando as **4 bordas** dos canais A e B
  (decodificação 4x), a contagem chega a **128 por volta**: θ = contagem·2π/128 e
  ω = Δcontagem·2π/(128·Ts). A resolução de ω é de 2,45 rad/s (4x melhor que no firmware original).
* **Atuação:** u ∈ [−12, 12] V vira PWM de 3 kHz: u > 0 aciona o pino D10 e u < 0 aciona o D9
  (as duas entradas da ponte H).
* **Planta identificada:** `W(s)/U(s) = 46,8 / (0,0195 s + 1)` rad/s/V, com **atrito seco**
  (o motor só sai do lugar acima de ~2,9 V girando, ou ~3,5 a 5 V parado).
* **Por que projetar no plano z:** τ ≈ 20 ms é igual a Ts, então não dá para tratar o controle
  como "quase contínuo". Os dois projetos discretizam a planta (ZOH) e trabalham direto em z.
* **Compensação de atrito:** o firmware soma `zm` (girando) ou `zs` (parado) volts no sentido de u.
  Assim o controlador "enxerga" uma planta quase linear, que é a hipótese do projeto.

Os detalhes e o *porquê* de cada escolha estão em [docs/](docs/).

## Resultados na bancada

| Modo | Controlador | Resultado (degrau 100→250 rad/s ou ±π/2 rad) |
|---|---|---|
| m1 | PI `C(z) = 0,01007 (z − 0,357)/(z − 1)` | acomodação (5 %) ≈ 0,14 s, sobressinal ≈ 2 %, erro em regime < 1 rad/s |
| m3 | EE `u = −0,00669 ω + 0,295 ∫e` | acomodação ≈ 0,16 s, sobressinal ≈ 2 %, erro < 1 rad/s |
| m2 | Avanço `C(z) = 0,897 (z − 0,357)/z` | rápido (≈ 0,1 s), mas **para onde o atrito deixar**: erro de 0 a 0,4 rad |
| m4 | EE `u = 0,65 (r − θ) − 0,0096 ω + 2,06 ∫e` | o integrador leva o erro a 0,05–0,1 rad, mas devagar (≈ 1–2 s) |

Na **velocidade**, simulação e bancada praticamente coincidem. Na **posição**, o resultado é
limitado pelo **atrito estático**, que varia com o ângulo do eixo. Isso é uma conclusão importante
do trabalho: um controlador sem integrador (m2) não corrige o erro deixado pelo atrito, e o
integrador (m4) corrige, ao custo de *stick-slip*. A discussão completa está em
[docs/03-espaco-de-estados.md](docs/03-espaco-de-estados.md#5-o-que-aconteceu-na-bancada-e-por-quê).

![posição com degraus longos](docs/figuras/comparacao_posicao_longo.png)

## Comandos da serial

Uma linha por comando, terminada em Enter (o painel faz isso por você).

| Comando | Efeito |
|---|---|
| `m0` … `m4` | modo: 0 malha aberta, 1 vel. LGR, 2 pos. LGR, 3 vel. EE, 4 pos. EE |
| `l` / `d` | liga / desliga o motor |
| `p` | referência pelo potenciômetro (±12 V, ±350 rad/s ou ±π rad, conforme o modo) |
| `r<valor>` | referência fixa, ex.: `r150` |
| `q<a>,<b>,<ms>` | onda quadrada entre a e b, meio período em ms, ex.: `q100,250,750` |
| `z` | zera a posição |
| `cv b0,b1,b2,a1,a2` | C(z) de velocidade: `(b0 + b1 z⁻¹ + b2 z⁻²)/(1 + a1 z⁻¹ + a2 z⁻²)` |
| `cp b0,b1,b2,a1,a2` | C(z) de posição |
| `ev k1,ki,nv` | EE velocidade: `u = −k1 ω + ki xi + nv r` |
| `ep k1,k2,ki` | EE posição: `u = k1 (r − θ) − k2 ω + ki xi` |
| `ob L1,L2` / `oe 0\|1` | ganhos do observador / desliga-liga o observador |
| `pl K,tau` | modelo da planta usado pelo observador |
| `zm V` / `zs V` | compensação de atrito girando / parado |
| `zr V/s` | rampa de partida: com o motor preso, a compensação sobe zr V/s (até 7 V); 0 desliga |
| `bp rad` | banda morta do erro de posição |
| `?` | imprime todos os parâmetros |

Telemetria (50 Hz): `t_ms,modo,referencia,u,velocidade,posicao`.

## Restaurar o firmware original

Ver [backup/README.md](backup/README.md).

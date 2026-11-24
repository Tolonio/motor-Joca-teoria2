# 4. Versionando e publicando no GitHub

Este repositório já está ligado ao GitHub (`origin`). Aqui está o passo a passo para enviar
mudanças e o **porquê** de cada passo.

## 4.1 Conceitos em 30 segundos

| Termo | O que é | Por que importa aqui |
|---|---|---|
| **commit** | uma "foto" do projeto com uma mensagem | dá para voltar a qualquer versão do firmware que funcionava |
| **branch** | uma linha de trabalho separada | testar um controlador novo sem quebrar o que já funciona |
| **push** | envia os commits para o GitHub | backup, e o professor ou o grupo podem ver |
| **.gitignore** | lista do que NÃO versionar | `.pio/` (arquivos de compilação) é grande e é gerado de novo a cada build |

## 4.2 Primeira vez numa máquina nova

```bash
git config --global user.name  "Seu Nome"
git config --global user.email "seu-email@exemplo.com"     # o mesmo da conta do GitHub
gh auth login           # (GitHub CLI) faz o login uma vez; alternativa: token pessoal
git clone https://github.com/Tolonio/motor-JOca.git
```

**Por quê:** o nome e o e-mail ficam gravados em cada commit (autoria). O `gh auth login` guarda a
credencial, e sem ela o `push` pede senha, que o GitHub não aceita mais.

## 4.3 Ciclo normal de trabalho

```bash
git status                       # 1. o que mudou?
git diff                         # 2. revisar as mudanças linha a linha
git add src/ projeto/ docs/      # 3. escolher o que entra no commit
git commit -m "Ajusta polos do controle de posição (EE)"   # 4. registrar
git push                         # 5. enviar para o GitHub
```

**Por que `git add` com pastas e não `git add .`:** para não enviar sem querer arquivos
temporários, CSVs de teste enormes ou configurações locais.

**Boas mensagens de commit:** dizem *o que* mudou e, se não for óbvio, *por quê*. Por exemplo,
"Liga anti-windup no PI de velocidade" é melhor que "ajustes".

## 4.4 Testando algo arriscado: use um branch

```bash
git switch -c teste-observador    # cria e entra no branch
# ... edita, grava na placa, testa ...
git commit -am "Testa observador com polos 0,1"
git push -u origin teste-observador
# deu certo? junta no principal:
git switch main && git merge teste-observador && git push
# não deu? volta ao main e o branch fica lá só como registro
git switch main
```

**Por quê:** o `main` sempre tem um firmware que funciona na bancada. Se algo der errado na
véspera da apresentação, você está a um `git switch main` + `pio run -t upload` de voltar ao
estado bom.

## 4.5 Marcando as entregas

```bash
git tag -a etapa1 -m "Entrega da Etapa 1 (LGR)"
git tag -a etapa2 -m "Entrega da Etapa 2 (espaço de estados)"
git push --tags
```

**Por quê:** a tag congela exatamente o código que foi apresentado. No GitHub ela aparece em
*Releases*, onde dá para anexar o `firmware.hex` (`.pio/build/lgt8f328p/firmware.hex`) para quem
quiser gravar sem compilar.

## 4.6 O que está (e o que não está) no repositório

| Versionado | Não versionado (`.gitignore`) |
|---|---|
| `src/`, `platformio.ini` (firmware) | `.pio/`: build, é recriado pelo `pio run` |
| `projeto/`, `interface/` (Python) | `__pycache__/`, `*.pyc`: cache do Python |
| `docs/` + figuras | `.vscode/`: configurações pessoais do editor |
| `dados/`: ensaios usados no relatório | |
| `backup/`: firmware original da bancada | |

**Por que as figuras e os CSVs entram:** o README mostra as figuras direto no GitHub, e com os CSVs
qualquer pessoa reproduz os gráficos rodando os scripts.

# Backup do firmware original (bancada nº 5)

Lido do Arduino em 2026-11-24 com avrdude (`-c arduino -b 57600`) e verificado byte a byte contra o chip.

| Arquivo | Conteúdo |
|---|---|
| `firmware_original.hex` | Imagem completa da flash (32 KB), Intel HEX |
| `firmware_original.bin` | Mesma imagem em binário |
| `firmware_original.asm` | Desmontagem (avr-objdump) |

> Não é possível recuperar o código-fonte em C, só o binário compilado.

## Restaurar o firmware original

```bash
AD=~/.platformio/packages/tool-avrdude
$AD/avrdude -C $AD/avrdude.conf -p atmega328p -c arduino -P /dev/ttyACM1 -b 57600 \
  -U flash:w:firmware_original.hex:i
```

## O que foi descoberto pela engenharia reversa

- **MCU:** provavelmente **LGT8F328P** (clone do ATmega328P). O código de inicialização escreve em
  PMCR (0xF2) e CLKPR, registradores típicos do núcleo LGT8F. O bootloader é do tipo antigo (57600 baud).
- **Encoder:** D2 e D3 (`INPUT_PULLUP`, `attachInterrupt` em INT0/INT1).
- **Motor:** PWM em **D9 (OC1A)** e **D10 (OC1B)** via Timer1 (biblioteca TimerOne), um pino por sentido.
- **Potenciômetro:** `pinMode(20)` = **A6**.
- **Serial:** 115200 baud. Imprime `col1,col2,col3` a **50 Hz (Ts = 20 ms)**.
  - col1 ≈ col2 ≈ 4,2 V: parece ser a referência/tensão vinda do potenciômetro.
  - col3: velocidade, quantizada em passos de 9,817 (1 pulso do encoder por amostra).
- **Comandos seriais aceitos** (lidos no `loop`): `r`, `s`, `S` (seguidos de número float), `p`, `t` (inteiro),
  `a`/`f` (liga/desliga uma flag), `l`/`d` (outra flag), `-`.
  Parece seguir este padrão: `r` = referência, `s`/`S` = parâmetros, `p` = parar,
  `a`/`f` = abrir/fechar a malha, `l`/`d` = ligar/desligar.

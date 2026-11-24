/*
 * Firmware da bancada de controle de motor DC (bancada nº 5)
 * ------------------------------------------------------------------
 * RECONSTRUÇÃO por engenharia reversa do binário original
 * (backup/firmware_original.hex), lido do Arduino em 2026-11-24.
 *
 * Os nomes de variáveis e funções foram inventados; a lógica, as
 * constantes e a pinagem foram tirados do assembly. Os endereços de RAM
 * do original estão nos comentários (ex.: @0x14D), para conferir com
 * backup/firmware_original.asm.
 *
 * Hardware (descoberto no binário):
 *   - MCU LGT8F328P a 16 MHz, ADC de 12 bits (0..4095)
 *   - Encoder: canal A em D2 (INT0, borda de subida), canal B em D3 (sentido)
 *              32 pulsos por volta (só bordas de subida do canal A)
 *   - Motor:   ponte H com 2 entradas PWM, Timer1 a 3 kHz (TimerOne)
 *              u >= 0 -> PWM em D10 (OC1B) | u < 0 -> PWM em D9 (OC1A)
 *   - Potenciômetro em A6
 *   - Serial 115200: imprime "referencia,tensao_u,velocidade" a cada 20 ms
 *
 * Comandos pela serial (verificados a cada 30 ms):
 *   l        liga o motor            d        desliga o motor
 *   a        malha aberta (u = ref)  f        malha fechada (PI de velocidade)
 *   r<num>   referência fixa (ex.: r3.5)              -> modo 1
 *   s<num>   nível 1 da onda quadrada (padrão  5.0)   -> modo 2
 *   S<num>   nível 2 da onda quadrada (padrão -5.0)   -> modo 2
 *   t<num>   meio período da onda quadrada em ms (padrão 1000)
 *   p        volta a usar o potenciômetro como referência -> modo 0
 */
#include <Arduino.h>
#include <TimerOne.h>

// ---------------- Pinos ----------------
const uint8_t PIN_ENC_A = 2;    // INT0
const uint8_t PIN_ENC_B = 3;
const uint8_t PIN_PWM_NEG = 9;  // OC1A - sentido negativo
const uint8_t PIN_PWM_POS = 10; // OC1B - sentido positivo
const uint8_t PIN_POT = A6;     // no original: pinMode(20, INPUT)

// ---------------- Constantes ----------------
const unsigned long TS_US = 20000;        // período de amostragem: 20 ms
const unsigned long CMD_PERIOD_MS = 30;   // leitura de comandos
const float PULSOS_POR_VOLTA = 32.0;      // 640000 = 32 * 20000 us
const float V_MAX = 12.0;                 // saturação da tensão
const float ADC_MAX = 4095.0;             // ADC de 12 bits

// Controlador PI discreto (forma incremental):
//   u[k] = u[k-1] + KE0*e[k] - KE1*e[k-1]
//   C(z) = (KE0 z - KE1) / (z - 1)
const float KE0 = 0.01;        // 0x3C23D70A
const float KE1 = 0.0035;      // 0x3B656F5B (= 0.00350000)

// ---------------- Estado ----------------
enum Modo : uint8_t { MODO_POT = 0, MODO_FIXA = 1, MODO_QUADRADA = 2, MODO_TRIANGULAR = 3 };

volatile long contagemEncoder = 0;   // @0x137
long contagemAnterior = 0;           // @0x133

uint8_t motorLigado = 1;             // @0x10D  ('l' / 'd')
uint8_t malhaAberta = 1;             // @0x10E  ('a' / 'f')
uint8_t modo = MODO_POT;             // @0x151
uint8_t sentidoTri = 1;              // @0x104  (usado só no modo 3)

float referencia = 0;                // @0x14D
float refBaixa = 5.0;                // @0x105  ('s')
float refAlta = -5.0;                // @0x109  ('S')
long periodoRefMs = 1000;            // @0x10F  ('t')

float u = 0;                         // @0x145  tensão aplicada
float velocidade = 0;                // @0x149  rad/s
float erroAnterior = 0;              // @0x13B
float uAnterior = 0;                 // @0x13F

unsigned int tCmd = 0;               // @0x156
unsigned int tRef = 0;               // @0x154
unsigned int tCtrl = 0;              // @0x152

// ---------------- Encoder ----------------
void isrEncoder() {
  if (digitalRead(PIN_ENC_B)) contagemEncoder--;
  else                        contagemEncoder++;
}

// ---------------- Motor ----------------
void aplicaTensao(float v) {
  // duty de 0..1024 (TimerOne usa 10 bits); o original soma 1 antes de truncar
  if (!motorLigado) v = 0;
  if (v < 0) {
    unsigned long duty = (unsigned long)(v * 1023.0 / -V_MAX + 1.0);
    Timer1.setPwmDuty(PIN_PWM_POS, 0);
    Timer1.setPwmDuty(PIN_PWM_NEG, duty);
  } else {
    unsigned long duty = (unsigned long)(v * 1023.0 / V_MAX + 1.0);
    Timer1.setPwmDuty(PIN_PWM_POS, duty);
    Timer1.setPwmDuty(PIN_PWM_NEG, 0);
  }
}

// ---------------- Comandos seriais ----------------
void trataComandos() {
  if (Serial.available() <= 0) return;
  char c = Serial.read();
  switch (c) {
    case 'l': motorLigado = 1; break;
    case 'd': motorLigado = 0; break;
    case 'a': malhaAberta = 1; break;
    case 'f': malhaAberta = 0; break;
    case 'p': modo = MODO_POT; break;
    case 'r': referencia = Serial.parseFloat(); modo = MODO_FIXA; break;
    case 's': refBaixa = Serial.parseFloat(); modo = MODO_QUADRADA; break;
    case 'S': refAlta = Serial.parseFloat(); modo = MODO_QUADRADA; break;
    case 't': periodoRefMs = Serial.parseInt(); break;
  }
}

// ---------------- Gerador de referência ----------------
void geraReferencia() {
  if (modo == MODO_QUADRADA) {
    referencia = (referencia != refAlta) ? refAlta : refBaixa;
  } else if (modo == MODO_TRIANGULAR) {
    // Não há comando que ative este modo no original; mantido por fidelidade.
    if (referencia >= 5.0)  sentidoTri = 1;   // chegou no topo: desce
    if (referencia <= -5.0) sentidoTri = 0;   // chegou no fundo: sobe
    referencia += sentidoTri ? -10.0 : 10.0;
  }
}

// ---------------- Laço de controle (Ts = 20 ms) ----------------
void passoControle() {
  // 1) Referência
  if (modo == MODO_POT) {
    int pot = analogRead(PIN_POT);
    if (malhaAberta) referencia = V_MAX - pot * 24.0 / ADC_MAX;   // -12..+12 V
    else             referencia = 600.0 - pot * 1200.0 / ADC_MAX;  // -600..+600 rad/s
  }

  // 2) Velocidade pelo encoder
  noInterrupts();
  long cont = contagemEncoder;
  interrupts();
  long delta = cont - contagemAnterior;
  contagemAnterior = cont;
  velocidade = (delta * 1000000.0 / (PULSOS_POR_VOLTA * TS_US)) * 2.0 * PI; // rad/s

  // 3) Lei de controle
  if (malhaAberta) {
    u = referencia;
  } else {
    float e = referencia - velocidade;
    float v = uAnterior + KE0 * e - KE1 * erroAnterior;
    if (v > V_MAX) v = V_MAX;
    if (v < -V_MAX) v = -V_MAX;
    erroAnterior = e;
    uAnterior = v;
    u = v;
  }

  // 4) Atuação
  aplicaTensao(u);

  // 5) Telemetria
  Serial.print(referencia, 2);
  Serial.print(',');
  Serial.print(u, 2);
  Serial.print(',');
  Serial.println(velocidade, 2);
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_POT, INPUT);

  Timer1.initialize(333);               // 3 kHz (ICR1 = 2664 @ 16 MHz)
  Timer1.pwm(PIN_PWM_POS, 1024);        // original inicia as duas saídas em 100%
  Timer1.pwm(PIN_PWM_NEG, 1024);

  pinMode(PIN_ENC_A, INPUT_PULLUP);
  pinMode(PIN_ENC_B, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_A), isrEncoder, RISING);
}

void loop() {
  // Tarefa 1: comandos (a cada 30 ms)
  if ((unsigned int)(millis() - tCmd) >= CMD_PERIOD_MS) {
    trataComandos();
    tCmd += CMD_PERIOD_MS;
  }
  // Tarefa 2: gerador de referência (a cada t ms)
  if ((unsigned int)(millis() - tRef) >= (unsigned long)periodoRefMs) {
    geraReferencia();
    tRef += periodoRefMs;
  }
  // Tarefa 3: controle (a cada 20 ms, via micros)
  if ((unsigned int)(micros() - tCtrl) >= TS_US) {
    passoControle();
    tCtrl += TS_US;
  }
}

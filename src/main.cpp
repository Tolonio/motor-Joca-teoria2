/*
 * Bancada de controle de motor DC - firmware didático
 * ==================================================================
 * Um único firmware com os 5 modos de operação pedidos no trabalho:
 *
 *   m0  Malha aberta ............ u = referência (V)          -> identificação da planta
 *   m1  Velocidade  - LGR ....... C(z) genérico de 2ª ordem    -> Etapa 1
 *   m2  Posição     - LGR ....... C(z) genérico de 2ª ordem    -> Etapa 1
 *   m3  Velocidade  - Espaço de Estados (realim. + integrador) -> Etapa 2
 *   m4  Posição     - Espaço de Estados (realim. + integrador
 *                                         + observador opcional) -> Etapa 2
 *
 * Todos os ganhos podem ser trocados pela serial (sem recompilar).
 * Os valores padrão abaixo vêm de projeto/lgr.py e projeto/espaco_estados.py (planta identificada
 * na bancada). Veja docs/ para a explicação completa.
 *
 * Hardware:
 *   - LGT8F328P (Nano roxo) a 16 MHz, ADC de 12 bits
 *   - Encoder em quadratura: A = D2 (INT0), B = D3 (INT1)
 *   - Ponte H com 2 entradas PWM (Timer1, 3 kHz): D10 = sentido +, D9 = sentido -
 *   - Potenciômetro (referência manual) em A6
 *
 * Telemetria (115200 baud, a cada Ts = 20 ms), uma linha CSV:
 *   t_ms,modo,referencia,u,velocidade,posicao
 *   (V, rad/s e rad). Linhas que começam com '#' são mensagens/parâmetros.
 *
 * Comandos (uma linha terminada em '\n'):
 *   m<n>            modo 0..4 (zera os estados do controlador)
 *   l / d           liga / desliga o motor (desligado => u = 0)
 *   p               referência pelo potenciômetro
 *   r<v>            referência fixa
 *   q<a>,<b>,<ms>   onda quadrada entre a e b, meio período em ms
 *   z               zera a posição (encoder) e os estados
 *   cv b0,b1,b2,a1,a2   controlador de velocidade LGR  (C(z), ver abaixo)
 *   cp b0,b1,b2,a1,a2   controlador de posição   LGR
 *   ev k1,ki,nv         espaço de estados, velocidade
 *   ep k1,k2,ki         espaço de estados, posição
 *   ob L1,L2            ganhos do observador de posição
 *   oe 0|1              desliga / liga o observador
 *   pl K,tau            modelo da planta (usado pelo observador)
 *   pc a0,am,a1,zn      calibração do potenciômetro: leitura numa ponta (a0 -> +1), no meio
 *                       físico (am -> 0), na outra ponta (a1 -> -1) e zona neutra (fração, ex. 0.03)
 *   pa                  imprime a leitura bruta do potenciômetro (0..4095), para calibrar
 *   zm <V>              compensação de zona morta (V), 0 = desliga
 *   zs <V>              compensação de atrito estático (usada com o motor parado)
 *   zr <V/s>            rampa de partida: com o motor preso, zs sobe zr V/s (até 7 V)
 *   bp <rad>            banda morta do erro de posição (m2/m4), 0 = desliga
 *   ?                   imprime todos os parâmetros
 */
#include <Arduino.h>
#include <TimerOne.h>

// ======================= Configuração fixa =======================
const uint8_t PIN_ENC_A   = 2;    // INT0
const uint8_t PIN_ENC_B   = 3;    // INT1
const uint8_t PIN_PWM_NEG = 9;    // OC1A
const uint8_t PIN_PWM_POS = 10;   // OC1B
const uint8_t PIN_POT     = A6;

const unsigned long TS_US = 20000UL;      // período de amostragem
const float TS = TS_US * 1e-6f;           // 0.02 s
const float V_MAX = 12.0f;                // saturação da tensão

// O encoder gera 32 pulsos/volta no canal A. Contando as 4 bordas (A e B,
// subida e descida) temos 128 contagens/volta: 4x mais resolução.
const float CONTAGENS_POR_VOLTA = 128.0f;
const float RAD_POR_CONTAGEM = 2.0f * PI / CONTAGENS_POR_VOLTA;

// Faixa da referência pelo potenciômetro, em cada modo
const float POT_V   = 12.0f;     // m0: ±12 V
// Calibração do potenciômetro (medida na bancada nº 5 em 2026-11-26): as pontas leem 0 e 4064,
// mas o meio físico lê ~2535, e não ~2032. Por isso o mapeamento é feito em dois trechos
// (ponta -> meio e meio -> ponta), e o meio físico vira referência zero.
const float POT_W   = 350.0f;    // m1/m3: ±350 rad/s (máx. ≈ 420 com 12 V)
const float POT_POS = PI;        // m2/m4: ±π rad (±meia volta)

// ======================= Parâmetros (ajustáveis pela serial) =======================
// Controlador discreto genérico (LGR), forma de equação a diferenças:
//   u[k] = b0 e[k] + b1 e[k-1] + b2 e[k-2] - a1 u[k-1] - a2 u[k-2]
//   C(z) = (b0 + b1 z^-1 + b2 z^-2) / (1 + a1 z^-1 + a2 z^-2)
// Serve para P, PI, PD, PID, avanço, atraso... (até 2ª ordem).
struct CtrlZ { float b0, b1, b2, a1, a2; };

// Padrões calculados por projeto/lgr.py
CtrlZ ctrlVel = { 0.010070f, -0.003592f, 0.0f, -1.0f, 0.0f };   // PI de velocidade (lgr.py)
CtrlZ ctrlPos = { 0.897000f, -0.319938f, 0.0f, 0.0f, 0.0f };     // avanço de posição (lgr.py)

// Espaço de estados
//   velocidade: u = -k1*w + ki*xi + nv*r,      xi[k+1] = xi[k] + Ts*(r - w)
//   posição:    u = k1*(r - th) - k2*w + ki*xi, xi[k+1] = xi[k] + Ts*(r - th)
float ssV_k1 = 0.006694f, ssV_ki = 0.295139f, ssV_nv = 0.0f;   // espaco_estados.py
float ssP_k1 = 0.649990f, ssP_k2 = 0.009648f, ssP_ki = 2.057970f;

// Modelo da planta  W(s)/U(s) = K/(tau s + 1)  e observador de posição
float plantaK = 46.75f, plantaTau = 0.0194f;   // identificacao.py
float obsL1 = 0.806676f, obsL2 = 0.484432f;
bool  observadorLigado = false;   // ver docs: atrito estático atrapalha o observador

float zonaMorta = 3.0f;   // V somados a |u| para vencer o atrito seco
float atritoEstatico = 4.0f;  // V usados no lugar de zm quando o motor está parado (0 = igual a zm)
float rampaPartida = 0.0f;    // V/s: quanto a tensão de partida sobe enquanto o motor segue preso
const float ZS_MAX = 7.0f;    // limite da rampa de partida
uint16_t nParado = 0;         // amostras seguidas com o motor preso
float bandaPos = 0.10f;    // |erro| (rad) abaixo do qual o controle de posição desliga

// ======================= Estado =======================
enum Modo : uint8_t { M_ABERTA = 0, M_VEL_LGR, M_POS_LGR, M_VEL_EE, M_POS_EE };
enum FonteRef : uint8_t { REF_POT = 0, REF_FIXA, REF_QUADRADA };

uint8_t modo = M_ABERTA;
uint8_t fonteRef = REF_POT;
bool motorLigado = true;

float refFixa = 0.0f;
float qA = 0.0f, qB = 0.0f;           // níveis da onda quadrada
unsigned long qMeioMs = 1000;
unsigned long qT0 = 0;

volatile long contagem = 0;
volatile uint8_t estadoAB = 0;
long contagemAnterior = 0;

float referencia = 0, u = 0, w = 0, th = 0;
float e1 = 0, e2 = 0, u1 = 0, u2 = 0;   // memória do C(z)
float xi = 0;                           // integrador do espaço de estados
float thHat = 0, wHat = 0;              // estados estimados pelo observador
float phi12, phi22, gam1, gam2;         // modelo discreto (ZOH) para o observador

unsigned long tCtrl = 0;

// ======================= Encoder (decodificação 4x) =======================
// Índice = (estado anterior << 2) | estado novo, estado = (A<<1)|B.
// Sequência 00->01->11->10 = -1 (mesmo sentido do firmware original).
const int8_t TAB_QUAD[16] = { 0, -1, +1, 0,
                             +1,  0,  0, -1,
                             -1,  0,  0, +1,
                              0, +1, -1, 0 };

void isrEncoder() {
  uint8_t pins = PIND;                                   // leitura direta: rápida
  uint8_t novo = ((pins >> 1) & 0x02) | ((pins >> 3) & 0x01); // A=D2, B=D3
  contagem += TAB_QUAD[(estadoAB << 2) | novo];
  estadoAB = novo;
}

// ======================= Motor =======================
void aplicaTensao(float v) {
  if (!motorLigado) v = 0;
  float mag = fabs(v);
  unsigned int duty = (unsigned int)(mag * 1024.0f / V_MAX + 0.5f);
  if (duty > 1024) duty = 1024;
  if (v >= 0) { Timer1.setPwmDuty(PIN_PWM_NEG, 0); Timer1.setPwmDuty(PIN_PWM_POS, duty); }
  else        { Timer1.setPwmDuty(PIN_PWM_POS, 0); Timer1.setPwmDuty(PIN_PWM_NEG, duty); }
}

float satura(float v) { return v > V_MAX ? V_MAX : (v < -V_MAX ? -V_MAX : v); }

// ======================= Auxiliares =======================
void calculaModeloDiscreto() {
  // ZOH de  th' = w,  w' = (-w + K u)/tau
  float a = exp(-TS / plantaTau);
  phi12 = plantaTau * (1 - a);
  phi22 = a;
  gam1 = plantaK * (TS - plantaTau * (1 - a));
  gam2 = plantaK * (1 - a);
}

void zeraEstados() {
  e1 = e2 = u1 = u2 = 0;
  xi = 0;
  thHat = th; wHat = w;
}

float potA0 = 0.0f, potMeio = 2535.0f, potA1 = 4064.0f;   // comando pc
float potZona = 0.03f;   // zona neutra em volta do meio (fração do curso de cada lado)

float lePotBruto() {   // média de 4 leituras, 0..4095
  long s = 0;
  for (uint8_t i = 0; i < 4; i++) s += analogRead(PIN_POT);
  return s / 4.0f;
}

float lePot() {   // retorna -1..+1 (sentido igual ao original: leitura baixa = positivo)
  float a = lePotBruto();
  // do lado da ponta a0: 0..+1; do lado da ponta a1: 0..-1 (vale para a0 < a1 ou a0 > a1)
  float x = ((a - potMeio) * (potA0 - potMeio) >= 0) ? (a - potMeio) / (potA0 - potMeio)
                                                     : -(a - potMeio) / (potA1 - potMeio);
  if (x > 1) x = 1;
  if (x < -1) x = -1;
  // zona neutra: perto do meio vale exatamente 0; fora dela reescala para não dar salto
  float m = fabs(x);
  if (m <= potZona) return 0.0f;
  return (x > 0 ? 1 : -1) * (m - potZona) / (1.0f - potZona);
}

float escalaPot() {
  switch (modo) {
    case M_ABERTA: return POT_V;
    case M_VEL_LGR: case M_VEL_EE: return POT_W;
    default: return POT_POS;
  }
}

void imprimeParametros() {
  Serial.print(F("#modo=")); Serial.print(modo);
  Serial.print(F(" ref=")); Serial.print(fonteRef);
  Serial.print(F(" motor=")); Serial.println(motorLigado);
  Serial.print(F("#cv ")); Serial.print(ctrlVel.b0, 6); Serial.print(','); Serial.print(ctrlVel.b1, 6);
  Serial.print(','); Serial.print(ctrlVel.b2, 6); Serial.print(','); Serial.print(ctrlVel.a1, 6);
  Serial.print(','); Serial.println(ctrlVel.a2, 6);
  Serial.print(F("#cp ")); Serial.print(ctrlPos.b0, 6); Serial.print(','); Serial.print(ctrlPos.b1, 6);
  Serial.print(','); Serial.print(ctrlPos.b2, 6); Serial.print(','); Serial.print(ctrlPos.a1, 6);
  Serial.print(','); Serial.println(ctrlPos.a2, 6);
  Serial.print(F("#ev ")); Serial.print(ssV_k1, 6); Serial.print(','); Serial.print(ssV_ki, 6);
  Serial.print(','); Serial.println(ssV_nv, 6);
  Serial.print(F("#ep ")); Serial.print(ssP_k1, 6); Serial.print(','); Serial.print(ssP_k2, 6);
  Serial.print(','); Serial.println(ssP_ki, 6);
  Serial.print(F("#ob ")); Serial.print(obsL1, 6); Serial.print(','); Serial.println(obsL2, 6);
  Serial.print(F("#oe ")); Serial.println(observadorLigado);
  Serial.print(F("#pl ")); Serial.print(plantaK, 4); Serial.print(','); Serial.println(plantaTau, 5);
  Serial.print(F("#pc ")); Serial.print(potA0, 0); Serial.print(','); Serial.print(potMeio, 0);
  Serial.print(','); Serial.print(potA1, 0); Serial.print(','); Serial.println(potZona, 3);
  Serial.print(F("#zm ")); Serial.println(zonaMorta, 3);
  Serial.print(F("#zs ")); Serial.println(atritoEstatico, 3);
  Serial.print(F("#zr ")); Serial.println(rampaPartida, 3);
  Serial.print(F("#bp ")); Serial.println(bandaPos, 4);
}

// Lê até n floats separados por vírgula/espaço. Retorna quantos leu.
uint8_t leFloats(const char *s, float *out, uint8_t n) {
  uint8_t k = 0;
  while (*s && k < n) {
    while (*s == ' ' || *s == ',') s++;
    if (!*s) break;
    char *fim;
    out[k] = strtod(s, &fim);
    if (fim == s) break;
    k++; s = fim;
  }
  return k;
}

// ======================= Comandos =======================
char linha[64];
uint8_t nLinha = 0;

void executa(char *c) {
  float v[5];
  switch (c[0]) {
    case 'm': {
      int m = atoi(c + 1);
      if (m >= 0 && m <= 4) { modo = m; zeraEstados(); }
      break;
    }
    case 'l': motorLigado = true; zeraEstados(); break;
    case 'd': motorLigado = false; break;
    case 'p':
      if (c[1] == 'l') {
        if (leFloats(c + 2, v, 2) == 2 && v[1] > 0) {
          plantaK = v[0]; plantaTau = v[1]; calculaModeloDiscreto(); zeraEstados();
        }
      } else if (c[1] == 'c') {
        uint8_t n = leFloats(c + 2, v, 4);
        // exige a ordem ponta < meio < ponta (ou o contrário) para não dividir por zero
        if (n >= 3 && ((v[0] < v[1] && v[1] < v[2]) || (v[0] > v[1] && v[1] > v[2]))) {
          potA0 = v[0]; potMeio = v[1]; potA1 = v[2];
          if (n == 4 && v[3] >= 0 && v[3] < 0.5f) potZona = v[3];
        }
      } else if (c[1] == 'a') {
        Serial.print(F("#pa ")); Serial.println(lePotBruto(), 1);
        return;
      } else fonteRef = REF_POT;
      break;
    case 'r': if (leFloats(c + 1, v, 1) == 1) { refFixa = v[0]; fonteRef = REF_FIXA; } break;
    case 'q':
      if (leFloats(c + 1, v, 3) == 3) {
        qA = v[0]; qB = v[1]; qMeioMs = (unsigned long)v[2];
        if (qMeioMs < 20) qMeioMs = 20;
        qT0 = millis(); fonteRef = REF_QUADRADA;
      }
      break;
    case 'b':
      if (c[1] == 'p' && leFloats(c + 2, v, 1) == 1) bandaPos = v[0];
      break;
    case 'z':
      if (c[1] == 's') { if (leFloats(c + 2, v, 1) == 1) atritoEstatico = v[0]; break; }
      if (c[1] == 'r') { if (leFloats(c + 2, v, 1) == 1) rampaPartida = v[0]; break; }
      if (c[1] == 'm') { if (leFloats(c + 2, v, 1) == 1) zonaMorta = v[0]; break; }
      noInterrupts(); contagem = 0; interrupts();
      contagemAnterior = 0; th = 0; zeraEstados();
      break;
    case 'c':
      if (leFloats(c + 2, v, 5) == 5) {
        CtrlZ &k = (c[1] == 'v') ? ctrlVel : ctrlPos;
        k = { v[0], v[1], v[2], v[3], v[4] };
        zeraEstados();
      }
      break;
    case 'e':
      if (c[1] == 'v' && leFloats(c + 2, v, 3) == 3) { ssV_k1 = v[0]; ssV_ki = v[1]; ssV_nv = v[2]; zeraEstados(); }
      if (c[1] == 'p' && leFloats(c + 2, v, 3) == 3) { ssP_k1 = v[0]; ssP_k2 = v[1]; ssP_ki = v[2]; zeraEstados(); }
      break;
    case 'o':
      if (c[1] == 'b' && leFloats(c + 2, v, 2) == 2) { obsL1 = v[0]; obsL2 = v[1]; zeraEstados(); }
      if (c[1] == 'e') { observadorLigado = atoi(c + 2) != 0; zeraEstados(); }
      break;
    case '?': imprimeParametros(); return;
    default: break;
  }
  Serial.print(F("#ok ")); Serial.println(c);
}

void trataSerial() {           // não bloqueia: junta caracteres até '\n'
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n' || ch == '\r') {
      if (nLinha) { linha[nLinha] = 0; executa(linha); nLinha = 0; }
    } else if (nLinha < sizeof(linha) - 1) {
      linha[nLinha++] = ch;
    }
  }
}

// ======================= Laço de controle (Ts = 20 ms) =======================
float controladorZ(const CtrlZ &k, float e) {
  float v = k.b0 * e + k.b1 * e1 + k.b2 * e2 - k.a1 * u1 - k.a2 * u2;
  v = satura(v);
  // Guardar o u JÁ SATURADO na memória é o anti-windup: o integrador não
  // "acumula" além do que o motor consegue fazer.
  e2 = e1; e1 = e;
  u2 = u1; u1 = v;
  return v;
}

void passoControle() {
  // 1) Referência
  if (fonteRef == REF_POT) {
    referencia = lePot() * escalaPot();
  } else if (fonteRef == REF_FIXA) {
    referencia = refFixa;
  } else {
    referencia = (((millis() - qT0) / qMeioMs) & 1) ? qB : qA;
  }

  // 2) Medidas: posição e velocidade pelo encoder
  noInterrupts(); long c = contagem; interrupts();
  long delta = c - contagemAnterior;
  contagemAnterior = c;
  th = c * RAD_POR_CONTAGEM;            // rad
  w  = delta * RAD_POR_CONTAGEM / TS;   // rad/s (resolução 2,45 rad/s)

  // 3) Lei de controle
  float v = 0;
  switch (modo) {
    case M_ABERTA:
      v = referencia;
      break;

    case M_VEL_LGR:
      v = controladorZ(ctrlVel, referencia - w);
      break;

    case M_POS_LGR: {
      float e = referencia - th;
      v = controladorZ(ctrlPos, e);
      if (fabs(e) <= bandaPos) { v = 0; u1 = 0; }   // banda morta de erro
      break;
    }

    case M_VEL_EE: {
      float e = referencia - w;
      v = -ssV_k1 * w + ssV_ki * xi + ssV_nv * referencia;
      float vs = satura(v);
      // anti-windup: só integra se não estiver saturado "empurrando" no mesmo sentido
      if (vs == v || (v > 0) != (e > 0)) xi += TS * e;
      v = vs;
      break;
    }

    case M_POS_EE: {
      float thU = th, wU = w;
      if (observadorLigado) { thU = thHat; wU = wHat; }
      float e = referencia - th;
      if (fabs(e) <= bandaPos) { v = 0; break; }   // chegou: desliga e congela o integrador
      v = ssP_k1 * (referencia - thU) - ssP_k2 * wU + ssP_ki * xi;
      float vs = satura(v);
      if (vs == v || (v > 0) != (e > 0)) xi += TS * e;
      v = vs;
      break;
    }
  }

  // u "linear" (antes da compensação): é o que o modelo/observador enxerga,
  // pois a compensação existe justamente para cancelar o atrito.
  float vLin = v;

  // Compensação de atrito (opcional): soma uma tensão no sentido de u.
  //   girando        -> zm (atrito dinâmico/Coulomb)
  //   parado         -> zs + zr * (tempo parado), até ZS_MAX: rampa de partida.
  //   O atrito estático desta bancada varia de 2,4 V a 5,7 V conforme o ponto,
  //   então em vez de um valor fixo a tensão sobe até o motor se mexer.
  if (modo != M_ABERTA) {
    float comp = zonaMorta;
    bool preso = (w == 0 && fabs(v) > 0.05f);
    if (preso && atritoEstatico > zonaMorta) {
      comp = atritoEstatico + rampaPartida * TS * nParado;
      if (comp > ZS_MAX) comp = ZS_MAX;
      nParado++;
    } else {
      nParado = 0;
    }
    if (comp > 0) {
      if (v > 0.05f) v = satura(v + comp);
      else if (v < -0.05f) v = satura(v - comp);
    }
  }

  if (!motorLigado) { v = 0; vLin = 0; zeraEstados(); }
  u = v;
  aplicaTensao(u);

  // 4) Observador (preditor):  x^[k+1] = Phi x^[k] + Gam u[k] + L (y[k] - th^[k])
  float erroObs = th - thHat;
  float uObs = (modo == M_ABERTA) ? u : vLin;
  float thN = thHat + phi12 * wHat + gam1 * uObs + obsL1 * erroObs;
  float wN  =         phi22 * wHat + gam2 * uObs + obsL2 * erroObs;
  thHat = thN; wHat = wN;

  // 5) Telemetria
  Serial.print(millis()); Serial.print(',');
  Serial.print(modo); Serial.print(',');
  Serial.print(referencia, 3); Serial.print(',');
  Serial.print(u, 3); Serial.print(',');
  Serial.print(w, 2); Serial.print(',');
  Serial.println(th, 4);
}

// ======================= Setup / loop =======================
void setup() {
  Serial.begin(115200);
  analogReadResolution(12);              // LGT8F: o padrão do core é 10 bits!
  pinMode(PIN_POT, INPUT);

  Timer1.initialize(333);                // 3 kHz
  Timer1.pwm(PIN_PWM_POS, 0);
  Timer1.pwm(PIN_PWM_NEG, 0);

  pinMode(PIN_ENC_A, INPUT_PULLUP);
  pinMode(PIN_ENC_B, INPUT_PULLUP);
  estadoAB = ((PIND >> 1) & 0x02) | ((PIND >> 3) & 0x01);
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_A), isrEncoder, CHANGE);
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_B), isrEncoder, CHANGE);

  calculaModeloDiscreto();
  Serial.println(F("#bancada pronta - envie ? para ver os parametros"));
  imprimeParametros();
  tCtrl = micros();
}

void loop() {
  trataSerial();
  if (micros() - tCtrl >= TS_US) {
    tCtrl += TS_US;
    passoControle();
  }
}

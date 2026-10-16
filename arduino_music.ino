#include <Arduino.h>
#include <avr/interrupt.h>
#include <util/atomic.h>

const uint8_t BUZZER_PIN = 5;
const uint16_t SAMPLE_RATE = 8000;
const uint16_t BUFFER_SIZE = 512;
const uint16_t PREBUFFER_SAMPLES = 128;        // 预存 16 ms，缓解串口传输抖动。
const uint16_t PREBUFFER_TIMEOUT_TICKS = 160;  // 20 ms；以 Timer1 的采样节拍计时。

volatile uint8_t audioBuffer[BUFFER_SIZE];
volatile uint16_t readIndex = 0;
uint16_t writeIndex = 0;
volatile uint16_t buffered = 0;
volatile bool playing = false;
volatile uint16_t sampleTicks = 0;
uint16_t firstSampleTick = 0;

ISR(TIMER1_COMPA_vect) {
  ++sampleTicks;
  if (!playing) {
    return;
  }

  if (buffered > 0) {
    OCR0B = audioBuffer[readIndex];  // OC0B 对应 D5，不能使用 D10 的 OCR1B。
    readIndex = (readIndex + 1) % BUFFER_SIZE;
    --buffered;
  } else {
    OCR0B = 128;
    playing = false;
  }
}

void setup() {
  pinMode(BUZZER_PIN, OUTPUT);
  Serial.begin(115200);

  ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
    // Timer0：8 位快速 PWM、不分频，16 MHz / 256 = 62.5 kHz。
    TCCR0A = 0;
    TCCR0B = 0;
    TIMSK0 = 0;  // 关闭 Arduino 原有的 Timer0 溢出中断，避免高频中断干扰音频。
    TCNT0 = 0;
    OCR0B = 128;  // 无符号 PCM 的静音中点。
    TCCR0A = _BV(COM0B1) | _BV(WGM01) | _BV(WGM00);
    TCCR0B = _BV(CS00);

    // Timer1：CTC 模式，不分频。16 MHz / (1999 + 1) = 8000 Hz。
    TCCR1A = 0;
    TCCR1B = 0;
    TIMSK1 = 0;
    TCNT1 = 0;
    OCR1A = F_CPU / SAMPLE_RATE - 1;
    TIFR1 = _BV(OCF1A);
    TIMSK1 = _BV(OCIE1A);
    TCCR1B = _BV(WGM12) | _BV(CS10);
  }
}

void loop() {
  while (Serial.available() > 0) {
    bool hasRoom;
    ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
      hasRoom = buffered < BUFFER_SIZE;
    }
    if (!hasRoom) {
      break;
    }

    audioBuffer[writeIndex] = static_cast<uint8_t>(Serial.read());
    writeIndex = (writeIndex + 1) % BUFFER_SIZE;
    // 先写入样本，再原子地发布计数，避免采样中断读到尚未写完的数据。
    ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
      if (buffered == 0 && !playing) {
        firstSampleTick = sampleTicks;
      }
      ++buffered;
    }
  }

  ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
    // 即使不足预缓冲长度，20 ms 后也开始播放短片段。
    if (!playing && buffered > 0 &&
        (buffered >= PREBUFFER_SAMPLES ||
         static_cast<uint16_t>(sampleTicks - firstSampleTick) >= PREBUFFER_TIMEOUT_TICKS)) {
      playing = true;
    }
  }
}

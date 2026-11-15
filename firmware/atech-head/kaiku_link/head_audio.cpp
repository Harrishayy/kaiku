// head_audio implementation. See head_audio.h for the wire format, the numbers and who calls what.
// Three tasks touch this file: the main loop (MQTT callback -> speakerPush, micFrame -> publish), the speaker task
// created here (ring -> Speaker::writeSamples) and the Atech capture task (micCapture). Each ring has one writer and
// one reader and a spinlock around the few lines that move its indices.
#include "head_audio.h"
#include <math.h>

#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

namespace head_audio {
namespace {

HeadAudioIO io = {nullptr, nullptr, nullptr};
Stats st = {};

// ---------------------------------------------------------------- speaker: main loop -> ring -> speaker task -> I2S
portMUX_TYPE spkMux = portMUX_INITIALIZER_UNLOCKED;
int16_t spkRing[SPK_RING_SAMPLES];
int spkRead = 0;                      // next sample to play (guarded by spkMux)
volatile int spkCount = 0;            // samples waiting (guarded by spkMux for writes)
volatile bool spkSounding = false;    // PCM is on its way out of the amplifier
volatile uint32_t spkQuietAt = 0;     // millis() when it last went quiet

int spkPop(int16_t* out, int max) {
  portENTER_CRITICAL(&spkMux);
  int n = spkCount < max ? spkCount : max;
  int first = SPK_RING_SAMPLES - spkRead;
  if (first > n) first = n;
  memcpy(out, spkRing + spkRead, (size_t)first * 2);
  memcpy(out + first, spkRing, (size_t)(n - first) * 2);
  spkRead = (spkRead + n) % SPK_RING_SAMPLES;
  spkCount -= n;
  portEXIT_CRITICAL(&spkMux);
  return n;
}

// The only place that writes PCM to the amplifier. It blocks inside io.write while the driver's I2S buffer is full,
// which paces it to real time; the main loop never waits for audio.
void spkTask(void*) {
  static int16_t buf[FRAME_SAMPLES];
  static const int16_t zeros[SPK_DMA_BLOCK] = {0};
  const int prebuffer = (int)(SPK_PREBUFFER_MS * RATE_HZ / 1000);
  const int32_t gain = (int32_t)(SPK_GAIN * 256.0f + 0.5f);
  bool playing = false;     // a sound is being fed to the driver
  int tail = 0;             // blocks of zeros still owed after the last sound
  bool waiting = false;     // frames of the next sound are collecting (prebuffer)
  uint32_t firstAt = 0;     // when the first of them arrived
  uint32_t endAt = 0;       // estimate: when the last sample written leaves the I2S buffer
  uint32_t frac = 0;        // samples not yet counted into endAt (16 samples = 1 ms)
  for (;;) {
    uint32_t now = millis();
    int have = spkCount;
    if (playing) {
      if (have > 0) {
        int n = spkPop(buf, FRAME_SAMPLES);
        if (gain > 256) {           // louder: soft limiter, x * SPK_GAIN for quiet samples, peaks rounded to full scale
          for (int i = 0; i < n; i++) buf[i] = (int16_t)(32767.0f * tanhf(buf[i] * (SPK_GAIN / 32768.0f)));
        } else if (gain != 256) {   // quieter: plain scaling
          for (int i = 0; i < n; i++) buf[i] = (int16_t)(((int32_t)buf[i] * gain) >> 8);
        }
        io.write(buf, n);
        now = millis();
        if ((int32_t)(endAt - now) < 0) { endAt = now; frac = 0; }
        frac += (uint32_t)n;
        endAt += frac / (RATE_HZ / 1000);
        frac %= (RATE_HZ / 1000);
        continue;
      }
      if ((int32_t)(endAt - now) > (int32_t)SPK_DRY_MS) {   // the I2S buffer still holds sound: the next frame is due
        vTaskDelay(pdMS_TO_TICKS(2));
        continue;
      }
      playing = false;                                       // ran dry: the sound ended, or the network starved it
      st.spkDry++;
      tail = SPK_DMA_BLOCKS;
      spkQuietAt = now + SPK_DRY_MS + 16;
      spkSounding = false;
      continue;
    }
    if (have > 0) {
      if (!waiting) { waiting = true; firstAt = now; }
      if (have >= prebuffer || now - firstAt >= SPK_PREBUFFER_MS) {
        // From idle the driver's write position sits somewhere in the middle of an old buffer: one block of zeros
        // first, so it is silence, not the start of the sound, that lands there.
        if (tail <= 0) io.write(zeros, SPK_DMA_BLOCK);
        tail = 0;
        waiting = false;
        playing = true;
        spkSounding = true;
        endAt = millis();
        frac = 0;
        continue;
      }
    } else {
      waiting = false;
    }
    if (tail > 0) {   // silence on underrun: overwrite one whole I2S cycle so no old buffer is played a second time
      io.write(zeros, SPK_DMA_BLOCK);
      tail--;
      continue;
    }
    vTaskDelay(pdMS_TO_TICKS(have > 0 ? 2 : 5));
  }
}

// ---------------------------------------------------------------- microphone: capture task -> ring -> main loop
portMUX_TYPE micMux = portMUX_INITIALIZER_UNLOCKED;
int16_t micRing[MIC_RING_SAMPLES];
int micRead = 0;                      // guarded by micMux
volatile int micCount = 0;            // guarded by micMux for writes
volatile bool micOn = false;
volatile uint32_t micHeldAt = 0;
volatile uint16_t micPeak = 0;

void micClear() {
  portENTER_CRITICAL(&micMux);
  micRead = 0;
  micCount = 0;
  portEXIT_CRITICAL(&micMux);
}

bool micArmed() { return micOn && millis() - micHeldAt <= MIC_HOLD_MS; }

// Runs on the Atech capture task for every block (512 samples, 32 ms). The filter always runs so it has no jump
// when the microphone opens; samples are KEPT only while the hub holds the microphone open and the speaker is quiet.
void micCapture(const int16_t* x, int n, void*) {
  static int16_t tmp[512];
  static int32_t x1 = 0, acc = 0;   // acc = the filter's output with 8 fraction bits (plain rounding left a DC offset)
  if (n > 512) n = 512;
  int32_t peak = 0;
  for (int i = 0; i < n; i++) {
    acc = ((int32_t)x[i] - x1) * 256 + (int32_t)(((int64_t)acc * 31785) >> 15);   // high-pass, about 75 Hz: no DC, less rumble
    x1 = x[i];
    int32_t v = (int32_t)(((int64_t)acc * MIC_GAIN + 128) >> 8);
    v = v > 32767 ? 32767 : v < -32768 ? -32768 : v;
    tmp[i] = (int16_t)v;
    if (v < 0) v = -v;
    if (v > peak) peak = v;
  }
  if (!micArmed()) return;
  if (speakerBusy() || speakerQuietMs() < MIC_TAIL_MS || (io.toneBusy && io.toneBusy())) return;   // half-duplex
  portENTER_CRITICAL(&micMux);
  if (micCount + n > MIC_RING_SAMPLES) {
    portEXIT_CRITICAL(&micMux);
    st.micDropped++;
    return;
  }
  int w = (micRead + micCount) % MIC_RING_SAMPLES;
  int first = MIC_RING_SAMPLES - w;
  if (first > n) first = n;
  memcpy(micRing + w, tmp, (size_t)first * 2);
  memcpy(micRing, tmp + first, (size_t)(n - first) * 2);
  micCount += n;
  portEXIT_CRITICAL(&micMux);
  if (peak > micPeak) micPeak = (uint16_t)peak;
}

}  // namespace

void begin(const HeadAudioIO& hooks) {
  io = hooks;
  spkQuietAt = millis() - 60000;
  if (io.write) xTaskCreatePinnedToCore(spkTask, "kaiku_pcm", SPK_TASK_STACK, nullptr, SPK_TASK_PRIO, nullptr, SPK_TASK_CORE);
  if (io.micTap) io.micTap(micCapture, nullptr);
}

void speakerPush(const uint8_t* pcm, size_t len) {
  if (len == 0) {
    st.spkFlushes++;
    speakerDrop();
    return;
  }
  int n = (int)(len / 2);
  if ((len & 1) || !io.write) {
    st.spkDropped++;
    return;
  }
  portENTER_CRITICAL(&spkMux);
  if (spkCount + n > SPK_RING_SAMPLES) {   // full: the newest message goes, what is already queued plays on
    portEXIT_CRITICAL(&spkMux);
    st.spkDropped++;
    return;
  }
  int w = (spkRead + spkCount) % SPK_RING_SAMPLES;
  int first = SPK_RING_SAMPLES - w;
  if (first > n) first = n;
  memcpy(spkRing + w, pcm, (size_t)first * 2);            // little-endian on the wire and on the ESP32
  memcpy(spkRing, pcm + (size_t)first * 2, (size_t)(n - first) * 2);
  spkCount += n;
  portEXIT_CRITICAL(&spkMux);
  st.spkFrames++;
}

size_t speakerDrop() {
  portENTER_CRITICAL(&spkMux);
  size_t n = (size_t)spkCount;
  spkRead = 0;
  spkCount = 0;
  portEXIT_CRITICAL(&spkMux);
  return n;   // what the driver already holds (up to one I2S cycle, 128 ms) still plays out
}

bool speakerBusy() { return spkCount > 0 || spkSounding; }

uint32_t speakerQuietMs() {
  if (speakerBusy()) return 0;
  int32_t d = (int32_t)(millis() - spkQuietAt);
  return d < 0 ? 0 : (uint32_t)d;
}

int speakerBufferedMs() { return spkCount / (RATE_HZ / 1000); }

void micHold(bool open) {
  if (open) {
    if (!micOn) micClear();
    micHeldAt = millis();
    micOn = true;
  } else {
    micOn = false;
    micClear();
  }
}

bool micOpen() {
  if (micOn && millis() - micHeldAt > MIC_HOLD_MS) micHold(false);   // the hub went quiet: close by ourselves
  return micOn;
}

bool micFrame(uint8_t* out) {
  if (!micOpen()) return false;   // nothing leaves the head unless the hub holds the microphone open
  portENTER_CRITICAL(&micMux);
  if (micCount < FRAME_SAMPLES) {
    portEXIT_CRITICAL(&micMux);
    return false;
  }
  int first = MIC_RING_SAMPLES - micRead;
  if (first > FRAME_SAMPLES) first = FRAME_SAMPLES;
  memcpy(out, micRing + micRead, (size_t)first * 2);
  memcpy(out + (size_t)first * 2, micRing, (size_t)(FRAME_SAMPLES - first) * 2);
  micRead = (micRead + FRAME_SAMPLES) % MIC_RING_SAMPLES;
  micCount -= FRAME_SAMPLES;
  portEXIT_CRITICAL(&micMux);
  st.micFrames++;
  return true;
}

Stats stats() {
  Stats s = st;
  s.micPeak = micPeak;
  micPeak = 0;
  return s;
}

}  // namespace head_audio

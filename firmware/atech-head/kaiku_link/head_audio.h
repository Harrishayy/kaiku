// head_audio: the head's speaker and microphone as two PCM streams over MQTT (plan 07 §4), shared by the three
// programs that use them: this MQTT firmware (kaiku_link.cpp), the standalone ritual (../standalone/src/kaiku_net.cpp;
// its build.sh copies these two files in) and the bench part (../bench/speaker_pcm).
//
// Wire format, both directions (binary, QoS 0, not retained, never an envelope):
//   kaiku/v1/<home>/audio/head/speaker   hub -> head   signed 16-bit little-endian mono 16 000 Hz, 20 ms = 320 samples
//   kaiku/v1/<home>/audio/head/mic       head -> hub   = 640 bytes a message; a zero-length speaker message = drop
//
// Speaker: frames go into a 0.5 s ring; a task of its own (never the main loop) feeds them to the Atech Speaker
// driver's own sample call (Speaker::writeSamples: I2S_NUM_0, 16 kHz, 16-bit, mono copied to both channels, 8 x 256
// frame DMA = 128 ms, scaled by the driver's volume). Ring full -> the NEWEST message is dropped. Nothing to play ->
// the task writes one DMA cycle of zeros, so the amplifier gets silence and no old buffer is played again.
// Microphone: the Atech Microphone driver's capture tap (Microphone::onAudio: I2S_NUM_1, 16 kHz, 512 samples every
// 32 ms, top 16 bits of the ICS-43434's 24) is high-passed, amplified and kept ONLY while the hub holds the
// microphone open and the speaker is quiet; the main loop takes 640-byte frames with micFrame() and publishes them.
//
// No Atech class is named here: the three hooks in HeadAudioIO are filled in by whoever owns the driver objects.
#pragma once

#include <Arduino.h>

struct HeadAudioIO {
  void (*write)(const int16_t* samples, int count);   // blocking: `count` mono 16 kHz samples to the amplifier
  bool (*toneBusy)();                                 // the tone driver is sounding (may be null)
  void (*micTap)(void (*cb)(const int16_t* samples, int count, void* ctx), void* ctx);   // gap-free capture (may be null)
};

namespace head_audio {

// ---- the wire format (fixed with the hub; do not change one side alone)
constexpr int RATE_HZ = 16000;
constexpr int FRAME_SAMPLES = 320;                    // 20 ms
constexpr int FRAME_BYTES = FRAME_SAMPLES * 2;        // 640

// ---- speaker numbers (tune here)
constexpr int SPK_RING_SAMPLES = 8000;                // 0.5 s; the hub runs about 80 ms ahead, never above 120 ms
constexpr uint32_t SPK_PREBUFFER_MS = 120;            // a sound starts once this much is buffered, or this long after
                                                      // its first frame: the cushion against Wi-Fi and loop jitter
constexpr float SPK_GAIN = 1.0f;                      // PCM gain BEFORE the driver's volume (0.4 in both firmwares);
                                                      // above 1 clips at that ceiling instead of getting louder than it
constexpr int SPK_DMA_BLOCK = 256;                    // the Atech Speaker driver's I2S buffer: 8 x 256 frames
constexpr int SPK_DMA_BLOCKS = 8;                     // (atech 1.0.0a12 speaker.cpp); one cycle = 128 ms
constexpr uint32_t SPK_DRY_MS = 24;                   // ring empty and this little left in the I2S buffer = ran dry
constexpr uint32_t SPK_TASK_STACK = 4096;
constexpr int SPK_TASK_PRIO = 3;                      // above the Atech tone, mic and IMU tasks (2), far below Wi-Fi
constexpr int SPK_TASK_CORE = 0;                      // with the other audio tasks; the Arduino loop owns core 1

// ---- microphone numbers (tune here)
constexpr int MIC_RING_SAMPLES = 8000;                // 0.5 s between the capture task and the main loop
constexpr int MIC_GAIN = 8;                           // x8 (+18 dB) after the high-pass, clipped to 16 bit. NOT measured
                                                      // on the board: the test tool prints the level to tune this
constexpr uint32_t MIC_TAIL_MS = 250;                 // half-duplex: no microphone frames while the speaker sounds
                                                      // and this long after (Kaiku must not hear itself)
constexpr uint32_t MIC_HOLD_MS = 10000;               // the hub re-sends {mic: open} every 3 s; this long without one
                                                      // closes the microphone by itself

struct Stats {
  uint32_t spkFrames;    // speaker messages accepted
  uint32_t spkDropped;   // speaker messages dropped (ring full: the newest goes; or an odd size)
  uint32_t spkDry;       // times the speaker ran out of samples (every normal end of a sound counts once)
  uint32_t spkFlushes;   // zero-length messages
  uint32_t micFrames;    // microphone frames handed to the sender
  uint32_t micDropped;   // capture blocks lost because the sender was too slow (ring full)
  uint16_t micPeak;      // largest |sample| after gain since the last stats() call (0..32767)
};

void begin(const HeadAudioIO& io);

// Speaker. Call speakerPush from the MQTT callback with the raw payload (length 0 = drop what is buffered).
void speakerPush(const uint8_t* pcm, size_t len);
size_t speakerDrop();            // drops the ring; returns how many samples went
bool speakerBusy();              // PCM is buffered or still sounding
uint32_t speakerQuietMs();       // ms since the PCM went quiet (0 while busy)
int speakerBufferedMs();         // what waits in the ring

// Microphone. Frames exist only between micHold(true) and micHold(false) / MIC_HOLD_MS without a new hold.
void micHold(bool open);
bool micOpen();
bool micFrame(uint8_t* out);     // main loop: copies the next FRAME_BYTES into `out`; false when none is ready

Stats stats();                   // counters since boot; micPeak resets on read

}  // namespace head_audio

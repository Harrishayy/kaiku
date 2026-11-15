// Logic test of ../../../kaiku_link/head_audio.cpp on a computer: the real file, built against stand-ins for the few
// Arduino / FreeRTOS names it uses (stubs/), a model of the Atech Speaker driver's I2S buffer (2048 frames drained
// at 16 kHz, a write blocks while it is full) and of the Microphone driver's 512-sample capture blocks.
// It proves the ring, prebuffer, drop, silence and microphone gate rules. It proves NOTHING about the board: no I2S,
// no Wi-Fi, no sound. Run from the repo root: `make head-audio-test` (about 25 s; one check waits 10 s on purpose).
#include <atomic>
#include <cmath>
#include <cstdio>
#include <vector>
#include "head_audio.h"

using head_audio::SPK_GAIN; using head_audio::SPK_PREBUFFER_MS; using head_audio::SPK_RING_SAMPLES;
using head_audio::MIC_TAIL_MS;
// what the head plays for a sample it was sent: the same gain rule as head_audio.cpp (soft limiter above 1)
static int16_t expect(int16_t x) {
  if (SPK_GAIN > 1.0f) return (int16_t)(32767.0f * tanhf(x * (SPK_GAIN / 32768.0f)));
  int32_t g = (int32_t)(SPK_GAIN * 256.0f + 0.5f);
  return g == 256 ? x : (int16_t)(((int32_t)x * g) >> 8);
}
static const int RING_FRAMES = SPK_RING_SAMPLES / 320;
using namespace std::chrono;

static std::mutex sinkM;
static std::vector<int16_t> played;            // every sample handed to the driver, in order
static std::vector<uint32_t> playedAt;         // millis() of each write call (first sample)
static double dmaEnd = 0;                      // ms when the model's buffer runs empty
static void sinkWrite(const int16_t* s, int n) {
  for (;;) {                                   // block while the model buffer (128 ms) is full, like i2s_write
    double now = millis();
    std::unique_lock<std::mutex> l(sinkM);
    double backlog = dmaEnd > now ? dmaEnd - now : 0;
    if (backlog + n / 16.0 <= 128.0) {
      dmaEnd = (dmaEnd > now ? dmaEnd : now) + n / 16.0;
      playedAt.push_back((uint32_t)now);
      played.insert(played.end(), s, s + n);
      return;
    }
    l.unlock();
    std::this_thread::sleep_for(milliseconds(1));
  }
}
static std::atomic<bool> toneOn{false};
static bool toneBusy() { return toneOn; }
static void (*micCb)(const int16_t*, int, void*) = nullptr;
static void micTap(void (*cb)(const int16_t*, int, void*), void*) { micCb = cb; }

static int fails = 0;
#define CHECK(cond, ...) do { if (!(cond)) { fails++; printf("  FAIL %s:%d  ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)
static void sleepMs(int ms) { std::this_thread::sleep_for(milliseconds(ms)); }

// frame i of a test stream: every sample carries its own index, so order and loss show up exactly
static void frame(int i, uint8_t* out) {
  int16_t s[320];
  for (int k = 0; k < 320; k++) s[k] = (int16_t)(1 + ((i * 320 + k) % 30000));
  memcpy(out, s, 640);
}
static std::vector<int16_t> nonZero() {
  std::lock_guard<std::mutex> l(sinkM);
  std::vector<int16_t> v;
  for (int16_t x : played) if (x) v.push_back(x);
  return v;
}
static void clearSink() { std::lock_guard<std::mutex> l(sinkM); played.clear(); playedAt.clear(); }

// send frames [from, to) the way the hub does: one every 20 ms, `lead` ms ahead of the clock
static void sendPaced(int from, int to, int leadMs) {
  auto t0 = steady_clock::now();
  uint8_t f[640];
  for (int i = from; i < to; i++) {
    auto due = t0 + milliseconds((i - from) * 20 - leadMs);
    std::this_thread::sleep_until(due);
    frame(i, f);
    head_audio::speakerPush(f, 640);
  }
}

int main() {
  head_audio::begin({sinkWrite, toneBusy, micTap});
  uint8_t f[640];

  printf("1. a 6 s stream, 80 ms ahead: every sample once, in order, one dry event at the end\n");
  uint32_t tStart = millis();
  sendPaced(0, 300, 80);
  sleepMs(700);
  {
    auto v = nonZero();
    CHECK(v.size() == 300u * 320u, "played %zu samples, sent %u", v.size(), 300u * 320u);
    size_t bad = 0;
    for (size_t k = 0; k < v.size(); k++) if (v[k] != expect((int16_t)(1 + (k % 30000)))) bad++;
    CHECK(bad == 0, "%zu samples out of order", bad);
    head_audio::Stats s = head_audio::stats();
    CHECK(s.spkFrames == 300 && s.spkDropped == 0, "frames %u dropped %u", s.spkFrames, s.spkDropped);
    CHECK(s.spkDry == 1, "dry %u (want 1: the end of the sound)", s.spkDry);
    std::lock_guard<std::mutex> l(sinkM);
    size_t firstNz = 0; while (firstNz < played.size() && !played[firstNz]) firstNz++;
    size_t tailZeros = 0; for (size_t k = played.size(); k > 0 && !played[k - 1]; k--) tailZeros++;
    CHECK(firstNz == 256, "leading zeros %zu (want one block of 256)", firstNz);
    CHECK(tailZeros == 2048, "zeros after the sound %zu (want one I2S cycle, 2048)", tailZeros);
    // the hub sends five frames at once (80 ms ahead), then one every 20 ms: the prebuffer is full once
    // SPK_PREBUFFER_MS of sound is in, SPK_PREBUFFER_MS - 100 ms after the first frame
    printf("   first write at +%u ms after the first frame\n", playedAt.empty() ? 0 : playedAt[0] - tStart);
    { uint32_t want = SPK_PREBUFFER_MS - 100, got = playedAt.empty() ? 0 : playedAt[0] - tStart;
      CHECK(!playedAt.empty() && got + 5 >= want && got <= want + 25, "start delay %u ms (want about %u)", got, want); }
  }
  CHECK(!head_audio::speakerBusy(), "still busy after the end");

  printf("2. a 300 ms hole in the stream: silence, then it picks up again (two dry events)\n");
  clearSink();
  sendPaced(0, 50, 80);
  sleepMs(300 + 80);
  sendPaced(50, 100, 80);
  sleepMs(600);
  {
    auto v = nonZero();
    CHECK(v.size() == 100u * 320u, "played %zu of %u", v.size(), 100u * 320u);
    head_audio::Stats s = head_audio::stats();
    CHECK(s.spkDry == 3, "dry %u (want 3 in total)", s.spkDry);
  }

  printf("3. overflow: %d frames at once into a %d-frame ring: the NEWEST five are dropped, the rest play\n", RING_FRAMES + 5, RING_FRAMES);
  clearSink();
  {
    head_audio::Stats a = head_audio::stats();
    for (int i = 0; i < RING_FRAMES + 5; i++) { frame(i, f); head_audio::speakerPush(f, 640); }
    head_audio::Stats b = head_audio::stats();
    printf("   accepted %u, dropped %u\n", b.spkFrames - a.spkFrames, b.spkDropped - a.spkDropped);
    CHECK(b.spkFrames - a.spkFrames + b.spkDropped - a.spkDropped == (uint32_t)RING_FRAMES + 5, "accepted + dropped != %d", RING_FRAMES + 5);
    CHECK(b.spkDropped - a.spkDropped >= 4 && b.spkDropped - a.spkDropped <= 5, "dropped %u (want 5, or 4 if the task took a frame meanwhile)", b.spkDropped - a.spkDropped);
    sleepMs(RING_FRAMES * 20 + SPK_PREBUFFER_MS + 300);
    auto v = nonZero();
    size_t bad = 0;
    for (size_t k = 0; k < v.size(); k++) if (v[k] != expect((int16_t)(1 + (k % 30000)))) bad++;
    CHECK(bad == 0 && v.size() == (size_t)(b.spkFrames - a.spkFrames) * 320, "after overflow: %zu samples, %zu wrong", v.size(), bad);
  }

  printf("4. drop: 20 frames at once, then a zero-length message: the ring is emptied, at most 128 ms plays on\n");
  clearSink();
  {
    for (int i = 0; i < 20; i++) { frame(i, f); head_audio::speakerPush(f, 640); }
    sleepMs(30);
    int before = head_audio::speakerBufferedMs();
    head_audio::speakerPush(f, 0);
    CHECK(head_audio::speakerBufferedMs() == 0, "ring not empty after the drop");
    sleepMs(500);
    auto v = nonZero();
    printf("   %d ms waited in the ring at the drop; %zu ms had gone to the driver and played\n", before, v.size() / 16);
    CHECK(v.size() / 16 <= 30 + 128 + 20, "played %zu ms in all (30 ms before the drop + at most one I2S cycle after)", v.size() / 16);
    CHECK(head_audio::stats().spkFlushes == 1, "flush not counted");
    CHECK(!head_audio::speakerBusy(), "busy after a drop");
  }

  printf("5. odd-sized message is refused\n");
  { head_audio::Stats a = head_audio::stats(); head_audio::speakerPush(f, 639); CHECK(head_audio::stats().spkDropped == a.spkDropped + 1, "odd size accepted"); }

  // ---- microphone: a capture thread delivering 512 samples every 32 ms, like the Atech driver
  std::atomic<bool> run{true};
  std::thread cap([&] {
    int16_t blk[512]; long n = 0;
    auto t = steady_clock::now();
    while (run) {
      for (int k = 0; k < 512; k++, n++) blk[k] = (int16_t)(500 + 100.0 * sin(2 * M_PI * 1000.0 * n / 16000.0));   // DC 500 + 1 kHz, amplitude 100
      micCb(blk, 512, nullptr);
      t += milliseconds(32);
      std::this_thread::sleep_until(t);
    }
  });
  auto drain = [&](int ms, std::vector<int16_t>* keep = nullptr) {
    int frames = 0; auto end = steady_clock::now() + milliseconds(ms);
    while (steady_clock::now() < end) {
      while (head_audio::micFrame(f)) { frames++; if (keep) { int16_t s[320]; memcpy(s, f, 640); keep->insert(keep->end(), s, s + 320); } }
      sleepMs(1);
    }
    return frames;
  };

  printf("6. microphone closed: not one frame leaves\n");
  sleepMs(400);   // past the half-duplex tail of test 4
  CHECK(drain(500) == 0, "frames while closed");

  printf("7. open for 2 s: about 100 frames, DC gone, level = gain x input\n");
  {
    head_audio::micHold(true);
    std::vector<int16_t> got;
    int n = drain(2000, &got);
    printf("   %d frames in 2 s\n", n);
    CHECK(n >= 95 && n <= 101, "%d frames in 2 s (want about 100)", n);
    double mean = 0, peak = 0;
    for (size_t k = 1600; k < got.size(); k++) mean += got[k];   // skip the filter's first 100 ms
    mean /= (got.size() - 1600);
    for (size_t k = 1600; k < got.size(); k++) if (fabs(got[k] - mean) > peak) peak = fabs(got[k] - mean);
    printf("   mean %.1f, peak %.0f (input: DC 500, amplitude 100, gain %d)\n", mean, peak, head_audio::MIC_GAIN);
    CHECK(fabs(mean) < 5, "DC left: %.1f", mean);
    CHECK(peak > 0.9 * 100 * head_audio::MIC_GAIN && peak < 1.1 * 100 * head_audio::MIC_GAIN, "peak %.0f", peak);
  }

  printf("8. half-duplex: no frames captured while the speaker plays, nor for %u ms after\n", MIC_TAIL_MS);
  {
    drain(50);
    std::thread spk([&] { sendPaced(0, 50, 80); });      // 1 s of sound
    sleepMs(100);                                         // frames captured before the sound may still be in the ring
    drain(60);
    int during = drain(700);                              // well inside the sound
    spk.join();
    while (head_audio::speakerBusy()) sleepMs(5);
    uint32_t quietAt = millis();
    int early = drain(150);                               // inside the tail
    int waited = 0; while (!head_audio::micFrame(f) && waited < 1000) { sleepMs(1); waited++; }
    uint32_t backAt = millis();
    printf("   during the sound: %d frames; first 150 ms after: %d; first frame %u ms after it went quiet\n", during, early, backAt - quietAt);
    CHECK(during == 0, "%d frames during playback", during);
    CHECK(early == 0, "%d frames inside the tail", early);
    CHECK(backAt - quietAt >= MIC_TAIL_MS && backAt - quietAt <= MIC_TAIL_MS + 32 + 40 + 60, "microphone back after %u ms", backAt - quietAt);
  }

  printf("9. the tone driver sounding also mutes the microphone\n");
  { toneOn = true; sleepMs(80); drain(40); int n = drain(300); toneOn = false; CHECK(n == 0, "%d frames during a tone", n); CHECK(drain(300) > 5, "no frames after the tone"); }

  printf("10. close: nothing after it, even with samples waiting\n");
  { head_audio::micHold(false); CHECK(!head_audio::micOpen(), "still open"); CHECK(drain(300) == 0, "frames after close"); }

  printf("11. no new hold for 10 s: the microphone closes by itself (takes 10 s)\n");
  {
    head_audio::micHold(true);
    int n1 = drain(9500);
    CHECK(head_audio::micOpen(), "closed too early");
    drain(700);
    CHECK(!head_audio::micOpen(), "still open after 10.2 s without a hold");
    int n2 = drain(500);
    printf("   %d frames in the first 9.5 s, %d after the hold ran out\n", n1, n2);
    CHECK(n1 > 450 && n2 == 0, "frames %d / %d", n1, n2);
  }
  run = false; cap.join();
  printf(fails ? "\n%d CHECK(S) FAILED\n" : "\nall checks passed\n", fails);
  return fails ? 1 : 0;
}

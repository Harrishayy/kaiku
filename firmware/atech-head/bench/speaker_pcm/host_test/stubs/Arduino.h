// Stand-in for the few Arduino names head_audio.cpp uses, so its logic can run on a computer (host_test only).
#pragma once
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <thread>
inline uint32_t millis() {
  static const auto t0 = std::chrono::steady_clock::now();
  return (uint32_t)std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - t0).count() + 5000;
}

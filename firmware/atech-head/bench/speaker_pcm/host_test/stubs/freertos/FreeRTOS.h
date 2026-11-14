#pragma once
#include <Arduino.h>
struct portMUX_TYPE { std::mutex m; };
#define portMUX_INITIALIZER_UNLOCKED {}
#define portENTER_CRITICAL(mux) (mux)->m.lock()
#define portEXIT_CRITICAL(mux) (mux)->m.unlock()
#define pdMS_TO_TICKS(ms) (ms)
inline void vTaskDelay(int ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); }
inline int xTaskCreatePinnedToCore(void (*fn)(void*), const char*, uint32_t, void* arg, int, void*, int) {
  std::thread(fn, arg).detach();
  return 1;
}

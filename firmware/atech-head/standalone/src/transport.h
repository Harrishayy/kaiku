#pragma once
#include <Arduino.h>
struct P2PCommand { char action[48]; char value[200]; bool truncated; };
inline void p2p_transport_setup() {}
inline void p2p_transport_loop() {}
bool p2p_next_command(P2PCommand *out);
uint32_t p2p_ms_since_command();
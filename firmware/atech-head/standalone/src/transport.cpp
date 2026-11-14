#include "transport.h"
static char line[1024]; static size_t len = 0;
static bool seen = false; static uint32_t atMs = 0;

static bool field(const char *s, const char *key, char *dst, size_t cap) {
  char pat[16]; snprintf(pat, sizeof pat, "\"%s\"", key);
  const char *p = strstr(s, pat); if (!p) return false;
  p = strchr(p + strlen(pat), ':'); if (!p) return false;
  p++; while (*p == ' ') p++;
  size_t n = 0;
  if (*p == '"') { p++;
    while (*p && *p != '"' && n + 1 < cap) { if (*p == '\\' && p[1]) p++; dst[n++] = *p++; }
  } else {
    while (*p && *p != ',' && *p != '}' && n + 1 < cap) dst[n++] = *p++;
    while (n && dst[n-1] == ' ') n--;
  }
  dst[n] = 0; return true;
}

bool p2p_next_command(P2PCommand *out) {
  while (Serial.available() > 0) {
    int c = Serial.read();
    if (c == '\r') continue;
    if (c != '\n') { if (len < sizeof line - 1) line[len++] = (char)c; continue; }
    line[len] = 0; len = 0;
    const char *s = line; while (*s == ' ') s++;
    if (!*s) continue;
    out->truncated = false; out->value[0] = 0;
    if (*s == '{' && field(s, "action", out->action, sizeof out->action))
      field(s, "value", out->value, sizeof out->value);
    else { strncpy(out->action, s, sizeof out->action - 1); out->action[sizeof out->action - 1] = 0; }
    seen = true; atMs = millis(); return true;
  }
  return false;
}
uint32_t p2p_ms_since_command() { return seen ? millis() - atMs : 0xFFFFFFFFu; }
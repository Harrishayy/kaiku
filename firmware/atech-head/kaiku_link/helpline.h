// The three lines the head shows on its own screen when the hub's crisis path sends cmd.head {show: "help"}:
// the helpline's name, its number, and the emergency number. Public numbers, not secrets.
// They MUST equal config/kaiku.toml [safety] helpline_name / helpline_number / emergency_number (the hub prints the
// same three): firmware/atech-head/tests/test_helpline.py, part of `make test`, fails when they differ.
// Shared by the MQTT firmware (config.h includes this), the standalone (build.sh copies it) and bench/speaker_pcm.
#pragma once

#define HELPLINE_NAME "MIELI Crisis Helpline"
#define HELPLINE_NUMBER "09 2525 0111"
#define EMERGENCY_NUMBER "112"

#define HELP_SHOW_MS 600000UL   // the help screen leaves by itself after 10 minutes (or on {show: "none"})

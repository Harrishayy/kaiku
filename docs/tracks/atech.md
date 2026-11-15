# Atech Real World Challenge (Atech) — tech challenge

Brief as given on the Junction 2026 challenge page, copied 15 November 2026. The platform redemption code and the
contacts' e-mail addresses are left out (public repository); they are on the challenge page in the Junction app.

## The challenge: the API for the physical world
AI made software something anyone can build in an afternoon. Hardware is next. Wiring, drivers and firmware used to
eat a whole hackathon before anything blinked; with Atech you describe what you want, snap the modules together and
flash working firmware from your browser.

Build a physical device that solves a real problem for a real person, using Atech modules as its body and AI as its
brain. Pick someone (a farmer, a nurse, a cyclist, your grandmother, your flatmate) and give them a device that
senses, reacts or connects in a way software alone can't. Use Atech to go from idea to a working prototype on the
table, then spend your remaining hours on what makes it great. Using Atech hardware is required; how you combine it
with other tools, APIs and models is up to you.

## Minimum requirements
- Atech modules used in the demo alongside a real-world solution.
- A link to a summary or post about it shared in Atech's Discord.

## Submission requirements
- Live demo on the hardware.
- Public GitHub repo or exported Atech project.
- A video or live demo of about 2 minutes.

## Inspiration
- Assistive devices: fall detection, posture coaching, smart reminders for people living alone.
- Sustainability: sensing energy, water, air quality or food waste and acting on it.
- Physical AI: put an LLM or vision model in a loop with real sensors and actuators.
- Robotics: give a robot arm or rover new senses with distance, IMU or climate modules.
- Tools for makers, labs and classrooms that make building hardware even easier.

## The technology
Atech is a kit of snap-together ESP32-based electronic modules (sensors, motion, connectivity) plus an AI platform
that writes the firmware. You describe the device in plain language; Atech plans it, generates the code, builds it
and flashes it to the hardware from the browser. No breadboards, no soldering, no driver hunting.

- Modules snap together: distance, IMU, temperature and humidity, air quality, microphone, speakers, motors, more.
- Build from atech.dev and flash from the browser over USB (Chrome or Edge, WebSerial).
- Python library: `pip install atech`, usable from any coding agent.
- An emulator for testing before touching hardware.
- Devices connect over Wi-Fi or Bluetooth, giving an API to your AI set-up.

Tech profile: natural language in; generated C/C++ firmware (PlatformIO / ESP32), editable by hand; Python library
for coding agents. Firmware generation needs internet; flashed devices run standalone. Kits are limited, 2 to 4 per
team, first come first served, returned after the final demos.

## Tips and pitfalls
- Chrome or Edge only for browser flashing.
- A data USB cable, not a charge-only one.
- Start with one module working, then add the next; describe changes step by step.
- On Linux, add your user to the `dialout` group if the board doesn't show up.

## Support
- Docs: atech.dev/docs. Starter repos: github.com/atechdotdev.
- `#atech` on the Junction Discord, the Atech booth and Atech's own Discord; mentors throughout, with a night shift.
- A main contact and a technical contact from Atech.

## Judging criteria
| Criterion | Weight | Question |
|---|---|---|
| Real-world validation of usefulness | 25% | Evidence it's genuinely useful: tested with real users, experts or real-world data. |
| Real-world impact | 25% | A real user and a real problem, solved convincingly. |
| Use of Atech | 25% | How well and how creatively the hardware and AI platform were used. |
| Working demo and storytelling | 25% | It runs live on the hardware in front of the judges, with a clear story and pitch. |
| Bonus | 0% | Extra credit for combining several modules, or connecting the device to AI models and external APIs. |

## Prizes
Winner: a Pro Atech kit for the team. Runners-up: Atech kits and swag. Top teams are invited to show their project
on Atech's channels and to visit Atech in Copenhagen.

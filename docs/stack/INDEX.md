# The stack, piece by piece

Kaiku is built on six partner technologies. Each has its own page here, written from the code on 15 November
2026, with the same five parts: what we use and how, what has actually run (with dates and measured numbers),
whether it was the right choice for a person at home after TMS treatment, and how it joins the
other five.

| Page | The one-line version |
|---|---|
| [Gemini API](gemini.md) | Gemini Live is Kaiku's one voice on phone, Mac, glasses and robot; its function calls move a ritual, a walk and a card; six more Gemini models each do one job |
| [Gemma](gemma.md) | Gemma 4 reasons over the record in eight jobs; code checks every answer; a trace shows where a model was involved and where it was overruled |
| [Modal](modal.md) | The whole cloud: one warm container for API, dashboard and database; three schedules; a `.map()` simulation; Gemma on an H100 that scales to zero |
| [Meta AI glasses](meta-glasses.md) | A walk companion in the ear through the Device Access Toolkit and Bluetooth, with opt-in seeing and a walk that survives the glasses coming off |
| [Atech](atech.md) | The robot's head on one 14-port board: ear dial, taps from the orientation sensor, neck motor, and a live voice as audio frames over MQTT |
| [Arduino UNO Q](arduino-uno-q.md) | The robot's eyes: a camera read on the board itself, only numbers leave it. A face woke the head board to board (14 Nov). Since D61 the camera stays closed until she says yes, so the ear wakes the robot. |

These pages are views. The ground truth stays where the root [`AGENTS.md`](../../AGENTS.md) says it is: the
module docs, the config files and [`decisions.md`](../decisions.md). Where an older page of this repo
disagrees with a stack page, the code decided.

## Why these six, together

The problem has a shape, and each technology covers one side of it.

- **A person with little energy will not report.** So Kaiku has to come to them, by voice
  ([Gemini Live](gemini.md)), on things they already live with: a phone, a pair of glasses
  ([Meta](meta-glasses.md)), and something on the desk that turns to look at them
  ([Atech](atech.md), [UNO Q](arduino-uno-q.md)).
- **One signal is thin.** So every device sends small derived observations to one place
  ([Modal](modal.md)), where a fixed rule compares each kind with the person's own usual.
- **A practitioner needs reasons, not a score.** So an open model reads the record and says what changed
  ([Gemma](gemma.md)), and code makes every sentence checkable.
- **None of it may be trusted blindly.** So the state and the crisis path are deterministic everywhere, and no
  raw media is kept by the product.

## One sentence through all six

It is morning. This is the path of one moment, and each step is real code.

1. **Atech.** She presses the robot's ear and it wakes. (A face woke the head board to board on 14 Nov. Since
   D61 the camera stays closed until she says yes, so the ear wakes the robot.)
2. **UNO Q.** Kaiku asks once whether its camera may be on. After her yes the board finds her face and publishes
   where it is: a few numbers, no picture (`raw.hub.face`).
3. **Gemini Live.** The hub opens a conversation; Kaiku's voice travels to the head's speaker as 20 ms audio
   frames. She says she slept badly and misses her sister.
4. **Modal.** The voice calls its `feel` tool. The call lands on the one Modal container, where the crisis gate
   reads it first and code answers with a plan: stay, comfort, and at most one offer.
5. **Gemma.** She asks what helped last time. The voice calls `ask_mind`; the cloud looks in her own notebook,
   then asks Gemma, and checks the answer for citations and for any number or state word before it is spoken.
6. **Atech again.** She agrees to the check-in and turns the ear three times. The hub turns each confirmed
   answer into an observation and uploads only those.
7. **Meta glasses.** In the afternoon the phone shows the walk she agreed to. In the glasses, the same voice
   knows about her sister, and with her permission can see the lake she is looking at.
8. **Modal and Gemma.** The fixed rule compares today's mood, sleep, drum and walk with her own usual. If two
   signal groups are worse, the dashboard says "needs a call", and Gemma's review tells the practitioner what
   changed, citing the records, with a trace of every step.

What has run, and where (the stack pages give the dates and the numbers):

- **On the real boards:** an ear press opening a Gemini Live conversation through the head's speaker with a phone
  as its microphone, and her spoken yes to the camera arriving as a tool call (15 Nov); the dial answers by knob;
  the UNO Q's face numbers on the broker and a face waking the head (14 Nov, an earlier firmware, before D61).
- **On real glasses:** registration, the self-test and a walk that sent 30 frames and heard the wearer (15 Nov).
  Kaiku's replies have not yet been heard in the glasses.
- **With real model calls on a simulated record:** steps 4, 5 and 8 (`feel`, `ask_mind`, the review), from a test
  client or the software twin.
- **Not yet seen on the robot:** the camera opening on her yes (the tool call arrived; the camera's part was
  written the same day), agreeing to the check-in in words (D66) and asking twice for an activity (D58). Both
  rules are tested in code and on the twin; no person has tried them on the robot.

## What made the integration possible

- **One contract.** Every device speaks the same envelope and message types
  ([`contracts/`](../../contracts/AGENTS.md)): MQTT at home, HTTPS to the cloud. No module imports another.
- **A twin for every device.** Each hardware node has a software twin that speaks the same messages
  ([`sim/`](../../sim/AGENTS.md)), so the cloud, the voice and the dashboard were built before the hardware was
  ready and can be run by anyone without it.
- **One tool registry.** The same list of 18 voice tools serves all four bodies
  ([`companion_tools.py`](../../contracts/python/kaiku_contracts/companion_tools.py)); the hub adds three
  robot-only tools (`camera_choice`, `turn_head`, `checkin`,
  [`hub/kaiku_hub/live/tools.py`](../../hub/kaiku_hub/live/tools.py)).
- **One rule file.** [`config/criteria.toml`](../../config/criteria.toml) is the whole consensus, versioned by
  its hash.

## What each stack has shown

| Stack | Shown for real |
|---|---|
| Gemini API | Live on four bodies with real calls; tools, tokens, renewal, barge-in, TTS, embeddings, Lyria through the head's twin |
| Gemma | All eight jobs' checks tested; six jobs run on real calls; review and record question also on our own GPU |
| Modal | Public deployment checked from outside; H100 cold and warm calls measured |
| Meta glasses | Registration, self-test (speaker, microphone, camera frame) and a 30-frame walk on real glasses |
| Atech | Ritual by knob with no laptop; taps, motor, MQTT, a Live conversation through the head's speaker |
| Arduino UNO Q | Camera numbers and chimes on the broker; a face waking the Atech head (14 Nov, before D61) |

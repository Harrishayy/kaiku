# Meta AI glasses in Kaiku

> Part of [the stack pages](INDEX.md). Read from the code on 15 November 2026. Module doc:
> [`apps/apple/AGENTS.md`](../../apps/apple/AGENTS.md); the real-device checklist is
> [`glasses-test.md`](../glasses-test.md). The integration is the iPhone app. The two `apps/glasses-*` folders
> hold instructions only and are not part of the entry.

**In one paragraph.** A walk is one of the best things a person can do after treatment and one of the hardest
to start. With Meta glasses paired to the iPhone, Kaiku walks along as a voice in the ear: head up, hands free,
phone in a pocket. The iPhone reaches the glasses through Meta's **Wearables Device Access Toolkit** (DAT) for
the device session, the camera and head motion, and through ordinary Bluetooth for the microphone and speakers.
The same Gemini Live conversation that started in the kitchen continues on the street, and if she chooses, it
can see what she sees. The walk becomes one derived record (minutes and steps) in the "walks and outings" signal
group that the practitioner's consensus reads.

## The integration, step by step

All DAT code is in one file, [`apps/apple/iOS/DATGlasses.swift`](../../apps/apple/iOS/DATGlasses.swift), behind
an adapter protocol ([`Glasses/GlassesAdapter.swift`](../../apps/apple/KaikuKit/Sources/KaikuKit/Glasses/GlassesAdapter.swift)),
so the walk itself does not know which glasses, real or mock, it is talking to.

| Step | What the code does |
|---|---|
| **Package** | `meta-wearables-dat-ios` pinned to exactly 1.0.1; products `MWDATCore`, `MWDATCamera`, `MWDATMotion`, and `MWDATMockDevice` in Debug builds only ([`project.yml`](../../apps/apple/project.yml)) |
| **Configure** | `Wearables.configure()` once at launch; toolkit analytics opted out in `Info.plist` |
| **Register** | An explicit button (You → Glasses, the Glasses check, or first-run setup) calls `startRegistration()`, which hands over to the Meta AI app and returns through the `kaiku://` link. It opens no microphone and starts no walk |
| **Permissions** | The camera grant lives in the Meta AI app. Kaiku checks it and asks for it only from the Glasses check screen, never in the middle of a walk; without it the walk says so in words |
| **Session** | Waits for a device, builds an `AutoDeviceSelector` (falling back to the first device), `createSession`, `start()`, then follows `stateStream()` and `errorStream()` |
| **Camera** | `addCamera(StreamConfiguration(videoCodec: .raw, resolution: .low, frameRate: 2))`: 360 × 640, two frames a second, of which at most one a second is used |
| **Motion** | `addMotion(MotionConfiguration(samplingRate: .hz30))`, batched in sixes |
| **Device state** | A listener reads link, worn or not, hinge and battery; "worn" drives what Kaiku does when the glasses come off |

Each session state has words on the walk screen: connecting, "Connect Kaiku in the Meta AI app, then come back
here", "Walking with your glasses", "Glasses are off. Kaiku waits until they are back on", and "Your glasses
went quiet. I'll keep walking with you on the phone."

## Audio: why hands-free Bluetooth

The glasses' microphones and speakers are not a DAT capability; they are a Bluetooth headset. Kaiku uses the
hands-free profile (HFP) through `AVAudioSession`
([`Voice/TalkAudio.swift`](../../apps/apple/KaikuKit/Sources/KaikuKit/Voice/TalkAudio.swift)):
`.playAndRecord`, `.voiceChat`, HFP allowed, and the HFP port set as the preferred input every time the route
changes.

HFP is mono and narrowband, and music would sound poor through it. We chose it anyway because it is the only
route that gives the **glasses' own microphone**, which is what makes the phone-in-pocket walk possible. Three
details follow from that choice:

- **Order matters.** The walk starts the conversation and its audio first, waits up to three seconds for the
  headset route to settle, and only then opens the DAT session and camera.
- **Voice activity is tuned for a headset.** The glasses' microphones are aimed at the wearer, so the Live
  session uses a more sensitive start and 800 ms of silence, instead of the loudspeaker settings.
- **A route change is said aloud to the model.** If the headset drops, Kaiku is told the conversation continues
  on the phone, and a short line on screen says the same.

One audio engine with voice processing gives echo cancellation and lets her interrupt Kaiku mid-sentence.

## "Let Kaiku see" (D43)

Seeing is a separate choice, off by default, on the walk's start screen: **"Let Kaiku see through the glasses
during walks. About one picture a second goes to the live conversation only, while you talk. Never saved, never
sent to your care team."**

- **Path.** DAT frame → at most one a second → JPEG (longest side 640 px, quality 0.6) held in memory →
  `realtimeInput.video` on that walk's Gemini Live socket. No Kaiku service has a route that accepts a frame, and
  a cloud test asserts that walk tools create no events.
- **Five gates before a frame leaves the phone**: the switch is on; "Pause everything" is off; the conversation
  is open; Kaiku is not muted; the pairing has not changed. Tested in `GlassesFrameGateTests`.
- **The screen tells the truth.** "Kaiku can see · n pictures sent, none saved" appears only once a frame was
  really sent. After eight seconds without a frame it changes to paused. The end of the walk says how many
  pictures Kaiku saw.
- **The model is told the truth too.** It receives `[glasses camera on]` and `[glasses camera off · you cannot
  see now]`, and its `look_at_this` tool answers "you cannot see" unless a frame from the last three seconds
  was sent. With the switch off, Kaiku says it cannot see.
- **What a view is used for.** Her outdoor favourites (up to four, from her own notebook) travel with the walk,
  so a view can become "Is that your favourite tree up there?". It asks, because a model cannot know it is that
  tree. A new favourite is kept only from her own words.
- **What a view is never used for.** No observation, state or crisis trigger is derived from a picture. We
  rejected deriving daylight minutes from frames: an auto-exposed picture is not a light measurement. The
  persona forbids describing, identifying or judging people in view; that is a rule in the prompt, checked by a
  test for its presence, not a technical filter.

A lesson from the real glasses: the camera stream needs the toolkit's Bluetooth Classic route when the phone is
a Personal Hotspot. Without `UISupportedExternalAccessoryProtocols: com.meta.ar.wearable` and the
`external-accessory` background mode, the stream waited forever for the device. Raw frames also arrive only
while the app is in front: with the phone locked the voice continues and seeing pauses, and the screen says so.

## The walk itself

- **Three styles she chooses.** Calm mostly listens. Playful sets a small spotting goal and asks a little about
  her day. Chatty keeps the talk going. Each has its own word limits (8, 14 and 16 words a turn).
- **A spotting game where the phone keeps count.** Kaiku calls `set_walk_goal` ("three trees") and
  `log_walk_moment`; the phone holds the number, allows one find per thing she said, and tells Kaiku
  "2 of 3 found". She can also press "Found one" on the card, the Lock Screen or the Dynamic Island.
- **A feeling wins.** A sad sentence stops the game in any style: the persona rule sends the voice to its `feel`
  tool and it does not return to the game unless she asks.
- **Mute Kaiku.** Her captions and Kaiku's keep coming.
- **A crisis phrase ends the walk** and opens the fixed crisis screen. No model is involved.

## When the glasses come off

A walk must not end because a battery did. Three levels handle it
([`Walk/WalkModel.swift`](../../apps/apple/KaikuKit/Sources/KaikuKit/Walk/WalkModel.swift)):

- The DAT session stops or pauses → the walk stays active and Kaiku is told once that it continues on the phone.
- The Bluetooth route is lost → the conversation moves to the phone's microphone and speaker.
- The glasses are taken off → Kaiku waits quietly until they are back on.

The phone's own pedometer runs on every walk, so steps are counted either way. The end summary says whether the
voice was in the glasses or on the phone.

## What the walk leaves behind

One observation, `obs.outing`, when the walk lasted at least a minute and her walks switch is on: minutes, steps
and how the steps were counted. From the glasses' motion sensor the phone can also derive cadence, gait
regularity and how much of the walk her head was up
([`Walk/GaitAnalyzer.swift`](../../apps/apple/KaikuKit/Sources/KaikuKit/Walk/GaitAnalyzer.swift)); raw motion
never leaves the phone.

In the consensus, outing minutes and steps are the two enabled measures of the "walks and outings" signal group,
each compared with her own usual ([`config/criteria.toml`](../../config/criteria.toml)). Cadence is defined but
switched off, and gait regularity and head-up share are stored but have no vote: we did not want measures we
have not seen on real glasses to move a person's state. Not recorded at all: any picture, what was seen, the
game, or the audio.

## The Glasses check

You → Glasses check is a 20-second self-test that a person, or a judge, can run before a walk. It stores
nothing.

1. **Kaiku speaks**: one line through whatever route is active; passes only if audio really played.
2. **Say something for three seconds**: passes if the microphone heard a voice, and names which microphone.
3. **One picture from the glasses**: opens a short session, waits for the first frame, shows it on the phone
   only.

Above it, the screen lists live facts: registration, device, worn, battery, permissions, audio routes, pictures
sent.

## What has run

| Where | What | Result |
|---|---|---|
| **Real glasses**, 14 Nov | Registration through Meta AI and connection | Confirmed on the lead's glasses, Developer Mode |
| **Real glasses**, 15 Nov, phone as hotspot | Glasses check | All three steps passed: Kaiku's line played in the glasses, the glasses microphone heard the wearer, a camera frame arrived |
| **Real glasses**, 15 Nov | A walk with seeing on | 30 frames reached its Gemini Live conversation, and Kaiku heard the wearer through the glasses twice |
| **Meta's Mock Device Kit**, real Gemini Live | A 3 min 6 s walk, playful style, typed lines | 178 pictures sent on one socket; "What's that up there?" answered; a favourite remembered; a sad sentence dropped the game |
| **Mock glasses**, UI test | A walk to its record | `obs.outing` with cadence 108, regularity 0.97, head-up 0.89 from synthetic motion |
| **Real Gemini Live**, stock pictures as the view | Walk nudges | A dull road got no words in any style; a lone tree got the favourite-tree question |

## Is this the best we could have done?

**Why glasses fit this problem.** The person we are building for should look up, not at a screen. Audio in the
ear with the phone away is the least demanding interface there is, and it works for someone who cannot or will
not type. A first-person view lets a companion talk about the same world she is in, which a phone in a pocket
cannot.

**Choices we would defend.** Native iOS with DAT rather than a web view, since DAT is native-only (D24). Audio
first, camera as a second, separate consent. A walk that never depends on the glasses staying connected.
Failure states written in plain words on screen. Measures we have not verified on the device kept out of the
consensus.

## How it joins the rest

- **Glasses → Gemini Live.** Microphone, speakers and opt-in pictures feed the same conversation as every other
  body ([Gemini](gemini.md)).
- **Glasses → the mind.** A favourite place mentioned on a walk is known to the phone, the Mac and the robot
  next time ([`cloud/tests/test_walk.py`](../../cloud/tests/test_walk.py)); an activity agreed on a walk shows
  as a card on the phone and Mac (D50).
- **Glasses → the record.** The outing reaches the [Modal](modal.md) cloud, the deterministic rule compares it
  with her usual, and [Gemma](gemma.md)'s review can cite it.

# Glasses test — 5 minutes, on the real Ray-Ban Meta

What this checks: Kaiku's voice in your glasses, Kaiku hearing you through them, Kaiku seeing what you look at
(optional), taking the glasses off, and the walk arriving in Your days and on the practitioner dashboard.
None of this has run on the real glasses yet. If a step fails, **screenshot You → Glasses check** (scroll so
"Last problem" and the Log lines show), tap **Share the log**, and send both. The log has states and errors only.

## Before you start (1 minute)
- iPhone unlocked, Kaiku open, the Kaiku service running on the Mac (`make cloud-local`), phone on the same network.
  Mobile data ON (when Kaiku sees, the phone joins the glasses' own Wi-Fi and needs mobile data for the voice).
- Glasses unfolded and **on your face**, connected in the Meta AI app, Developer Mode on there.
- iPhone Settings → Bluetooth: the glasses show "Connected".
- To record the screen for the demo: Settings → Control Centre → add **Screen Recording**. Swipe down from the top
  right, long-press the record button, turn **Microphone On**, Start Recording. Stop from the red pill at the top.
  The video lands in Photos. (The glasses' own speaker is not in the recording; film yourself too if you can.)

## Steps
1. **Open the check.** You → Glasses check.
   See: Meta AI registration `registered`, Glasses `<name>` with a green dot, Worn `on`, Hands-free audio device
   `<glasses name>`. If the hands-free device says `none found`: the glasses are not connected as a Bluetooth
   audio device; put them on, wait 5 s, reopen the screen.
2. **Camera permission** (only if you want Kaiku to see). If Camera permission is not `granted`, tap
   **Ask for the camera in Meta AI**, allow it there, come back.
3. **Self-test** (20 s). Tap **Run the self-test**.
   - Hear: one short Kaiku line **in the glasses**. Row 1 says "Played through <glasses name>".
   - Then say anything for 3 seconds. Row 2 says "Heard you on <glasses name>".
   - Row 3 shows a small picture of what you are looking at (shown only, not saved).
   Fail = any row in amber: screenshot.
4. **Start.** Tap **Walk with Kaiku** at the bottom (or Play → the walk). Turn on **Let Kaiku see through the
   glasses during walks** if you want that part. Tap **Walk with Kaiku**.
   Hear within about 5 s: a short warm greeting in the glasses.
   See: "Kaiku is listening", "In your ear: <glasses name>", "Walking with your glasses", and with seeing on
   "Kaiku can see · n pictures sent, none saved" with the number going up about once a second.
5. **Say three things**, pausing after each: "I'm just heading out." · "It's been a slow morning." · "How long
   have I been walking?"
   Hear: a short reply after each (a few words). See: your words and Kaiku's as bubbles on the phone.
6. **Ask "What am I looking at?"** while looking at something clear (a sign, a tree, a mug). Keep the phone
   unlocked with this screen open.
   Hear: a short answer about that thing. With seeing off, Kaiku should say it cannot see.
7. **Take the glasses off**, wait 5 s, **put them back on**.
   See: "Glasses are off. Kaiku waits…" and probably "On the phone, not in the glasses"; after putting them back,
   the route line returns to "In your ear" within a few seconds and Kaiku answers again when you speak.
8. **Walk at least one full minute in total** (under a minute nothing is saved), then tap **End walk**.
   See: the summary: minutes, "You spoke n times. Kaiku was in your glasses.", pictures seen (none saved),
   "Saved to Your days."
9. **Your days** tab: today shows the walk under "Today, so far".
10. **Practitioner dashboard** on the Mac (`http://localhost:8000`, this person's record): the outing appears
    under Walks and outings for today.

## Known limits (expected, not failures)
- After 5 minutes the conversation reaches its time limit: the screen says so, the walk goes on, **Talk again**
  starts a new one.
- With the phone locked or Kaiku in the background the voice continues, but Kaiku stops seeing (the screen says
  "No pictures are arriving").
- If the Kaiku service is only on the Mac's network, the walk may be saved a little later (it waits in the queue).
- Step counts from the glasses appear only if the glasses offer motion data; otherwise the phone counts steps.

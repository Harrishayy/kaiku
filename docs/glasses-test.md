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

## Walking together: what to film (about 8 minutes, after the steps above work)
Kaiku as company on a walk: it sees what you look at, knows a few things you told it, plays small games and
drops them when you need something else. One real walk of this ran in the simulator (Meta's mock glasses, typed
lines instead of a microphone, 2026-11-14); nothing here has run on the real glasses. Say things in your own
words; the lines below are examples. Seeing must be on (step 4) for A2 to A4.

A1. **Pick how Kaiku walks with you.** On the start screen, under Kaiku's bubble: **Calm · Playful · Chatty**, with
    one line saying what the chosen one does. Choose **Playful**, then **Walk with Kaiku**.
    See on the walk: the same three words with Playful lit. (You → Settings has the same choice.)
A2. **"What's that?"** Look at one clear thing (a tree, a bench, a boat) and ask "What's that over there?".
    Hear: a short answer naming what you are looking at.
A3. **"That's my favourite …"** Look at something you like and say so: "That's my favourite cherry tree."
    Hear: a short warm reply that it will remember it. Check later: You → What Kaiku remembers lists it.
A4. **A spotting game, counted aloud.** Say "Let's play a spotting game" (in Playful, Kaiku may also offer one
    by itself after about a minute of quiet, or when something in view would make one).
    Hear: what to find and how many, chosen from what is around ("three red doors").
    See: a green card on the walk screen: the thing and **0 of 3**, with one dot per thing.
    When you see one, say "Found one" (or "yes" when Kaiku asks "is that one?"). Hear: how many are left.
    See: the card count goes up with every find. **Found one** on the card does the same without speaking.
    If Kaiku counts aloud but no card appears, or the spoken number and the card disagree: that is a failure.
    Screenshot it (in the simulator run Kaiku proposed "three birds" and counted by itself, with no card).
A5. **A sad sentence in the middle of the game.** Before the last find, say something true and heavy: "I don't
    feel like playing anymore. I've been missing my sister all week."
    Hear: Kaiku leaves the game and stays with what you said. No "two more to find", no new game.
    (Never use the words on the crisis list for this take: those end the walk and open the crisis screen.)
A6. **Finish the game** on another take: find the last one. See: the card shows a tick and a soft sparkle.
A7. **A quiet stretch.** Walk 40 to 60 seconds without speaking. Look at plain ground or a wall for half of it,
    then at something striking (water, low sun through trees).
    Hear in Calm: nothing for the ground, at most one short remark for the striking view. In Chatty: Kaiku
    speaks first after about 40 seconds of quiet. A click, breath or hum with no words is a failure: note the time.
A8. **Change the style on the walk.** Tap **Calm**. See: "Kaiku is joining…" for a moment, then listening again;
    a game card that was showing stays. Hear: no second greeting.
A9. **The next walk remembers.** End the walk, start a new one (seeing on), and look at the favourite from A3.
    Hear: Kaiku connects it to you ("Is that your favourite cherry tree?"), by itself in Calm within about half
    a minute of looking, or when you ask "Do you know where we are?".

## Known limits (expected, not failures)
- A game's count lives on the phone for that walk only. Nothing about what was seen is stored: the pictures go
  to the live conversation and nowhere else, and the saved walk has minutes and steps, not sights.
- Kaiku speaks by itself only because the phone asks it to look (every 20 to 30 seconds while it can see) or
  notes a quiet stretch. With seeing off or paused it never remarks on the view.
- A walk's conversation has a time limit from the service (30 minutes on 2026-11-14) and ends by itself after a
  long stretch with nobody speaking (15 minutes): the screen says so, the walk goes on, **Talk again** starts a
  new one, which is told the walk and any game are still going. Neither limit has been reached in a test run.
- With the phone locked or Kaiku in the background the voice continues, but Kaiku stops seeing (the screen says
  "No pictures are arriving").
- If the Kaiku service is only on the Mac's network, the walk may be saved a little later (it waits in the queue).
- Step counts from the glasses appear only if the glasses offer motion data; otherwise the phone counts steps.

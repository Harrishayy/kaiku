@preconcurrency import AVFoundation
import CoreGraphics
import XCTest
@testable import KaikuKit

/// Quick talk on the Mac: the double tap, the one shape that grows (bar, pill, popup) and where it goes, what it
/// shows in every state, what Kaiku reacts to, and who ends the conversation. No test opens a microphone: the
/// conversations here run on stand-in audio and a stand-in socket.
final class QuickTalkDoubleTapTests: XCTestCase {
    private func taps(_ d: inout QuickTalkDoubleTap, _ events: [(QuickTalkMods, TimeInterval)], input: UInt64 = 0) -> [Bool] {
        events.map { d.modifiersChanged($0.0, at: $0.1, input: input) }
    }

    func testTwoLoneTapsFireOnTheSecondRelease() {
        var d = QuickTalkDoubleTap(key: .option)
        XCTAssertEqual(taps(&d, [([.option], 0.00), ([], 0.08), ([.option], 0.22), ([], 0.30)]), [false, false, false, true])
    }

    func testOneTapAndSlowSecondTapDoNotFire() {
        var d = QuickTalkDoubleTap(key: .option)
        XCTAssertEqual(taps(&d, [([.option], 0), ([], 0.08)]), [false, false])
        // the second press comes after the window: it is a first tap again, and a third right after it completes a pair
        XCTAssertEqual(taps(&d, [([.option], 0.60), ([], 0.68)]), [false, false])
        XCTAssertEqual(taps(&d, [([.option], 0.80), ([], 0.88)]), [false, true])
    }

    func testHoldingIsNotATap() {
        var d = QuickTalkDoubleTap(key: .option)
        // first press held (typing a special character with Option down)
        XCTAssertEqual(taps(&d, [([.option], 0), ([], 0.5), ([.option], 0.6), ([], 0.68)]), [false, false, false, false])
        // tap, then hold: nothing on the release of the hold
        d.reset()
        XCTAssertEqual(taps(&d, [([.option], 1.0), ([], 1.08), ([.option], 1.2), ([], 1.9)]), [false, false, false, false])
    }

    func testAnotherModifierStartsOver() {
        var d = QuickTalkDoubleTap(key: .option)
        // Option-Shift (the key combination itself, or any shortcut) is not a lone tap
        XCTAssertEqual(taps(&d, [([.option], 0), ([.option, .shift], 0.03), ([.shift], 0.06), ([], 0.09),
                                 ([.option], 0.2), ([], 0.28)]), [false, false, false, false, false, false])
        // a press that starts while another modifier is down does not count either
        d.reset()
        XCTAssertEqual(taps(&d, [([.shift], 1.0), ([.shift, .option], 1.05), ([.shift], 1.1), ([.shift, .option], 1.2),
                                 ([.shift], 1.25), ([], 1.3)]), [false, false, false, false, false, false])
        // Command twice is not Option twice
        d.reset()
        XCTAssertEqual(taps(&d, [([.command], 2.0), ([], 2.08), ([.command], 2.2), ([], 2.28)]), [false, false, false, false])
    }

    func testAKeyOrClickInBetweenStartsOver() {
        var d = QuickTalkDoubleTap(key: .option)
        XCTAssertFalse(d.modifiersChanged([.option], at: 0, input: 100))
        XCTAssertFalse(d.modifiersChanged([], at: 0.08, input: 100))
        // the system's count of key and mouse presses moved: something was typed or clicked
        XCTAssertFalse(d.modifiersChanged([.option], at: 0.2, input: 101))
        XCTAssertFalse(d.modifiersChanged([], at: 0.28, input: 101))
        // …and that second tap was a first one: a clean tap right after completes the pair
        XCTAssertFalse(d.modifiersChanged([.option], at: 0.4, input: 101))
        XCTAssertTrue(d.modifiersChanged([], at: 0.48, input: 101))
        // a press seen directly (Kaiku's own window) does the same
        XCTAssertFalse(d.modifiersChanged([.option], at: 1.0, input: 101))
        XCTAssertFalse(d.modifiersChanged([], at: 1.08, input: 101))
        d.otherInput()
        XCTAssertFalse(d.modifiersChanged([.option], at: 1.2, input: 101))
        XCTAssertFalse(d.modifiersChanged([], at: 1.28, input: 101))
    }

    func testRepeatsAndOtherKeysOfTheSameModifierAreQuiet() {
        var d = QuickTalkDoubleTap(key: .option)
        // unchanged flags (Caps Lock, the second Option key joining) are not transitions
        XCTAssertEqual(taps(&d, [([.option], 0), ([.option], 0.02), ([], 0.08), ([], 0.1), ([.option], 0.2), ([], 0.27)]),
                       [false, false, false, false, false, true])
        // it fires once: a third tap is the first of a new pair
        XCTAssertEqual(taps(&d, [([.option], 0.4), ([], 0.47)]), [false, false])
    }

    func testControlKeyAndTheChoices() {
        var d = QuickTalkDoubleTap(key: .control)
        XCTAssertEqual(taps(&d, [([.control], 0), ([], 0.07), ([.control], 0.18), ([], 0.25)]), [false, false, false, true])
        XCTAssertEqual(taps(&d, [([.option], 1), ([], 1.07), ([.option], 1.18), ([], 1.25)]), [false, false, false, false])
        XCTAssertNil(QuickTalkDoubleTapKey.off.mods)
        XCTAssertEqual(QuickTalkDoubleTapKey.option.mods, .option)
        XCTAssertEqual(QuickTalkDoubleTapKey.control.mods, .control)
    }

    /// Option-Shift-Space: Carbon's key code for Space and optionKey | shiftKey; not Spotlight, not input sources.
    func testTheKeyCombination() {
        XCTAssertEqual(QuickTalkHotKey.keyCode, 49)
        XCTAssertEqual(QuickTalkHotKey.carbonModifiers, 0x0800 | 0x0200)
        XCTAssertEqual(QuickTalkHotKey.carbonModifiers & 0x0100, 0, "no Command: Spotlight and Finder search use it")
        XCTAssertEqual(QuickTalkHotKey.carbonModifiers & 0x1000, 0, "no Control: input-source switching uses it")
        XCTAssertEqual(L10n.shared.string("quick.keys", lang: .en), "⌥⇧Space")
    }
}

final class QuickTalkGeometryTests: XCTestCase {
    /// The lead's MacBook: 1512 × 982 pt, menu bar 32.
    let laptop = MacScreenInfo(frame: CGRect(x: 0, y: 0, width: 1512, height: 982),
                               visibleFrame: CGRect(x: 0, y: 0, width: 1512, height: 950), safeTop: 32, isMain: true)

    func testLeftEdgeVerticallyCentredInsideTheVisibleFrame() {
        let g = QuickTalkGeometry.compute(laptop)
        XCTAssertEqual(g.window.minX, 0)                               // the card slides in from the screen edge
        XCTAssertEqual(g.window.midY, 475, accuracy: 0.5)              // centred below the menu bar
        XCTAssertTrue(laptop.visibleFrame.contains(g.window))
        for size in [QuickTalkLayout.wide, QuickTalkLayout.compact, QuickTalkLayout.largest] {
            let card = g.cardFrame(size)
            XCTAssertEqual(card.minX, QuickTalkLayout.margin)
            XCTAssertEqual(card.midY, 475, accuracy: 0.5)
            XCTAssertEqual(card.size, size)
            XCTAssertTrue(g.window.contains(card))
            // room for the shadow on the three free sides
            XCTAssertGreaterThanOrEqual(g.window.maxX - card.maxX, QuickTalkLayout.shadowPad - 0.5)
            XCTAssertGreaterThanOrEqual(card.minY - g.window.minY, QuickTalkLayout.shadowPad - 0.5)
        }
        // a side companion: well under the notch island's 460 × 188 footprint in width, and a small part of the screen
        XCTAssertLessThan(QuickTalkLayout.wide.width, MacIslandLayout.expanded.width)
        XCTAssertLessThan(QuickTalkLayout.largest.width * QuickTalkLayout.largest.height, 0.06 * 1512 * 982)
    }

    func testClearOfTheDockWhereverItIs() {
        // Dock on the left (72 pt): the visible frame starts after it, and so does the panel
        var s = laptop
        s.visibleFrame = CGRect(x: 72, y: 0, width: 1440, height: 950)
        var g = QuickTalkGeometry.compute(s)
        XCTAssertEqual(g.window.minX, 72)
        XCTAssertEqual(g.cardFrame(QuickTalkLayout.wide).minX, 72 + QuickTalkLayout.margin)
        XCTAssertTrue(s.visibleFrame.contains(g.window))
        // Dock at the bottom (80 pt): centred in what is left
        s.visibleFrame = CGRect(x: 0, y: 80, width: 1512, height: 870)
        g = QuickTalkGeometry.compute(s)
        XCTAssertEqual(g.window.midY, 515, accuracy: 0.5)
        XCTAssertTrue(s.visibleFrame.contains(g.window))
    }

    func testExternalAndSmallScreens() {
        // a display to the left of the main one, lower: the panel is at ITS left edge
        let left = MacScreenInfo(frame: CGRect(x: -2560, y: -300, width: 2560, height: 1440),
                                 visibleFrame: CGRect(x: -2560, y: -300, width: 2560, height: 1415))
        let g = QuickTalkGeometry.compute(left)
        XCTAssertEqual(g.window.minX, -2560)
        XCTAssertTrue(left.visibleFrame.contains(g.window))
        XCTAssertEqual(g.window.midY, -300 + 1415 / 2, accuracy: 0.5)
        // a screen smaller than the panel: clamped to it, never outside
        let tiny = MacScreenInfo(frame: CGRect(x: 0, y: 0, width: 300, height: 200), visibleFrame: CGRect(x: 0, y: 0, width: 300, height: 180))
        let t = QuickTalkGeometry.compute(tiny)
        XCTAssertTrue(tiny.visibleFrame.contains(t.window))
        XCTAssertTrue(tiny.visibleFrame.contains(t.cardFrame(QuickTalkLayout.wide)))
    }

    func testThePointersScreen() {
        let external = MacScreenInfo(frame: CGRect(x: 1512, y: -200, width: 2560, height: 1440),
                                     visibleFrame: CGRect(x: 1512, y: -200, width: 2560, height: 1415))
        XCTAssertEqual(QuickTalkGeometry.pick([laptop, external], pointer: CGPoint(x: 2000, y: 500)), external)
        XCTAssertEqual(QuickTalkGeometry.pick([external, laptop], pointer: CGPoint(x: 100, y: 100)), laptop)
        XCTAssertEqual(QuickTalkGeometry.pick([external, laptop], pointer: CGPoint(x: -50, y: 5000)), laptop)   // nowhere: main
        XCTAssertEqual(QuickTalkGeometry.pick([external], pointer: CGPoint(x: -50, y: 5000)), external)
        XCTAssertNil(QuickTalkGeometry.pick([], pointer: .zero))
    }

    /// The bar, the pill and the popup are one object at one place: same left edge of the screen, same centre line.
    func testOneShapeThatGrowsInPlace() {
        let g = QuickTalkGeometry.compute(laptop)
        let bar = g.frame(.bar), live = g.frame(.bar, live: true), pill = g.frame(.pill)
        let popup = g.frame(.popup, card: QuickTalkLayout.wide)
        XCTAssertEqual(popup, g.cardFrame(QuickTalkLayout.wide))
        for f in [bar, live, pill, popup] {
            XCTAssertEqual(f.midY, 475, accuracy: 0.5)
            XCTAssertTrue(g.window.contains(f))
            XCTAssertLessThanOrEqual(f.minX - g.window.minX, QuickTalkLayout.margin)
        }
        // a few points of bar at rest, a little more while a conversation is on; each stage holds the one before
        XCTAssertLessThanOrEqual(bar.width, 8); XCTAssertEqual(bar.size, QuickTalkLayout.bar)
        XCTAssertGreaterThan(live.width, bar.width); XCTAssertLessThanOrEqual(live.width, 14)
        XCTAssertLessThanOrEqual(bar.maxX, pill.maxX); XCTAssertLessThanOrEqual(live.maxX, pill.maxX)
        XCTAssertGreaterThan(pill.height, live.height)
        XCTAssertLessThan(pill.maxX, popup.maxX); XCTAssertLessThan(pill.height, popup.height)
        // exactly two pointer-sized buttons fit the pill, one above the other
        XCTAssertGreaterThanOrEqual(QuickTalkLayout.pill.height, 2 * QuickTalkLayout.pillButton + 16)
        XCTAssertGreaterThanOrEqual(QuickTalkLayout.pill.width, QuickTalkLayout.pillButton + 12)
        XCTAssertLessThan(QuickTalkLayout.pill.height, 3 * QuickTalkLayout.pillButton)
        // the bar and the pill are capsules; the popup is a card
        XCTAssertEqual(QuickTalkLayout.radius(.bar, size: bar.size), 3)
        XCTAssertEqual(QuickTalkLayout.radius(.pill, size: pill.size), 25)
        XCTAssertEqual(QuickTalkLayout.radius(.popup, size: popup.size), 24)
        // turned off: nothing is drawn, and the popup still grows from the screen edge
        XCTAssertEqual(g.frame(.hidden).width, 0); XCTAssertEqual(g.frame(.hidden).minX, g.window.minX)
        XCTAssertEqual(Set(QuickTalkStage.allCases), [.hidden, .bar, .pill, .popup])
    }

    func testThePointerGrowsThePillAndLetsItGo() {
        let g = QuickTalkGeometry.compute(laptop)
        let bar = g.frame(.bar), pill = g.frame(.pill), edge = g.window.minX
        func hover(_ was: Bool, _ x: CGFloat, _ y: CGFloat) -> Bool {
            QuickTalkLayout.hovering(was: was, pointer: CGPoint(x: x, y: y), bar: bar, pill: pill, edge: edge)
        }
        // coming right up to the bar starts it: on it, at the very screen edge beside it, a few points past it
        XCTAssertTrue(hover(false, bar.midX, bar.midY))
        XCTAssertTrue(hover(false, edge, bar.midY))
        XCTAssertTrue(hover(false, bar.maxX + 6, bar.maxY + 6))
        // passing by does not: the pill's own area is not enough to start it
        XCTAssertFalse(hover(false, pill.maxX - 4, bar.midY))
        XCTAssertFalse(hover(false, bar.midX, bar.maxY + 30))
        XCTAssertFalse(hover(false, 400, 475))
        // once it is out, the pointer may be anywhere on the pill and a little around it
        XCTAssertTrue(hover(true, pill.maxX - 4, pill.midY))
        XCTAssertTrue(hover(true, pill.midX, pill.maxY + 10))
        XCTAssertTrue(hover(true, pill.maxX + 10, pill.minY - 10))
        XCTAssertFalse(hover(true, pill.maxX + 30, pill.midY))
        XCTAssertFalse(hover(true, pill.midX, pill.maxY + 30))
        // a Dock on the left: the edge is the Dock's, not the screen's
        var s = laptop
        s.visibleFrame = CGRect(x: 72, y: 0, width: 1440, height: 950)
        let d = QuickTalkGeometry.compute(s)
        XCTAssertFalse(QuickTalkLayout.hovering(was: false, pointer: CGPoint(x: 20, y: 475), bar: d.frame(.bar), pill: d.frame(.pill), edge: d.window.minX))
        XCTAssertTrue(QuickTalkLayout.hovering(was: false, pointer: CGPoint(x: 78, y: 475), bar: d.frame(.bar), pill: d.frame(.pill), edge: d.window.minX))
    }

    func testTheVoiceLevelForTheMeter() {
        XCTAssertEqual(QuickTalkLayout.level(db: -90), 0)       // silence
        XCTAssertEqual(QuickTalkLayout.level(db: -55), 0)       // room noise shows nothing
        XCTAssertEqual(QuickTalkLayout.level(db: -35), 0.5, accuracy: 0.001)
        XCTAssertEqual(QuickTalkLayout.level(db: -15), 1)
        XCTAssertEqual(QuickTalkLayout.level(db: 0), 1)
        XCTAssertLessThan(QuickTalkLayout.level(db: -45), QuickTalkLayout.level(db: -30))
    }

    func testWhichCard() {
        XCTAssertEqual(QuickTalkLayout.card(captions: true, conversational: true), QuickTalkLayout.wide)
        XCTAssertEqual(QuickTalkLayout.card(captions: false, conversational: true), QuickTalkLayout.compact)
        // a reason Kaiku cannot listen is spelled out even with captions off
        XCTAssertEqual(QuickTalkLayout.card(captions: false, conversational: false), QuickTalkLayout.wide)
        // an activity card needs the room, captions or not
        let withCard = QuickTalkLayout.card(captions: false, conversational: true, activity: true)
        XCTAssertEqual(withCard.width, QuickTalkLayout.wide.width)
        XCTAssertEqual(withCard.height, QuickTalkLayout.wide.height + QuickTalkLayout.activityRow)
        XCTAssertGreaterThanOrEqual(QuickTalkLayout.largest.height, withCard.height)
    }
}

final class QuickTalkDisplayTests: XCTestCase {
    private func make(onboarded: Bool = true, paired: Bool = true, paused: Bool = false, micDenied: Bool = false, starting: Bool = false,
                      live: Bool = true, phase: Conversation.Phase = .listening, wasLive: Bool = false,
                      reason: Conversation.UnavailableReason? = nil, status: CallStatus = .listening, micOn: Bool = true,
                      hearing: Bool = false, lines: [(text: String, me: Bool)] = [], captions: Bool = true,
                      voiceMuted: Bool = false) -> QuickTalkDisplay {
        .make(onboarded: onboarded, paired: paired, paused: paused, micDenied: micDenied, starting: starting, live: live, phase: phase,
              wasLive: wasLive, reason: reason, status: status, micOn: micOn, hearing: hearing, lines: lines, captions: captions,
              voiceMuted: voiceMuted)
    }

    func testTheMostBasicThingMissingIsTheOneSaid() {
        // setup first, whatever else is true
        var d = make(onboarded: false, paired: false, paused: true, micDenied: true)
        XCTAssertEqual(d.state, .setup); XCTAssertEqual(d.lineKey, "quick.setup"); XCTAssertEqual(d.help, .openKaiku)
        d = make(paired: false, paused: true, micDenied: true, live: false, phase: .unavailable, reason: .pairing)
        XCTAssertEqual(d.state, .notConnected); XCTAssertEqual(d.lineKey, "call.line.unpaired"); XCTAssertEqual(d.helpKey, "mac.open")
        d = make(paused: true, micDenied: true, live: false, phase: .unavailable, reason: .paused)
        XCTAssertEqual(d.state, .paused); XCTAssertEqual(d.lineKey, "call.line.paused"); XCTAssertEqual(d.help, .openKaiku)
        d = make(micDenied: true, live: false, phase: .idle)
        XCTAssertEqual(d.state, .micDenied); XCTAssertEqual(d.help, .microphoneSettings); XCTAssertEqual(d.helpKey, "talk.voice.settings")
        // the conversation's own reasons say the same without the flags
        XCTAssertEqual(make(live: false, phase: .unavailable, reason: .pairing).state, .notConnected)
        XCTAssertEqual(make(live: false, phase: .unavailable, reason: .paused).state, .paused)
        XCTAssertEqual(make(live: false, phase: .unavailable, reason: .microphone).state, .micDenied)
        // a conversation open without the microphone (typed on the Talk screen) is not one this panel can hold
        XCTAssertEqual(make(status: .micOff, micOn: false).state, .micDenied)
    }

    func testVoiceNotAvailableAndEnded() {
        for (reason, key) in [(Conversation.UnavailableReason.connection, "call.line.connection"), (.audio, "call.line.audio"), (.voice, "call.line.voice")] {
            let d = make(live: false, phase: .unavailable, reason: reason)
            XCTAssertEqual(d.state, .unavailable); XCTAssertEqual(d.lineKey, key)
            XCTAssertEqual(d.help, .tryAgain); XCTAssertEqual(d.helpKey, "call.retry")
        }
        // a call that was open and has ended; and no call yet (nothing was started): both offer to call
        let ended = make(live: false, phase: .idle, wasLive: true)
        XCTAssertEqual(ended.state, .ended); XCTAssertEqual(ended.lineKey, "call.ended"); XCTAssertEqual(ended.helpKey, "call.start")
        let ready = make(live: false, phase: .idle)
        XCTAssertEqual(ready.state, .ended); XCTAssertEqual(ready.lineKey, "call.line.ready"); XCTAssertEqual(ready.help, .tryAgain)
    }

    func testWakingUp() {
        for d in [make(starting: true, live: false, phase: .idle), make(live: false, phase: .connecting), make(phase: .connecting, status: .connecting),
                  make(paired: false, starting: true, live: false, phase: .idle)] {   // not connected yet: a demo service may still answer
            XCTAssertEqual(d.state, .connecting); XCTAssertEqual(d.mascot, .thinking)
            XCTAssertFalse(d.micLive); XCTAssertNil(d.help); XCTAssertNil(d.lineKey)
            XCTAssertEqual(d.statusKey, "call.state.connecting")
        }
    }

    func testTheCallFollowsKaiku() {
        let said: [(text: String, me: Bool)] = [("I'm not feeling too well", true)]
        var d = make(lines: [])
        XCTAssertEqual(d.state, .listening); XCTAssertEqual(d.mascot, .listening); XCTAssertTrue(d.micLive); XCTAssertNil(d.person)
        d = make(phase: .hearing, hearing: true, lines: said)
        XCTAssertEqual(d.state, .hearing); XCTAssertEqual(d.mascot, .listening); XCTAssertEqual(d.person, "I'm not feeling too well")
        XCTAssertEqual(d.statusKey, "call.state.listening")
        d = make(phase: .thinking, status: .thinking, lines: said)
        XCTAssertEqual(d.state, .thinking); XCTAssertEqual(d.mascot, .thinking); XCTAssertEqual(d.statusKey, "call.state.thinking")
        d = make(phase: .speaking, status: .speaking, lines: said + [("I'm here.", false)], voiceMuted: true)
        XCTAssertEqual(d.state, .speaking); XCTAssertEqual(d.mascot, .speaking); XCTAssertEqual(d.kaiku, "I'm here.")
        XCTAssertTrue(d.voiceMuted); XCTAssertTrue(d.micLive); XCTAssertEqual(d.statusKey, "call.state.speaking")
        // muted: sleepy, and the microphone is shown as closed
        d = make(phase: .muted, status: .muted, micOn: false, lines: said)
        XCTAssertEqual(d.state, .muted); XCTAssertEqual(d.mascot, .sleepy); XCTAssertFalse(d.micLive)
        XCTAssertEqual(d.statusKey, "call.state.muted")
        // Kaiku still finishing its sentence while I am muted: speaking, microphone closed
        d = make(phase: .muted, status: .speaking, micOn: false, lines: said)
        XCTAssertEqual(d.state, .speaking); XCTAssertFalse(d.micLive)
        for s in [QuickTalkDisplay.State.listening, .hearing, .thinking, .speaking, .muted] {
            XCTAssertTrue(QuickTalkDisplay(state: s).conversational); XCTAssertNil(QuickTalkDisplay(state: s).help)
        }
    }

    /// Whatever the inputs, a state without an open call never shows an open microphone, and says "Not listening".
    func testItNeverPretendsToListen() {
        let phases: [Conversation.Phase] = [.idle, .connecting, .listening, .hearing, .thinking, .speaking, .muted, .paused, .unavailable]
        let reasons: [Conversation.UnavailableReason?] = [nil, .microphone, .pairing, .connection, .voice, .audio, .paused]
        var seen = Set<QuickTalkDisplay.State>()
        for onboarded in [true, false] { for paired in [true, false] { for paused in [true, false] { for denied in [true, false] {
            for live in [true, false] { for phase in phases { for reason in reasons { for status in CallStatus.allCases { for micOn in [true, false] {
                let d = make(onboarded: onboarded, paired: paired, paused: paused, micDenied: denied, live: live, phase: phase,
                             wasLive: micOn, reason: reason, status: status, micOn: micOn, lines: [("words", true)])
                seen.insert(d.state)
                if !d.conversational {
                    XCTAssertFalse(d.micLive, "\(d.state)")
                    XCTAssertNil(d.person); XCTAssertNil(d.kaiku)
                    XCTAssertEqual(d.statusKey, d.state == .connecting ? "call.state.connecting" : "quick.status.off")
                    XCTAssertEqual(d.cardSize, QuickTalkLayout.wide)
                    if d.state != .connecting { XCTAssertNotNil(d.lineKey, "\(d.state)"); XCTAssertNotNil(d.help, "\(d.state)") }
                } else {
                    XCTAssertTrue(onboarded && paired && !paused && !denied && live)
                    XCTAssertEqual(d.micLive, micOn)
                }
            } } } } }
        } } } }
        XCTAssertEqual(seen, Set(QuickTalkDisplay.State.allCases).subtracting([.hearing]))
    }

    func testCaptionsOffLeavesKaikuAlone() {
        let d = make(phase: .hearing, hearing: true, lines: [("hello", true)], captions: false)
        XCTAssertEqual(d.cardSize, QuickTalkLayout.compact)
        XCTAssertEqual(make(live: false, phase: .unavailable, reason: .voice, captions: false).cardSize, QuickTalkLayout.wide)
        var withCard = d
        withCard.activity = ActivityCard(kind: "breathe")
        XCTAssertNotNil(withCard.activity)
        XCTAssertEqual(withCard.cardSize.height, QuickTalkLayout.wide.height + QuickTalkLayout.activityRow)
    }

    func testEveryCopyKeyExists() {
        XCTAssertGreaterThan(QuickTalkDisplay.copyKeys.count, 30)
        for key in QuickTalkDisplay.copyKeys {
            XCTAssertTrue(L10n.shared.has(key, .en), "missing en: \(key)")
            XCTAssertTrue(L10n.shared.has(key, .fi), "missing fi: \(key)")
        }
        // the status words fit one line beside "Continue in Kaiku" at the micro size (about 6.6 pt a letter)
        for s in QuickTalkDisplay.State.allCases {
            XCTAssertLessThanOrEqual(L10n.shared.string(QuickTalkDisplay(state: s).statusKey, lang: .en).count, 18, "\(s)")
        }
    }
}

/// What Kaiku shows for a moment: only what really happened, and gentle when the person is having a hard time.
final class QuickTalkMomentTests: XCTestCase {
    func testAGoodMomentSparkles() {
        var r = QuickTalkMoment.react(to: .expression(.happy), heavy: false)
        XCTAssertEqual(r.mascot, .happy); XCTAssertEqual(r.reaction, .sparkle)
        r = QuickTalkMoment.react(to: .expression(.cheering), heavy: false)
        XCTAssertEqual(r.mascot, .cheering); XCTAssertEqual(r.reaction, .sparkle)
        r = QuickTalkMoment.react(to: .plan(stance: "celebrate"), heavy: false)
        XCTAssertEqual(r.mascot, .happy); XCTAssertEqual(r.reaction, .sparkle)
        // a find: a small sparkle, Kaiku's face stays with the call
        r = QuickTalkMoment.react(to: .found, heavy: false)
        XCTAssertNil(r.mascot); XCTAssertEqual(r.reaction, .sparkle)
        r = QuickTalkMoment.react(to: .found, heavy: true)
        XCTAssertNil(r.mascot); XCTAssertNil(r.reaction)
    }

    func testCuriousCozyAndNothing() {
        var r = QuickTalkMoment.react(to: .expression(.listening), heavy: false)
        XCTAssertEqual(r.mascot, .listening); XCTAssertEqual(r.reaction, .curious)
        r = QuickTalkMoment.react(to: .plan(stance: "explore"), heavy: false)
        XCTAssertEqual(r.mascot, .listening); XCTAssertEqual(r.reaction, .curious)
        r = QuickTalkMoment.react(to: .expression(.cozy), heavy: false)
        XCTAssertEqual(r.mascot, .cozy); XCTAssertEqual(r.reaction, .heart)
        r = QuickTalkMoment.react(to: .expression(.sleepy), heavy: false)
        XCTAssertEqual(r.mascot, .sleepy); XCTAssertNil(r.reaction)
        // a steady plan, or one without a stance, is nothing to show
        for stance in ["steady", nil] {
            r = QuickTalkMoment.react(to: .plan(stance: stance), heavy: false)
            XCTAssertNil(r.mascot); XCTAssertNil(r.reaction)
        }
    }

    /// No sparkles and no cheering on a heavy moment: Kaiku is cozy, at most a small heart (it never looks sad).
    func testGentleOnAHeavyMoment() {
        XCTAssertTrue(QuickTalkMoment.heavy("comfort")); XCTAssertTrue(QuickTalkMoment.heavy("give_space"))
        for stance in ["celebrate", "steady", "explore", nil] { XCTAssertFalse(QuickTalkMoment.heavy(stance)) }
        var r = QuickTalkMoment.react(to: .plan(stance: "comfort"), heavy: true)
        XCTAssertEqual(r.mascot, .cozy); XCTAssertEqual(r.reaction, .heart)
        r = QuickTalkMoment.react(to: .plan(stance: "give_space"), heavy: true)
        XCTAssertEqual(r.mascot, .cozy); XCTAssertNil(r.reaction)
        let events: [QuickTalkMoment.Event] = [.expression(.happy), .expression(.cheering), .found, .expression(.cozy),
                                               .expression(.listening), .expression(.sleepy), .plan(stance: "comfort"), .plan(stance: "give_space")]
        for event in events {
            let h = QuickTalkMoment.react(to: event, heavy: true)
            XCTAssertNotEqual(h.reaction, .sparkle, "\(event)")
            XCTAssertFalse([MascotState.happy, .cheering].contains(h.mascot ?? .idle), "\(event)")
        }
    }

    /// A reaction is part of a call: the display carries it while the call is open, never while muted or closed.
    func testTheDisplayCarriesTheMoment() {
        func make(live: Bool = true, status: CallStatus = .listening, micOn: Bool = true) -> QuickTalkDisplay {
            .make(onboarded: true, paired: true, paused: false, micDenied: false, starting: false, live: live, phase: live ? .listening : .idle,
                  reason: nil, status: status, micOn: micOn, moment: .happy, reaction: .sparkle)
        }
        var d = make()
        XCTAssertEqual(d.mascot, .happy); XCTAssertEqual(d.reaction, .sparkle)
        d = make(status: .speaking)
        XCTAssertEqual(d.mascot, .happy); XCTAssertEqual(d.reaction, .sparkle)
        d = make(status: .thinking)
        XCTAssertEqual(d.mascot, .thinking); XCTAssertEqual(d.reaction, .sparkle)
        d = make(status: .muted, micOn: false)
        XCTAssertEqual(d.mascot, .sleepy); XCTAssertNil(d.reaction)
        d = make(live: false)
        XCTAssertNil(d.reaction); XCTAssertNotEqual(d.mascot, .happy)
    }
}

final class QuickTalkCaptionsTests: XCTestCase {
    func testTheExchangeGoingOn() {
        typealias L = (text: String, me: Bool)
        var c = QuickTalkCaptions.current([])
        XCTAssertNil(c.person); XCTAssertNil(c.kaiku)
        // the person is talking: their words alone
        c = QuickTalkCaptions.current([L("I'm not feeling too well", true)])
        XCTAssertEqual(c.person, "I'm not feeling too well"); XCTAssertNil(c.kaiku)
        // Kaiku answers: both
        c = QuickTalkCaptions.current([L("I'm not feeling too well", true), L("That sounds hard.", false)])
        XCTAssertEqual(c.person, "I'm not feeling too well"); XCTAssertEqual(c.kaiku, "That sounds hard.")
        // the person speaks again: Kaiku's older line steps aside
        c = QuickTalkCaptions.current([L("one", true), L("old reply", false), L("two", true)])
        XCTAssertEqual(c.person, "two"); XCTAssertNil(c.kaiku)
        // Kaiku spoke first (a conversation the Talk screen opened): its line alone; empty fragments are nobody's
        c = QuickTalkCaptions.current([L("Hello, you.", false), L("  ", true)])
        XCTAssertNil(c.person); XCTAssertEqual(c.kaiku, "Hello, you.")
    }

    func testLongLinesKeepTheirNewestWords() {
        XCTAssertEqual(QuickTalkCaptions.tail("short", limit: 20), "short")
        XCTAssertEqual(QuickTalkCaptions.tail("a  line\nwith   breaks", limit: 40), "a line with breaks")
        let long = (1...40).map { "word\($0)" }.joined(separator: " ")
        let t = QuickTalkCaptions.tail(long, limit: 60)
        XCTAssertTrue(t.hasPrefix("…")); XCTAssertTrue(t.hasSuffix("word40"))
        XCTAssertLessThanOrEqual(t.count, 61)
        XCTAssertFalse(t.dropFirst().hasPrefix("ord"), "starts at a word")
        XCTAssertTrue(long.hasSuffix(String(t.dropFirst())))
        // one endless word still shows its end
        XCTAssertEqual(QuickTalkCaptions.tail(String(repeating: "a", count: 100), limit: 10).count, 11)
        // the display keeps whole lines (VoiceOver reads them); the card shows the tails
        let c = QuickTalkCaptions.current([(text: long, me: true), (text: long, me: false)])
        XCTAssertEqual(c.person, long); XCTAssertEqual(c.kaiku, long)
        XCTAssertLessThan(QuickTalkCaptions.personWithReply, QuickTalkCaptions.kaikuLimit)
        XCTAssertLessThan(QuickTalkCaptions.kaikuLimit, QuickTalkCaptions.personAlone)
    }
}

// MARK: - the model, on a stand-in conversation

private final class QuickAudio: ConversationAudioIO, @unchecked Sendable {
    var onPCM: ((Data) -> Void)?
    var onBuffer: ((AVAudioPCMBuffer) -> Void)?
    var onLevel: ((Float) -> Void)?
    var onPlaying: ((Bool) -> Void)?
    var onFailure: (() -> Void)?
    var isPlaying = false
    var running = false
    var mic = false
    func start() throws { running = true }
    func stop() { running = false; mic = false }
    func setMic(_ on: Bool) { mic = on }
    func play(_ pcm: Data) {}
    func flush() {}
}

private final class QuickLink: ConversationTransport, @unchecked Sendable {
    var event: (@Sendable (LiveSession.Event) -> Void)?
    var contexts: [String] = []
    var connected = false
    var closed = false
    func connect(token: String, session: CompanionSessionResponse, options: LiveSession.Options) { connected = true }
    func close() { closed = true }
    func sendAudio(_ pcm: Data) {}
    func audioStreamEnd() {}
    func sendText(_ text: String) {}
    func sendContext(_ event: String) { contexts.append(event) }
    func respond(id: String, name: String, result: JSONValue) {}
}

/// The cloud, answering the session bootstrap and accepting everything else.
private final class QuickHTTP: URLProtocol {
    nonisolated(unsafe) static var sessions = 0
    /// The stance of the plan the cloud's `feel` tool answers with.
    nonisolated(unsafe) static var stance = "comfort"
    /// When set: the cloud's whole answer to the next tool calls (instead of the `feel` plan).
    nonisolated(unsafe) static var tool: String?
    static let lock = NSLock()
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let path = request.url!.path
        var json = #"{"accepted":1,"duplicates":0,"rejected":[]}"#
        if path.hasSuffix("session") {
            Self.lock.lock(); Self.sessions += 1; Self.lock.unlock()
            json = #"{"session_id":"quick-session","model":"test-model","voice":"test-voice","system_instruction":"test","tools":[],"context_card":{"time_of_day":"morning"},"persona_version":"p","safety_phrases_version":"s","live_token":{"token":"synthetic-token","expires_at":"2099-01-01T00:00:00Z","new_session_expires_at":"2099-01-01T00:00:00Z"}}"#
        } else if path.hasSuffix("tool") {
            Self.lock.lock(); let stance = Self.stance, tool = Self.tool; Self.lock.unlock()
            json = tool ?? #"{"ok":true,"name":"feel","result":{"stance":"\#(stance)","depth":"brief","scheduling":"SILENT"}}"#
        } else if path.hasSuffix("episode") {
            json = #"{"ok":true,"id":"quick-session","transcript_stored":false}"#
        } else if path.hasSuffix("events"), request.httpMethod == "GET" {
            json = #"{"events":[]}"#
        }
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(json.utf8)); client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

@MainActor final class QuickTalkModelTests: XCTestCase {
    private var grace: TimeInterval = 0
    private var handover: TimeInterval = 0
    private var quiet: TimeInterval = 0
    private var holds: (TimeInterval, TimeInterval) = (0, 0)
    private var voiceMuted: Any?

    override func setUp() async throws {
        grace = Conversation.closeGrace; Conversation.closeGrace = 0
        handover = QuickTalkModel.handoverGrace; QuickTalkModel.handoverGrace = 0.15
        quiet = QuickTalkModel.quietLimit
        holds = (QuickTalkModel.momentHold, QuickTalkModel.reactionHold)
        voiceMuted = UserDefaults.standard.object(forKey: Conversation.voiceMutedKey)
        UserDefaults.standard.removeObject(forKey: Conversation.voiceMutedKey)
    }

    override func tearDown() async throws {
        Conversation.closeGrace = grace
        QuickTalkModel.handoverGrace = handover
        QuickTalkModel.quietLimit = quiet
        (QuickTalkModel.momentHold, QuickTalkModel.reactionHold) = holds
        if let voiceMuted { UserDefaults.standard.set(voiceMuted, forKey: Conversation.voiceMutedKey) }
        else { UserDefaults.standard.removeObject(forKey: Conversation.voiceMutedKey) }
    }

    /// Everything a quick talk touches, on stand-ins: each conversation the model makes gets its own audio and socket.
    private final class Rig {
        var audios: [QuickAudio] = []
        var links: [QuickLink] = []
        var app: AppModel!
        var model: QuickTalkModel!
        var opened: [KaikuTab?] = []
        var mainShowsTalk = false
        var dir: URL!
        var audio: QuickAudio { audios.last! }
        var link: QuickLink { links.last! }
    }

    private func rig(paired: Bool = true, onboarded: Bool = true) -> Rig {
        let r = Rig()
        r.dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try! FileManager.default.createDirectory(at: r.dir, withIntermediateDirectories: true)
        let p = paired ? Pairing(baseURL: URL(string: "https://quick.test")!, homeID: "synthetic", token: "synthetic-pairing-token") : nil
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [QuickHTTP.self]
        let defaults = UserDefaults(suiteName: UUID().uuidString)!
        defaults.set(true, forKey: "kaikuMute")
        defaults.set(onboarded, forKey: "kaiku.onboarded")
        defaults.set(true, forKey: "kaiku.serviceAutoDisabled")   // never look for a service on the network
        r.app = AppModel(defaults: defaults, pairing: p, api: APIClient(pairing: p, maxAttempts: 1, session: URLSession(configuration: config)),
                         queue: OfflineQueue(url: r.dir.appendingPathComponent("events.json")),
                         episodes: EpisodeOutbox(url: r.dir.appendingPathComponent("episodes.json")))
        let talk = TalkModel(makeConversation: {
            let audio = QuickAudio(), link = QuickLink()
            r.audios.append(audio); r.links.append(link)
            return Conversation(surface: .mac, intent: .talk, audio: audio, transport: { event in link.event = event; return link },
                                permission: { true }, localListener: false, purpose: .talk)
        })
        r.model = QuickTalkModel(defaults: defaults, talk: talk)
        r.model.micPermission = { .granted }
        r.model.mainShowsTalk = { r.mainShowsTalk }
        r.model.openMain = { r.opened.append($0) }
        return r
    }

    private func settle(_ seconds: Double = 0.08) async { try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000)) }

    /// Opens the panel and plays Live's "ready".
    private func openLive(_ r: Rig) async {
        r.model.open(app: r.app)
        for _ in 0..<40 where !r.link.connected { await settle(0.05) }
        XCTAssertTrue(r.link.connected, "the conversation reached the socket")
        r.link.event?(.ready)
        await settle()
    }

    func testSettingsAreStoredAndDefaultSafe() {
        let defaults = UserDefaults(suiteName: UUID().uuidString)!
        let model = QuickTalkModel(defaults: defaults, talk: TalkModel(makeConversation: {
            Conversation(surface: .mac, intent: .talk, audio: QuickAudio(), transport: { _ in QuickLink() }, permission: { true }, localListener: false)
        }))
        XCTAssertTrue(model.enabled); XCTAssertEqual(model.doubleTap, .control); XCTAssertTrue(model.captions)   // ⌃⌃ needs no permission
        XCTAssertTrue(model.showBar)
        var changes = 0
        model.settingsChanged = { changes += 1 }
        model.enabled = false; model.doubleTap = .option; model.captions = false; model.showBar = false
        XCTAssertEqual(changes, 3)   // the shell re-arms and shows or hides the bar; captions need nothing of it
        let again = QuickTalkModel(defaults: defaults, talk: model.talk)
        XCTAssertFalse(again.enabled); XCTAssertEqual(again.doubleTap, .option); XCTAssertFalse(again.captions); XCTAssertFalse(again.showBar)
    }

    func testTheBarThePillAndThePopupAreStagesOfOneShape() async {
        let r = rig()
        defer { try? FileManager.default.removeItem(at: r.dir) }
        r.model.inert = true   // only the shape here: nothing starts
        XCTAssertEqual(r.model.stage, .bar)
        r.model.hovering = true
        XCTAssertEqual(r.model.stage, .pill)
        // the pill's first button before the shell handed the app over does nothing; after, it opens the popup
        r.model.perform(.start)
        XCTAssertEqual(r.model.stage, .pill)
        r.model.attach(app: r.app)
        r.model.perform(.start)
        XCTAssertEqual(r.model.stage, .popup); XCTAssertTrue(r.model.isOpen)
        XCTAssertFalse(r.model.hovering, "the popup closes back to the bar, not to the pill")
        r.model.close()
        XCTAssertEqual(r.model.stage, .bar)
        // the pill's second button opens Kaiku where it is, and starts nothing
        r.model.hovering = true
        r.model.perform(.openKaiku)
        XCTAssertEqual(r.opened, [nil]); XCTAssertFalse(r.model.isOpen); XCTAssertEqual(r.model.stage, .bar)
        XCTAssertEqual(r.model.startAttempts, 0)
        // the bar turned off: nothing at rest, the trigger still grows the popup (from the edge)
        r.model.showBar = false
        XCTAssertEqual(r.model.stage, .hidden)
        r.model.hovering = true
        XCTAssertEqual(r.model.stage, .hidden)
        r.model.open(app: r.app)
        XCTAssertEqual(r.model.stage, .popup)
        r.model.close()
        XCTAssertEqual(r.model.stage, .hidden)
        // quick talk turned off: nothing
        r.model.showBar = true; r.model.enabled = false
        XCTAssertEqual(r.model.stage, .hidden)
    }

    func testPuttingThePopupAwayKeepsTheConversation() async {
        let r = rig()
        defer { try? FileManager.default.removeItem(at: r.dir) }
        r.model.showBar = false   // even so: an open microphone is never out of sight
        XCTAssertNil(r.model.call); XCTAssertFalse(r.model.isLive)
        await openLive(r)
        let conversation = r.model.talk.conversation
        XCTAssertNil(r.model.call.flatMap { _ in r.model.isOpen ? nil : 1 }, "the island shows a call only while the popup is away")
        r.model.perform(.collapse)
        XCTAssertFalse(r.model.isOpen)
        XCTAssertTrue(r.model.talk.hasLive); XCTAssertTrue(r.audio.running); XCTAssertTrue(r.audio.mic)
        XCTAssertEqual(r.model.stage, .bar); XCTAssertTrue(r.model.isLive)
        XCTAssertEqual(r.model.call?.status, .listening); XCTAssertEqual(r.model.call?.micOn, true); XCTAssertNotNil(r.model.call?.since)
        XCTAssertTrue(r.model.meter.micOpen)
        // muting from the island is the call's own mute
        r.model.perform(.microphone)
        XCTAssertEqual(r.model.call?.status, .muted); XCTAssertEqual(r.model.call?.micOn, false); XCTAssertFalse(r.audio.mic)
        XCTAssertFalse(r.model.meter.micOpen); XCTAssertEqual(r.model.meter.level, 0)
        r.model.perform(.microphone)
        // the words keep coming while it is away
        r.link.event?(.userText("Still here"))
        await settle()
        // the pointer at the bar: the pill (show it, end it); "show" brings the same conversation back, nothing restarts
        r.model.hovering = true
        XCTAssertEqual(r.model.stage, .pill)
        r.model.perform(.show)
        await settle()
        XCTAssertTrue(r.model.isOpen); XCTAssertEqual(r.model.stage, .popup)
        XCTAssertTrue(r.model.talk.conversation === conversation); XCTAssertEqual(r.model.startAttempts, 1)
        XCTAssertEqual(r.model.display.person, "Still here"); XCTAssertEqual(r.model.display.state, .hearing)
        // away again, then ended from the pill (or the island): everything stops, and the bar goes with it
        r.model.perform(.collapse)
        XCTAssertEqual(r.model.stage, .bar)
        let audio = r.audio, link = r.link
        r.model.perform(.end)
        XCTAssertFalse(r.model.talk.hasLive); XCTAssertFalse(audio.running); XCTAssertFalse(audio.mic); XCTAssertTrue(link.closed)
        XCTAssertNil(r.model.call); XCTAssertEqual(r.model.stage, .hidden)
        // with nothing live there is nothing to keep: putting the popup away closes it
        r.model.inert = true
        r.model.open(app: r.app)
        r.model.perform(.collapse)
        XCTAssertFalse(r.model.isOpen); XCTAssertEqual(r.model.stage, .hidden)
    }

    func testAConversationPutAwayAndLeftQuietEndsByItself() async {
        QuickTalkModel.quietLimit = 0.4
        let r = rig()
        defer { try? FileManager.default.removeItem(at: r.dir) }
        await openLive(r)
        let audio = r.audio
        r.model.perform(.collapse)
        // the person keeps talking: it stays
        for _ in 0..<6 {
            r.link.event?(.userText(" and"))
            await settle(0.15)
        }
        XCTAssertTrue(r.model.talk.hasLive, "still talking")
        XCTAssertTrue(audio.mic)
        // nobody says anything: it ends by itself
        for _ in 0..<30 where r.model.talk.hasLive { await settle(0.1) }
        XCTAssertFalse(r.model.talk.hasLive); XCTAssertFalse(audio.running); XCTAssertFalse(audio.mic)
        XCTAssertNil(r.model.call)
    }

    func testAnOpenPopupIsNeverEndedForBeingQuiet() async {
        QuickTalkModel.quietLimit = 0.3
        let r = rig()
        defer { try? FileManager.default.removeItem(at: r.dir) }
        await openLive(r)
        r.model.perform(.collapse)
        await settle(0.1)
        r.model.perform(.show)      // back in sight before the limit
        await settle(0.8)
        XCTAssertTrue(r.model.isOpen); XCTAssertTrue(r.model.talk.hasLive); XCTAssertTrue(r.audio.mic)
        r.model.close()
    }

    func testEndCallEndsItWhereverItShows() async {
        let r = rig()
        defer { try? FileManager.default.removeItem(at: r.dir) }
        // in the popup
        await openLive(r)
        var audio = r.audio
        r.model.perform(.end)
        XCTAssertFalse(r.model.isOpen); XCTAssertFalse(audio.running); XCTAssertFalse(r.model.talk.hasLive)
        // on the Talk screen too (Esc would leave it there; End call is the person ending it)
        r.mainShowsTalk = true
        await r.model.talk.start(app: r.app)
        r.link.event?(.ready)
        await settle()
        audio = r.audio
        r.model.open(app: r.app)
        await settle()
        r.model.perform(.end)
        XCTAssertFalse(r.model.isOpen); XCTAssertFalse(r.model.talk.hasLive); XCTAssertFalse(audio.mic)
    }

    func testKaikuReactsToWhatReallyHappens() async {
        QuickTalkModel.reactionHold = 0.25; QuickTalkModel.momentHold = 0.5
        QuickHTTP.stance = "celebrate"
        let r = rig()
        defer { try? FileManager.default.removeItem(at: r.dir); QuickHTTP.stance = "comfort" }
        await openLive(r)
        XCTAssertNil(r.model.display.reaction); XCTAssertEqual(r.model.display.mascot, .listening)
        // the model's own `express` call: Kaiku is proud of them
        r.link.event?(.toolCall(id: "e1", name: "express", args: ["feeling": .string("proud")]))
        for _ in 0..<20 where r.model.display.reaction == nil { await settle(0.02) }
        XCTAssertEqual(r.model.display.reaction, .sparkle); XCTAssertEqual(r.model.display.mascot, .cheering)
        // the small reaction goes first, then the face
        for _ in 0..<40 where r.model.display.reaction != nil { await settle(0.05) }
        XCTAssertNil(r.model.display.reaction)
        // good news noticed by the cloud's `feel` plan: a sparkle
        r.link.event?(.toolCall(id: "f1", name: "feel", args: ["feeling": .string("glad")]))
        for _ in 0..<40 where r.model.display.reaction == nil { await settle(0.05) }
        XCTAssertEqual(r.model.talk.conversation.plan?.stance, "celebrate")
        XCTAssertEqual(r.model.display.reaction, .sparkle); XCTAssertEqual(r.model.display.mascot, .happy)
        for _ in 0..<40 where r.model.display.reaction != nil { await settle(0.05) }
        // a heavy moment: cozy and a small heart, and from then on no sparkle even when the model says "happy"
        QuickHTTP.stance = "comfort"
        r.link.event?(.toolCall(id: "f2", name: "feel", args: ["feeling": .string("low")]))
        for _ in 0..<40 where r.model.display.reaction == nil { await settle(0.05) }
        XCTAssertEqual(r.model.talk.conversation.plan?.stance, "comfort")
        XCTAssertEqual(r.model.display.reaction, .heart); XCTAssertEqual(r.model.display.mascot, .cozy)
        for _ in 0..<40 where r.model.display.reaction != nil { await settle(0.05) }
        r.link.event?(.toolCall(id: "e2", name: "express", args: ["feeling": .string("happy")]))
        for _ in 0..<20 where r.model.display.reaction == nil { await settle(0.02) }
        XCTAssertEqual(r.model.display.reaction, .heart); XCTAssertEqual(r.model.display.mascot, .cozy)
        // nothing is left showing once the conversation is over
        r.model.close()
        XCTAssertNil(r.model.display.reaction)
    }

    func testAFindIsASmallSparkleAndAnEmptyAnswerIsNothing() async {
        QuickTalkModel.reactionHold = 0.25; QuickTalkModel.momentHold = 0.4
        let r = rig()
        defer { try? FileManager.default.removeItem(at: r.dir); QuickHTTP.tool = nil }
        await openLive(r)
        // recall came back empty: nothing to show
        QuickHTTP.tool = #"{"ok":true,"name":"recall","result":{"memories":[]}}"#
        r.link.event?(.toolCall(id: "r1", name: "recall", args: ["topic": .string("walks")]))
        await settle(0.4)
        XCTAssertNil(r.model.display.reaction)
        // Kaiku remembers something about them
        QuickHTTP.tool = #"{"ok":true,"name":"recall","result":{"memories":["Likes walking by the lake"]}}"#
        r.link.event?(.toolCall(id: "r2", name: "recall", args: ["topic": .string("walks")]))
        for _ in 0..<40 where r.model.display.reaction == nil { await settle(0.05) }
        XCTAssertEqual(r.model.display.reaction, .sparkle)
        XCTAssertNotEqual(r.model.display.mascot, .happy, "its face stays with the call")
        for _ in 0..<40 where r.model.display.reaction != nil { await settle(0.05) }
        XCTAssertNil(r.model.display.reaction)
        r.model.close()
    }

    func testOpeningStartsARealConversationAndThePersonSpeaksFirst() async {
        let r = rig()
        defer { try? FileManager.default.removeItem(at: r.dir) }
        r.model.open(app: r.app)
        XCTAssertTrue(r.model.isOpen)
        XCTAssertEqual(r.model.display.state, .connecting)
        XCTAssertFalse(r.model.display.micLive, "not live before Live answers")
        for _ in 0..<40 where !r.link.connected { await settle(0.05) }
        XCTAssertEqual(r.model.talk.conversation.surface, .mac)
        XCTAssertEqual(r.model.talk.conversation.purpose, .talk)
        XCTAssertFalse(r.audio.mic, "the microphone opens only when Live is ready")
        r.link.event?(.ready)
        await settle()
        XCTAssertEqual(r.model.display.state, .listening)
        XCTAssertTrue(r.model.display.micLive); XCTAssertTrue(r.audio.mic); XCTAssertTrue(r.audio.running)
        XCTAssertTrue(r.link.contexts.isEmpty, "Kaiku is not asked to greet: the person speaks first")
        XCTAssertEqual(r.model.startAttempts, 1)
        // the person's words as they are transcribed, then Kaiku's line
        r.link.event?(.userText("I'm not feeling"))
        await settle()
        XCTAssertEqual(r.model.display.state, .hearing)
        XCTAssertEqual(r.model.display.person, "I'm not feeling")
        r.link.event?(.userText(" too well"))
        r.link.event?(.kaikuText("That sounds heavy."))
        await settle()
        XCTAssertEqual(r.model.display.person, "I'm not feeling too well")
        XCTAssertEqual(r.model.display.kaiku, "That sounds heavy.")
        // it is the Talk screen's conversation, word for word
        XCTAssertEqual(r.model.talk.lines.map(\.text), ["I'm not feeling too well", "That sounds heavy."])
        r.model.close()
    }

    func testMutingMeAndMutingKaikuAreIndependent() async {
        let r = rig()
        defer { try? FileManager.default.removeItem(at: r.dir) }
        await openLive(r)
        r.model.perform(.microphone)
        XCTAssertEqual(r.model.display.state, .muted); XCTAssertFalse(r.model.display.micLive); XCTAssertFalse(r.audio.mic)
        XCTAssertEqual(r.model.display.mascot, .sleepy)
        XCTAssertFalse(r.model.display.voiceMuted)
        r.model.perform(.voice)
        XCTAssertTrue(r.model.display.voiceMuted)
        // captions keep coming with both muted
        r.link.event?(.kaikuText("Still here."))
        await settle()
        XCTAssertEqual(r.model.display.kaiku, "Still here.")
        r.model.perform(.microphone)
        XCTAssertEqual(r.model.display.state, .listening); XCTAssertTrue(r.model.display.micLive); XCTAssertTrue(r.audio.mic)
        XCTAssertTrue(r.model.display.voiceMuted, "unmuting me leaves Kaiku's voice as it was")
        r.model.perform(.voice)
        XCTAssertFalse(r.model.display.voiceMuted)
        r.model.close()
    }

    func testClosingEndsTheConversationLikeLeavingTalk() async {
        let r = rig()
        defer { try? FileManager.default.removeItem(at: r.dir) }
        await openLive(r)
        let audio = r.audio, link = r.link, conversation = r.model.talk.conversation
        r.model.perform(.close)
        XCTAssertFalse(r.model.isOpen)
        XCTAssertFalse(audio.running); XCTAssertFalse(audio.mic); XCTAssertTrue(link.closed)
        XCTAssertEqual(conversation.phase, .idle)
        XCTAssertFalse(r.model.talk.conversation === conversation, "the next quick talk is a new conversation")
        XCTAssertFalse(r.model.talk.hasLive)
        // …and the next one opens the same way
        await openLive(r)
        XCTAssertEqual(r.model.display.state, .listening)
        XCTAssertEqual(r.model.startAttempts, 2)
        r.model.close()
    }

    func testTheTalkScreenKeepsAConversationItIsShowing() async {
        let r = rig()
        defer { try? FileManager.default.removeItem(at: r.dir) }
        // Talk is open in the main window with a live conversation
        r.mainShowsTalk = true
        await r.model.talk.start(app: r.app)
        r.link.event?(.ready)
        await settle()
        let conversation = r.model.talk.conversation
        XCTAssertTrue(r.model.talk.hasLive)
        // quick talk shows that same conversation and starts nothing
        r.model.open(app: r.app)
        await settle()
        XCTAssertEqual(r.model.startAttempts, 0)
        XCTAssertTrue(r.model.talk.conversation === conversation)
        XCTAssertEqual(r.model.display.state, .listening)
        // closing the panel leaves it with the Talk screen
        r.model.close()
        XCTAssertFalse(r.model.isOpen)
        XCTAssertTrue(r.model.talk.hasLive); XCTAssertTrue(r.audio.running)
        r.model.talk.stop()
    }

    func testContinueInKaikuHandsTheSameConversationOver() async {
        let r = rig()
        defer { try? FileManager.default.removeItem(at: r.dir) }
        await openLive(r)
        r.link.event?(.userText("Carry this on"))
        await settle()
        let conversation = r.model.talk.conversation
        r.app.selectedTab = .today
        r.model.openMain = { tab in r.opened.append(tab); r.mainShowsTalk = true }   // the window comes up on Talk
        r.model.perform(.continueInKaiku)
        XCTAssertFalse(r.model.isOpen)
        XCTAssertEqual(r.opened, [.talk]); XCTAssertEqual(r.app.selectedTab, .talk)
        await settle(0.4)   // past the hand-over grace
        XCTAssertTrue(r.model.talk.conversation === conversation)
        XCTAssertTrue(r.model.talk.hasLive); XCTAssertTrue(r.audio.mic)
        XCTAssertEqual(r.model.talk.lines.map(\.text), ["Carry this on"])
        // the Talk screen's own model is this one (what `TalkView(model: .forTalkScreen())` is given on the Mac)
        XCTAssertTrue(TalkModel.forTalkScreen() === QuickTalkModel.shared.talk)
        r.model.talk.stop()
    }

    func testAHandOverThatNeverArrivesDoesNotKeepListening() async {
        let r = rig()
        defer { try? FileManager.default.removeItem(at: r.dir) }
        await openLive(r)
        let audio = r.audio
        r.model.perform(.continueInKaiku)      // the main window never shows Talk (say, setup is running there)
        XCTAssertTrue(audio.running)
        await settle(0.5)
        XCTAssertFalse(audio.running); XCTAssertFalse(audio.mic)
        XCTAssertFalse(r.model.talk.hasLive)
    }

    func testNothingStartsWhenKaikuCannotListen() async {
        // not connected
        var r = rig(paired: false)
        r.model.open(app: r.app)
        await settle(0.3)
        XCTAssertEqual(r.model.display.state, .notConnected)
        XCTAssertFalse(r.audio.running); XCTAssertFalse(r.link.connected); XCTAssertFalse(r.model.display.micLive)
        // its one help: open Kaiku on You, where the service is
        r.model.perform(.help)
        XCTAssertFalse(r.model.isOpen); XCTAssertEqual(r.opened, [.you]); XCTAssertEqual(r.app.selectedTab, .you)
        try? FileManager.default.removeItem(at: r.dir)

        // paused: never even attempted
        r = rig()
        r.app.pausedAll = true
        r.model.open(app: r.app)
        await settle(0.2)
        XCTAssertEqual(r.model.display.state, .paused); XCTAssertEqual(r.model.startAttempts, 0)
        XCTAssertFalse(r.audio.running); XCTAssertFalse(r.link.connected)
        r.model.close()
        try? FileManager.default.removeItem(at: r.dir)

        // microphone permission off: never attempted, and the help is System Settings
        r = rig()
        var settings = 0
        r.model.micPermission = { .denied }
        r.model.openMicrophoneSettings = { settings += 1 }
        r.model.open(app: r.app)
        await settle(0.2)
        XCTAssertEqual(r.model.display.state, .micDenied); XCTAssertEqual(r.model.startAttempts, 0)
        r.model.perform(.help)
        XCTAssertEqual(settings, 1); XCTAssertFalse(r.model.isOpen)
        try? FileManager.default.removeItem(at: r.dir)

        // setup not finished: that comes first
        r = rig(onboarded: false)
        r.model.open(app: r.app)
        await settle(0.2)
        XCTAssertEqual(r.model.display.state, .setup); XCTAssertEqual(r.model.startAttempts, 0)
        r.model.perform(.help)
        XCTAssertEqual(r.opened, [nil])
        try? FileManager.default.removeItem(at: r.dir)
    }

    /// Layout-snapshot and inspection runs: the panel can be opened and looked at, nothing ever starts.
    func testAnInertRunNeverStartsAConversation() async {
        let r = rig()
        defer { try? FileManager.default.removeItem(at: r.dir) }
        r.model.inert = true
        let before = QuickHTTP.sessions
        r.model.open(app: r.app)
        await settle(0.3)
        XCTAssertTrue(r.model.isOpen)
        XCTAssertEqual(r.model.startAttempts, 0)
        XCTAssertFalse(r.audio.running); XCTAssertFalse(r.audio.mic); XCTAssertFalse(r.link.connected)
        XCTAssertEqual(QuickHTTP.sessions, before, "no session was asked for")
        XCTAssertFalse(r.model.display.micLive)
        r.model.close()
    }

    func testPausingEverythingClosesTheMicrophoneAndSaysSo() async {
        let r = rig()
        defer { try? FileManager.default.removeItem(at: r.dir) }
        await openLive(r)
        r.app.pausedAll = true
        await settle(0.2)
        XCTAssertEqual(r.model.display.state, .paused)
        XCTAssertFalse(r.model.display.micLive); XCTAssertFalse(r.audio.running); XCTAssertFalse(r.audio.mic)
        r.model.close()
    }

    func testACrisisBringsTheMainWindowForward() async {
        let r = rig()
        defer { try? FileManager.default.removeItem(at: r.dir) }
        await openLive(r)
        let audio = r.audio
        r.link.event?(.userText("I want to kill myself"))
        for _ in 0..<20 where !r.app.showCrisis { await settle(0.05) }
        XCTAssertTrue(r.app.showCrisis, "the deterministic crisis path ran")
        await settle(0.2)
        XCTAssertFalse(r.model.isOpen, "the panel steps aside")
        XCTAssertEqual(r.opened, [nil], "the crisis screen lives in the main window: it comes forward as it is")
        XCTAssertFalse(audio.running); XCTAssertFalse(audio.mic)
    }

    func testEndedFromTheMainWindowClosesThePanel() async {
        let r = rig()
        defer { try? FileManager.default.removeItem(at: r.dir) }
        // Talk is open in the main window with a live conversation, and quick talk is showing it too
        r.mainShowsTalk = true
        await r.model.talk.start(app: r.app)
        r.link.event?(.ready)
        await settle()
        r.model.open(app: r.app)
        await settle()
        XCTAssertTrue(r.model.isOpen); XCTAssertEqual(r.model.display.state, .listening)
        // the person leaves Talk in the main window: that screen stops the conversation
        r.mainShowsTalk = false
        r.model.talk.stop()
        await settle(0.2)
        XCTAssertFalse(r.model.isOpen)
        XCTAssertFalse(r.model.talk.hasLive)
    }

    func testTryAgainAfterAnEndedConversation() async {
        let r = rig()
        defer { try? FileManager.default.removeItem(at: r.dir) }
        await openLive(r)
        r.model.talk.end()   // the conversation ended (the session limit, or Kaiku said goodbye)
        await settle()
        XCTAssertEqual(r.model.display.state, .ended); XCTAssertFalse(r.model.display.micLive)
        XCTAssertTrue(r.model.isOpen)
        r.model.perform(.help)
        for _ in 0..<40 where r.links.count < 3 || !r.link.connected { await settle(0.05) }
        r.link.event?(.ready)
        await settle()
        XCTAssertEqual(r.model.display.state, .listening); XCTAssertTrue(r.model.display.micLive)
        r.model.close()
    }
}

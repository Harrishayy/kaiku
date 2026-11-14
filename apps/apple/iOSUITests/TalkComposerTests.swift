import XCTest

/// Talk is a call. These run on the scripted Live of Debug builds (`-kaikuTalkDemo live`: the real conversation
/// engine and screens; the socket and the audio are stand-ins), so nothing opens the microphone and no model is
/// called. They need any reachable cloud to pair with (`KAIKU_TEST_CLOUD`).
private func launchCall(_ extra: [String] = []) -> XCUIApplication {
    let env = ProcessInfo.processInfo.environment
    let cloud = env["KAIKU_TEST_CLOUD"] ?? "http://127.0.0.1:8000"
    let home = env["KAIKU_TEST_HOME"] ?? "aino"
    let app = XCUIApplication()
    app.launchArguments = ["-kaiku.lang", "en", "-AppleLanguages", "(en)", "-kaikuMute", "YES", "-kaikuSkipOnboarding", "YES",
                           "-kaikuPairLink", "\(cloud)/?home=\(home)", "-kaikuTab", "talk", "-kaikuTalkDemo", "live",
                           "-kaiku.talk.voiceMuted", "NO"] + extra
    app.launch()
    return app
}

private func labelled(_ text: String) -> NSPredicate { NSPredicate(format: "label CONTAINS[c] %@", text) }

/// Regression (2026-11-14): tapping the message field in Talk hung the app (an endless SwiftUI update cycle in the
/// transcript). Typing is now folded away behind the call bar's keyboard button; it must still never block.
final class TalkComposerTests: XCTestCase {
    func testTypingInACallStaysResponsive() {
        let app = launchCall()
        let type = app.buttons["call.type"].firstMatch
        XCTAssertTrue(type.waitForExistence(timeout: 20), "the call bar is there once Kaiku is on the line")
        XCTAssertFalse(app.textFields["Type a message"].exists, "typing is folded away until wanted")
        type.tap()
        let composer = app.textFields["Type a message"].firstMatch
        XCTAssertTrue(composer.waitForExistence(timeout: 5))
        let started = Date()
        composer.tap()
        composer.typeText("I walked to the lake today.")
        app.buttons["Send"].firstMatch.tap()
        XCTAssertTrue(app.staticTexts["I walked to the lake today."].firstMatch.waitForExistence(timeout: 10),
                      "the typed message appears as a caption")
        XCTAssertLessThan(Date().timeIntervalSince(started), 45, "typing must not wait on a busy main thread")
        let again = app.textFields.firstMatch
        again.tap()
        again.typeText("It was quiet there.")
        app.buttons["Send"].firstMatch.tap()
        XCTAssertTrue(app.staticTexts["It was quiet there."].firstMatch.waitForExistence(timeout: 10),
                      "the app still answers after typing in Talk")
    }
}

/// The call bar in the app, and the call outside it: Dynamic Island, Lock Screen, and their buttons acting on the
/// open call without opening the app. Screenshots go to `$KAIKU_SHOT_DIR` when set.
final class CallOutsideTests: XCTestCase {
    let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")

    override func setUp() { continueAfterFailure = true }

    func shot(_ name: String) {
        let s = XCUIScreen.main.screenshot()
        let a = XCTAttachment(screenshot: s)
        a.name = name; a.lifetime = .keepAlways
        add(a)
        if let dir = ProcessInfo.processInfo.environment["KAIKU_SHOT_DIR"] {
            try? s.pngRepresentation.write(to: URL(fileURLWithPath: dir).appendingPathComponent("\(name).png"))
        }
    }

    func testTwoMutesInTheCallBar() {
        let app = launchCall()
        let state = app.descendants(matching: .any).matching(identifier: "call.state").firstMatch
        XCTAssertTrue(state.waitForExistence(timeout: 20))
        XCTAssertTrue(app.descendants(matching: .any).matching(labelled("Listening")).firstMatch.waitForExistence(timeout: 5))
        let mic = app.buttons["call.mic"].firstMatch, voice = app.buttons["call.voice"].firstMatch
        XCTAssertEqual(mic.label, "Mute yourself")
        mic.tap()
        XCTAssertTrue(app.descendants(matching: .any).matching(labelled("You are muted")).firstMatch.waitForExistence(timeout: 5))
        XCTAssertEqual(mic.label, "Unmute yourself")
        XCTAssertEqual(voice.label, "Mute Kaiku", "the two mutes are independent")
        voice.tap()
        XCTAssertEqual(voice.label, "Unmute Kaiku")
        XCTAssertEqual(mic.label, "Unmute yourself")
        mic.tap()
        XCTAssertTrue(app.descendants(matching: .any).matching(labelled("Listening")).firstMatch.waitForExistence(timeout: 5))
        voice.tap()
        XCTAssertEqual(voice.label, "Mute Kaiku")
        app.buttons["call.end"].firstMatch.tap()
        XCTAssertTrue(app.staticTexts["Call ended."].firstMatch.waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Out for a coffee, even tired. That counts for something."].firstMatch.exists, "the words stay")
        XCTAssertTrue(app.buttons["Call Kaiku"].firstMatch.exists)
    }

    func testTheCallGoesOnOutsideTheAppAndItsButtonsWork() {
        let app = launchCall()
        XCTAssertTrue(app.buttons["call.mic"].firstMatch.waitForExistence(timeout: 20))
        sleep(2)
        shot("call-in-app")
        XCUIDevice.shared.press(.home)
        sleep(3)
        shot("call-island-compact")
        springboard.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.03)).press(forDuration: 1.2)
        sleep(2)
        shot("call-island-expanded")
        let mute = springboard.buttons["Mute"].firstMatch
        if mute.waitForExistence(timeout: 3) {
            mute.tap()
            XCTAssertTrue(springboard.buttons["Unmute"].firstMatch.waitForExistence(timeout: 6), "muted from the island, the app stayed closed")
            sleep(1)
            shot("call-island-muted")
            springboard.buttons["Unmute"].firstMatch.tap()
            XCTAssertTrue(springboard.buttons["Mute"].firstMatch.waitForExistence(timeout: 6))
        } else {
            XCTFail("the expanded island shows no Mute button")
        }
        XCUIDevice.shared.press(.home)
        sleep(1)
        // Lock, then wake to the Lock Screen.
        XCUIDevice.shared.perform(NSSelectorFromString("pressLockButton"))
        sleep(2)
        XCUIDevice.shared.press(.home)
        sleep(2)
        shot("call-lock-screen")
        let lockMute = springboard.buttons["Mute"].firstMatch
        XCTAssertTrue(lockMute.waitForExistence(timeout: 6), "the Lock Screen bar has its buttons")
        lockMute.tap()
        XCTAssertTrue(springboard.buttons["Unmute"].firstMatch.waitForExistence(timeout: 6), "muted from the Lock Screen")
        XCTAssertTrue(springboard.staticTexts.matching(labelled("You are muted")).firstMatch.waitForExistence(timeout: 6),
                      "and the bar says the microphone is closed")
        sleep(1)
        shot("call-lock-muted")
        let kaiku = springboard.buttons["Mute Kaiku"].firstMatch
        if kaiku.exists {
            kaiku.tap()
            XCTAssertTrue(springboard.buttons["Unmute Kaiku"].firstMatch.waitForExistence(timeout: 6), "Kaiku's voice muted from the Lock Screen")
            sleep(1)
            shot("call-lock-both-muted")
        }
        springboard.buttons["End"].firstMatch.tap()
        sleep(3)
        shot("call-lock-ended")
        XCTAssertFalse(springboard.buttons["End"].firstMatch.exists, "ended from the Lock Screen: the bar is gone")
        XCUIDevice.shared.press(.home)
        sleep(1)
        app.activate()
        XCTAssertTrue(app.staticTexts["Call ended."].firstMatch.waitForExistence(timeout: 10), "and the call really ended in the app")
        shot("call-after-end")
    }

    /// Opt-in, PAID (one real Gemini Live call of about five minutes, typed, never the microphone): the call goes on
    /// with the phone locked, past the life of one Live token. Launch arguments type a message every
    /// `KAIKU_CALL_LIVE_DELAY` seconds (default 85: inside the 180 s quiet limit that ends a call left in a pocket);
    /// Kaiku's answers must show up as the caption on the Lock Screen bar, the last one after the call has moved
    /// to its next token; "End" on the Lock Screen ends it.
    /// `TEST_RUNNER_KAIKU_CALL_LIVE_CLOUD=http://127.0.0.1:<port>` (a private cloud with a model key);
    /// `TEST_RUNNER_KAIKU_CALL_TRACE=<file>` writes the connection events (no words).
    func testARealCallGoesOnWhileThePhoneIsLocked() throws {
        let env = ProcessInfo.processInfo.environment
        guard let cloud = env["KAIKU_CALL_LIVE_CLOUD"], !cloud.isEmpty else { throw XCTSkip("set KAIKU_CALL_LIVE_CLOUD (paid)") }
        let home = env["KAIKU_CALL_LIVE_HOME"] ?? "call-\(Int(Date().timeIntervalSince1970))"
        let delay = Int(env["KAIKU_CALL_LIVE_DELAY"] ?? "") ?? 85
        let first = "Hello Kaiku. I am typing because my microphone is off."
        let later = ["I am out for a slow walk now. It is grey but dry.",
                     "I just passed the bakery. It smells of cinnamon.",
                     "I am nearly home. What was the first thing I told you about the weather?"]
        let app = XCUIApplication()
        app.launchArguments = ["-kaiku.lang", "en", "-AppleLanguages", "(en)", "-kaikuMute", "YES", "-kaikuSkipOnboarding", "YES",
                               "-kaikuPairLink", "\(cloud)/?home=\(home)", "-kaikuTab", "talk", "-kaiku.talk.voiceMuted", "NO",
                               "-kaikuTalkSay", first, "-kaikuTalkSayLater", later.joined(separator: "|"), "-kaikuTalkSayDelay", "\(delay)"]
        if let trace = env["KAIKU_CALL_TRACE"] { app.launchArguments += ["-kaikuCallTrace", trace] }
        app.launch()
        XCTAssertTrue(app.buttons["call.end"].firstMatch.waitForExistence(timeout: 40), "Kaiku is on the line")
        XCTAssertTrue(app.staticTexts[first].firstMatch.waitForExistence(timeout: 30), "the first typed message went out")
        let typedFirst = Date()
        sleep(9)                                   // Kaiku's answer to it
        shot("real-in-app")
        XCUIDevice.shared.press(.home)
        sleep(2)
        shot("real-island")
        XCUIDevice.shared.perform(NSSelectorFromString("pressLockButton"))
        sleep(2)
        XCUIDevice.shared.press(.home)             // wake to the Lock Screen
        sleep(2)
        shot("real-lock-0")
        var seen = [barTexts()]
        print("LOCK-0 \(seen[0])")
        // Each later message goes out while the phone is locked; look about 20 s after each.
        for n in 1...later.count {
            let at = typedFirst.addingTimeInterval(Double(n * delay) + 20)
            while Date() < at { sleep(2) }
            let texts = barTexts()
            shot("real-lock-\(n)")
            print("LOCK-\(n) \(texts)")
            XCTAssertTrue(texts.contains { $0.contains("Talking with Kaiku") }, "message \(n): the bar is still on the Lock Screen")
            XCTAssertNotEqual(texts.filter { $0.count > 24 }, seen.last!.filter { $0.count > 24 }, "message \(n): the caption moved on while locked")
            seen.append(texts)
        }
        let end = springboard.buttons["End"].firstMatch
        XCTAssertTrue(end.waitForExistence(timeout: 5), "the call is still open")
        end.tap()
        sleep(3)
        shot("real-lock-ended")
        XCTAssertFalse(springboard.buttons["End"].firstMatch.exists, "ended from the Lock Screen")
        XCUIDevice.shared.press(.home)
        sleep(1)
        app.activate()
        XCTAssertTrue(app.staticTexts["Call ended."].firstMatch.waitForExistence(timeout: 10))
        shot("real-after-end")
        let captions = texts(app)
        print("CAPTIONS \(captions)")
        for message in later { XCTAssertTrue(captions.contains(message), "typed while locked, in the captions: \(message)") }
    }

    /// What the Lock Screen shows. The simulator's Lock Screen stays awake; if it did go dark, wake it once.
    private func barTexts() -> [String] {
        var t = texts(springboard)
        if !t.contains(where: { $0.contains("Talking with Kaiku") }) { XCUIDevice.shared.press(.home); sleep(2); t = texts(springboard) }
        return t
    }

    /// The texts on screen from ONE snapshot (element-by-element queries race with a screen that is changing).
    private func texts(_ root: XCUIApplication) -> [String] {
        root.debugDescription.components(separatedBy: "\n").compactMap { line in
            guard line.contains("StaticText"), let r = line.range(of: "label: '") else { return nil }
            return String(line[r.upperBound...].dropLast())
        }
    }
}

/// The check-in's end is the end (2026-11-14: a check-in left on the Today tab's stack opened a new conversation,
/// with no call bar, when the tab came back). On the scripted Live of Debug builds; `KAIKU_TEST_CLOUD` to pair.
final class CheckInEndTests: XCTestCase {
    private let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")

    override func setUp() { continueAfterFailure = true }

    private func launchCheckIn(_ state: String?, extra: [String] = []) -> XCUIApplication {
        let env = ProcessInfo.processInfo.environment
        let cloud = env["KAIKU_TEST_CLOUD"] ?? "http://127.0.0.1:8000"
        let app = XCUIApplication()
        app.launchArguments = ["-kaiku.lang", "en", "-AppleLanguages", "(en)", "-kaikuMute", "YES", "-kaikuSkipOnboarding", "YES",
                               "-kaikuPairLink", "\(cloud)/?home=\(env["KAIKU_TEST_HOME"] ?? "aino")", "-kaikuRoute", "weather",
                               "-kaiku.talk.voiceMuted", "NO"] + (state.map { ["-kaikuTalkDemo", $0] } ?? []) + extra
        app.launch()
        return app
    }

    private func shot(_ app: XCUIApplication, _ name: String) {
        guard let dir = ProcessInfo.processInfo.environment["KAIKU_SHOT_DIR"] else { return }
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: dir).appendingPathComponent(name + ".png"))
    }

    /// No call bar anywhere, and nothing that says a conversation is open.
    private func assertNoCall(_ app: XCUIApplication, _ why: String) {
        XCTAssertFalse(app.buttons["call.end"].exists, "no call bar: \(why)")
        XCTAssertFalse(app.buttons["call.mic"].exists, "no microphone button: \(why)")
        XCTAssertFalse(springboard.staticTexts.matching(NSPredicate(format: "label CONTAINS[c] %@", "Talking with Kaiku")).firstMatch.exists,
                       "no call in the Dynamic Island: \(why)")
    }

    func testACheckInLeftForAnotherTabIsGoneWhenTodayComesBack() {
        let app = launchCheckIn("closed")
        XCTAssertTrue(app.staticTexts["Good to see you."].firstMatch.waitForExistence(timeout: 25), "the check-in wrapped up")
        sleep(3)                                           // Kaiku's goodbye has been said
        shot(app, "end-screen")
        assertNoCall(app, "an end screen")

        app.tabBars.buttons["Play"].tap()
        sleep(2)
        app.tabBars.buttons["Today"].tap()
        XCTAssertTrue(app.staticTexts["Today's path"].firstMatch.waitForExistence(timeout: 6), "Today is Today again")
        XCTAssertFalse(app.staticTexts["Good to see you."].exists, "the ended check-in is not waiting on the tab's stack")
        XCTAssertFalse(app.staticTexts["Checking in"].exists)
        sleep(3)                                           // long enough for a hidden conversation to have opened
        assertNoCall(app, "back on Today")
        shot(app, "today-after-leaving")

        // The same after the app was away.
        XCUIDevice.shared.press(.home)
        sleep(2)
        app.activate()
        XCTAssertTrue(app.staticTexts["Today's path"].firstMatch.waitForExistence(timeout: 6))
        sleep(3)
        assertNoCall(app, "back from the background")
    }

    func testUpNextLeavesTheCheckInBehind() {
        let app = launchCheckIn("closed")
        XCTAssertTrue(app.staticTexts["Good to see you."].firstMatch.waitForExistence(timeout: 25))
        let next = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Up next")).firstMatch
        XCTAssertTrue(next.waitForExistence(timeout: 5), "the end screen leads on to the next stop")
        next.tap()
        sleep(3)
        XCTAssertFalse(app.staticTexts["Good to see you."].exists, "the next stop is showing")
        shot(app, "up-next")
        // Wherever the next stop lives, Today is Today when she comes back to it.
        app.tabBars.buttons["Play"].tap()
        sleep(1)
        app.tabBars.buttons["Today"].tap()
        sleep(2)
        XCTAssertFalse(app.staticTexts["Good to see you."].exists, "the morning's end screen is gone for good")
        XCTAssertFalse(app.staticTexts["Checking in"].exists)
        sleep(3)
        assertNoCall(app, "after Up next")
    }

    func testAMidChatTabSwitchEndsTheCheckInAndItsCall() {
        let app = launchCheckIn("live")
        XCTAssertTrue(app.buttons["call.end"].firstMatch.waitForExistence(timeout: 25), "Kaiku is on the line")
        app.tabBars.buttons["You"].tap()
        sleep(3)
        assertNoCall(app, "the check-in's screen is gone, so is its call")
        app.tabBars.buttons["Today"].tap()
        XCTAssertTrue(app.staticTexts["Today's path"].firstMatch.waitForExistence(timeout: 6))
        XCTAssertFalse(app.staticTexts["Checking in"].exists)
        sleep(3)
        assertNoCall(app, "and nothing started again behind Today")
    }

    func testEndOnTheLockScreenBringsTheCheckInToItsEndScreen() {
        let app = launchCheckIn("live")
        XCTAssertTrue(app.buttons["call.end"].firstMatch.waitForExistence(timeout: 25), "Kaiku is on the line")
        XCUIDevice.shared.perform(NSSelectorFromString("pressLockButton"))
        sleep(2)
        XCUIDevice.shared.press(.home)                     // wake to the Lock Screen
        sleep(2)
        let end = springboard.buttons["End"].firstMatch
        XCTAssertTrue(end.waitForExistence(timeout: 8), "the call is on the Lock Screen")
        end.tap()
        sleep(3)
        XCTAssertFalse(springboard.buttons["End"].firstMatch.exists)
        XCUIDevice.shared.press(.home)
        sleep(1)
        app.activate()
        XCTAssertTrue(app.staticTexts["Good to see you."].firstMatch.waitForExistence(timeout: 10),
                      "the same end screen as after \"That's enough for now\"")
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@ OR label == %@", "Up next", "Back to today")).firstMatch.exists,
                      "with the way on")
        XCTAssertTrue(app.buttons["Keep talking"].firstMatch.exists)
        assertNoCall(app, "ended from the Lock Screen")
        shot(app, "after-end-on-lock-screen")
    }

    /// Without a voice the dials are the whole check-in: all three and "That's it" are in view at once (6.3-inch
    /// screen, default text size). Needs a cloud without a model key (`KAIKU_TEST_CLOUD`), so no call opens.
    func testThatsItIsInViewWithoutScrollingWhenKaikuCannotTalk() {
        let app = launchCheckIn(nil)
        XCTAssertTrue(app.staticTexts["Or just turn the dials"].firstMatch.waitForExistence(timeout: 25))
        let done = app.buttons["checkin.dials.done"].firstMatch
        XCTAssertTrue(done.waitForExistence(timeout: 20))
        sleep(2)
        shot(app, "dials-only")
        XCTAssertFalse(app.buttons["call.end"].exists, "this run has no voice")
        XCTAssertTrue(done.isHittable, "\"That's it\" is on screen without scrolling")
        let tabBar = app.tabBars.firstMatch.frame
        for name in ["Mood", "Energy", "Last night's sleep"] {
            let dial = app.otherElements[name].firstMatch.exists ? app.otherElements[name].firstMatch : app.descendants(matching: .any)[name].firstMatch
            XCTAssertTrue(dial.exists, name)
            XCTAssertLessThanOrEqual(dial.frame.maxY, done.frame.minY + 1, "\(name) sits above the button")
            XCTAssertGreaterThanOrEqual(dial.frame.minY, 0)
        }
        XCTAssertLessThanOrEqual(done.frame.maxY, tabBar.minY + 1, "and the button is clear of the tab bar")
        done.tap()
        XCTAssertTrue(app.staticTexts["Thank you for telling me. An ordinary day counts too."].firstMatch.waitForExistence(timeout: 6))
        // On a real service too (this run asked it for one conversation and got none): leaving the end screen and
        // coming back, or returning from the background, asks for nothing more. The service's log has the count.
        app.tabBars.buttons["Play"].tap()
        sleep(2)
        app.tabBars.buttons["Today"].tap()
        XCTAssertTrue(app.staticTexts["Today's path"].firstMatch.waitForExistence(timeout: 6))
        XCUIDevice.shared.press(.home)
        sleep(2)
        app.activate()
        sleep(4)
        XCTAssertTrue(app.staticTexts["Today's path"].firstMatch.exists)
        XCTAssertFalse(app.staticTexts["Checking in"].exists)
    }

    /// A thumb that lands on a dial still scrolls the page; only a sideways drag turns the dial.
    func testADragUpThatStartsOnADialScrollsThePageAndASidewaysDragTurnsTheDial() {
        let app = launchCheckIn("live")
        XCTAssertTrue(app.buttons["call.end"].firstMatch.waitForExistence(timeout: 25))
        let mood = app.descendants(matching: .any)["Mood"].firstMatch
        XCTAssertTrue(mood.waitForExistence(timeout: 10))
        let done = app.buttons["checkin.dials.done"].firstMatch
        let value = mood.value as? String
        let before = mood.frame.minY
        // Start on the dial's track (the lower half of its card) and drag up.
        let from = mood.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.72))
        from.press(forDuration: 0.05, thenDragTo: from.withOffset(CGVector(dx: 2, dy: -260)))
        sleep(1)
        shot(app, "after-drag-on-dial")
        XCTAssertLessThan(mood.frame.minY, before - 60, "the page scrolled")
        XCTAssertEqual(mood.value as? String, value, "and the dial did not move")
        // Sideways on the same track: the dial turns, the page stays.
        let at = mood.frame.minY
        let knob = mood.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.72))
        knob.press(forDuration: 0.05, thenDragTo: knob.withOffset(CGVector(dx: 120, dy: 3)))
        sleep(1)
        XCTAssertNotEqual(mood.value as? String, value, "a sideways drag turns the dial")
        XCTAssertEqual(mood.frame.minY, at, accuracy: 12, "without scrolling the page")
        _ = done
    }

    /// Opt-in, PAID (one real Gemini Live check-in of about 100 s, typed, never the microphone): the take in which
    /// Kaiku went silent, replayed. Four plain statements (no question, no name) 20 s apart through launch
    /// arguments, the phone locked after the third, the app reopened at the end. Every statement must get a
    /// caption from Kaiku. `TEST_RUNNER_KAIKU_CHECKIN_TAKE_CLOUD=http://127.0.0.1:<port>` (a private cloud with a
    /// model key); `TEST_RUNNER_KAIKU_CALL_TRACE=<file>` writes the connection and turn events (no words).
    func testARealCheckInAnswersPlainStatements() throws {
        let env = ProcessInfo.processInfo.environment
        guard let cloud = env["KAIKU_CHECKIN_TAKE_CLOUD"], !cloud.isEmpty else { throw XCTSkip("set KAIKU_CHECKIN_TAKE_CLOUD (paid)") }
        let home = "take-\(Int(Date().timeIntervalSince1970))"
        let lines = ["It has been a hard day. My mother would have turned ninety today, and I miss her more than I expected.",
                     "She always baked cardamom buns on her birthday. I could not face making them today.",
                     "I do not really know what to do with the evening.",
                     "Thank you for staying with me."]
        let app = XCUIApplication()
        app.launchArguments = ["-kaiku.lang", "en", "-AppleLanguages", "(en)", "-kaikuMute", "YES", "-kaikuSkipOnboarding", "YES",
                               "-kaikuPairLink", "\(cloud)/?home=\(home)", "-kaikuRoute", "weather", "-kaiku.talk.voiceMuted", "NO",
                               "-kaikuTalkSay", lines[0], "-kaikuTalkSayLater", lines.dropFirst().joined(separator: "|"),
                               "-kaikuTalkSayDelay", "20"]
        if let trace = env["KAIKU_CALL_TRACE"] { app.launchArguments += ["-kaikuCallTrace", trace] }
        app.launch()
        XCTAssertTrue(app.buttons["call.end"].firstMatch.waitForExistence(timeout: 40), "Kaiku is on the line")
        XCTAssertTrue(app.staticTexts[lines[0]].firstMatch.waitForExistence(timeout: 30), "the first statement went out")
        let t0 = Date()
        func texts(_ root: XCUIApplication) -> [String] {
            root.debugDescription.components(separatedBy: "\n").compactMap { line in
                guard line.contains("StaticText"), let r = line.range(of: "label: '") else { return nil }
                return String(line[r.upperBound...].dropLast())
            }
        }
        var states: [String] = []
        var seen: [String] = []                              // every text in the order it first showed
        let chrome: Set<String> = ["Checking in", "Or just turn the dials", "Mood", "Energy", "Last night's sleep", "I'm not OK",
                                   "Talking with Kaiku", "Good to see you."]
        func look(_ name: String, _ root: XCUIApplication) {
            let t = texts(root)
            let state = t.first { ["Thinking", "Microphone is off", "Kaiku is speaking", "Waking Kaiku up"].contains(where: $0.contains) } ?? "-"
            states.append(state)
            print(String(format: "TAKE %5.1fs %@ state=%@", Date().timeIntervalSince(t0), name, state))
            for text in t where text.count > 20 && !chrome.contains(text) && !seen.contains(text) && !text.contains("Call time") {
                seen.append(text)
                print(String(format: "TAKE-SAID %5.1fs %@ %@", Date().timeIntervalSince(t0), lines.contains(text) ? "PERSON:" : "KAIKU: ", text))
            }
            shot(app, name)
        }
        look("take-start", app)
        // In the app through the second and third statement (as in the failed take), a look every three seconds.
        for n in 0..<19 { sleep(3); look(String(format: "take-%02d", n), app) }
        XCUIDevice.shared.perform(NSSelectorFromString("pressLockButton"))
        sleep(2)
        XCUIDevice.shared.press(.home)
        for n in 0..<6 { sleep(3); look("take-lock-\(n)", springboard) }
        XCUIDevice.shared.press(.home)
        sleep(1)
        app.activate()
        sleep(3)
        look("take-back", app)
        // Every statement is followed by something Kaiku said before the next one (or the end).
        for (i, line) in lines.enumerated() {
            guard let at = seen.firstIndex(of: line) else { XCTFail("the statement never showed: \(line)"); continue }
            let next = i + 1 < lines.count ? (seen.firstIndex(of: lines[i + 1]) ?? seen.count) : seen.count
            XCTAssertTrue(seen[(at + 1)..<max(at + 1, next)].contains { !lines.contains($0) }, "Kaiku answered: \(line)")
        }
        XCTAssertFalse(states.contains { $0.contains("Waking") }, "the line never dropped: \(states)")
        // The model may have wrapped the chat up itself by now; otherwise the person does.
        if app.buttons["call.end"].firstMatch.exists { app.buttons["call.end"].firstMatch.tap() }
        XCTAssertTrue(app.staticTexts["Good to see you."].firstMatch.waitForExistence(timeout: 10))
        shot(app, "take-end")
    }
}

import XCTest

/// The iPhone demo recordings (`apps/apple/scripts/record_app_demo.sh ios`): one method per clip, driven like a
/// person would at a person's pace (read, then tap). Needs a local cloud seeded with the one person
/// (`KAIKU_TEST_CLOUD`, home `KAIKU_TEST_HOME`, default `aino`). A control that is missing is logged as
/// `DEMO-MISSING` with what was on screen (and a screenshot in `KAIKU_SHOT_DIR`), and the flow goes on, so a
/// recording doubles as a smoke test. `DEMO-STEP <name> <epoch>` lines are the chapter marks the recorder turns
/// into time codes; `DEMO-SAID` / `DEMO-LOCK` are the words that were on screen (the record of a real take).
///
/// Conversations (the check-in chat of `testB_TodayPath`, `testD_Talk`, `testH_CheckInHardDay`) are typed, never
/// spoken: the simulator's microphone is the Mac's, so the recorder revokes the app's microphone permission and
/// these flows never ask for it. What the person types is written here (or given in `KAIKU_DEMO_*_SAY`, lines
/// separated by `|`) and goes out through the Debug launch arguments `-kaikuTalkSay` / `-kaikuTalkSayLater` /
/// `-kaikuTalkSayDelay`: the real Live socket, also while the phone is locked. What Kaiku answers is never
/// written anywhere: it is the real model's reply, so those takes need a service with a model key (paid: one
/// Live session each). On a service without a live voice the same flows fall back to what a person would do
/// there (the dials; the one line of a Talk that cannot start). `KAIKU_DEMO_ARGS="-kaikuTalkDemo live"` runs a
/// flow on the scripted Live for free, to check the taps and the Lock Screen: its lines are hand-written layout
/// text, so such a take must never be shown as a clip. `KAIKU_DEMO_SOUND=1` lets Kaiku's voice play on the Mac
/// (default: `-kaikuMute YES`; the recording has no sound either way).
final class DemoTourTests: XCTestCase {
    let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
    var env: [String: String] { ProcessInfo.processInfo.environment }
    var cloud: String { env["KAIKU_TEST_CLOUD"] ?? "http://127.0.0.1:8000" }
    var home: String { env["KAIKU_TEST_HOME"] ?? "aino" }
    /// The Bonjour name of the recording cloud (the recorder advertises it), shown on the "nearby services" step.
    var serviceName: String { env["KAIKU_TEST_SERVICE_NAME"] ?? "Kaiku home service" }
    var app: XCUIApplication!
    var missing: [String] = []

    override func setUp() {
        continueAfterFailure = true
        addUIInterruptionMonitor(withDescription: "system alerts") { alert in
            for b in ["Allow", "OK", "Allow While Using App"] where alert.buttons[b].exists { alert.buttons[b].tap(); return true }
            return false
        }
    }

    override func tearDown() {
        print("DEMO-END \(Date().timeIntervalSince1970)")
        print("DEMO-MISSING-SUMMARY \(missing)")
    }

    // MARK: helpers

    func launch(_ extra: [String] = [], paired: Bool = true) {
        app = XCUIApplication()
        var args = ["-kaiku.lang", "en", "-AppleLanguages", "(en)"]
        if paired { args += ["-kaikuSkipOnboarding", "YES", "-kaikuPairLink", "\(cloud)/?home=\(home)"] }
        app.launchArguments = args + extra
        app.launch()
        pause(2.5)
    }

    // MARK: a conversation, typed (see the note at the top)

    /// What she types. Only her side: Kaiku's side is whatever the real model answers. No apostrophes or
    /// quotes in a line: on its way to the app as a launch argument a ' is read as a quote (seen 2026-11-14:
    /// "That's all for now." arrived, and was shown, as "Thats\ all\ for\ now."). The same goes for
    /// `KAIKU_DEMO_*_SAY`.
    static let ordinaryDay = ["Quite an ordinary one. I aired the bedding and made a pot of soup.",
                              "Nothing much planned. Maija rings at seven, as usual.",
                              "That is all for now. See you later, Kaiku."]
    static let hardDay = ["It has been a hard day. My mother would have turned ninety today, and I miss her more than I expected.",
                          "She always baked cardamom buns on her birthday. I could not face making them today. Is that silly, Kaiku?",
                          "I do not really know what to do with the evening. What do you think?",
                          "Thank you for staying with me, Kaiku."]
    static let talkLines = ["Hi Kaiku. I walked the lake loop with Leena this morning.",
                            "It was cold but bright. We saw two swans by the old sauna.",
                            "I am putting the phone in my pocket now. Stay with me on the way to the market hall?"]

    /// Extra launch arguments for a free check of a flow, e.g. `KAIKU_DEMO_ARGS="-kaikuTalkDemo live"`.
    var extraArgs: [String] { (env["KAIKU_DEMO_ARGS"] ?? "").split(separator: " ").map(String.init) }
    /// The scripted Live: no network, no model. Its words are layout text, never Kaiku's: not for a shown clip.
    var scripted: Bool { extraArgs.contains("-kaikuTalkDemo") }
    /// Kaiku's voice stays off the Mac's speakers unless asked for (the recording has no sound either way).
    var quiet: [String] { (env["KAIKU_DEMO_SOUND"] == "1" ? [] : ["-kaikuMute", "YES"]) + extraArgs }

    func lines(_ name: String, _ standard: [String]) -> [String] {
        guard let raw = env[name], !raw.isEmpty else { return standard }
        return raw.split(separator: "|").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
    }

    func seconds(_ name: String, _ standard: Double) -> Double { Double(env[name] ?? "") ?? standard }

    /// The launch arguments that type `lines`: the first once Kaiku has said hello, each next one `delay` seconds
    /// after the one before, wherever the app is by then (Debug builds; nothing is typed on the scripted Live).
    func typed(_ lines: [String], every delay: Double) -> [String] {
        guard let first = lines.first, !scripted else { return [] }
        var args = ["-kaikuTalkSay", first, "-kaikuTalkSayDelay", "\(Int(delay))"]
        if lines.count > 1 { args += ["-kaikuTalkSayLater", lines.dropFirst().joined(separator: "|")] }
        return args
    }

    /// The texts on screen from ONE snapshot (element-by-element queries race with a screen that is changing).
    func texts(_ root: XCUIApplication) -> [String] {
        root.debugDescription.components(separatedBy: "\n").compactMap { line in
            guard line.contains("StaticText"), let r = line.range(of: "label: '") else { return nil }
            return String(line[r.upperBound...].dropLast())
        }
    }

    /// The words of the conversation as they came, for `DEMO-SAID` (a caption grows while Kaiku speaks: the
    /// longer text takes the place of its beginning).
    var heard: [String] = []
    private var lastListen = Date.distantPast
    func listen(force: Bool = false) {
        guard force || Date().timeIntervalSince(lastListen) > 2.5 else { return }
        lastListen = Date()
        for t in texts(app) where t.count > 16 && !t.hasPrefix("Or just turn") {
            if heard.contains(where: { $0.hasPrefix(t) }) { continue }
            if let i = heard.firstIndex(where: { t.hasPrefix($0) }) { heard[i] = t } else { heard.append(t) }
        }
    }

    func logSaid() {
        listen(force: true)
        print("DEMO-SAID \(heard.joined(separator: " | "))")
    }

    /// Waits for `done`, at most `limit` seconds. Meanwhile it keeps the words that pass and marks the moment an
    /// activity card appears as a chapter.
    private var cardSeen = false
    @discardableResult
    func wait(_ limit: Double, until done: () -> Bool = { false }) -> Bool {
        let end = Date().addingTimeInterval(limit)
        while Date() < end {
            if done() { return true }
            if !cardSeen, app.descendants(matching: .any).matching(identifier: "activity.card").firstMatch.exists {
                cardSeen = true
                step("card")
            }
            listen()
            Thread.sleep(forTimeInterval: 0.4)
        }
        return done()
    }

    /// Follows her typed lines as they appear (they go out by themselves): a chapter per line. Stops early when
    /// the conversation has closed. Returns how many appeared and when the last one did.
    func follow(_ lines: [String], every delay: Double, closed: XCUIElement? = nil, first: Int = 1) -> (seen: Int, at: Date) {
        var seen = 0, at = Date()
        for (i, line) in lines.enumerated() {
            let bubble = app.staticTexts[line].firstMatch
            let there = wait(first + i == 1 ? 40 : delay + 15) { bubble.exists || closed?.exists == true }
            guard there, bubble.exists else {
                if closed?.exists != true { miss("typed line \(first + i)") }
                break
            }
            seen += 1
            at = Date()
            step("line-\(first + i)")
        }
        return (seen, at)
    }

    /// Locks the phone and wakes it: the call goes on as a bar on the Lock Screen. Watches the bar for `seconds`
    /// (a line typed meanwhile and Kaiku's answer arrive there as its caption) and prints what it says.
    func lockScreen(for seconds: Double) {
        XCUIDevice.shared.perform(NSSelectorFromString("pressLockButton"))
        pause(2)
        XCUIDevice.shared.press(.home)                      // wake to the Lock Screen
        pause(2)
        for label in ["Always Allow", "Allow"] where springboard.buttons[label].exists {
            // A simulator asks "Allow Live Activities?" once per install, on top of the bar.
            print("DEMO-NOTE the Live Activities prompt covered the bar: answered now, record this clip again")
            springboard.buttons[label].tap()
            pause(1.5)
            break
        }
        step("lock-screen")
        var last: [String] = []
        let end = Date().addingTimeInterval(seconds)
        while Date() < end {
            var now = texts(springboard)
            if !now.contains(where: { $0.contains("Talking with Kaiku") }) {
                XCUIDevice.shared.press(.home)              // the simulator's Lock Screen went dark: wake it once
                pause(1.5)
                now = texts(springboard)
            }
            if now != last {
                print("DEMO-LOCK \(now.joined(separator: " | "))")
                last = now
            }
            Thread.sleep(forTimeInterval: 1.0)
        }
        if !last.contains(where: { $0.contains("Talking with Kaiku") }) { miss("call bar on the Lock Screen") }
    }

    /// "End" on the Lock Screen's bar ends the call without opening the app; then back into the app.
    func endOnLockScreen() {
        let end = springboard.buttons["End"].firstMatch
        if end.waitForExistence(timeout: 5) {
            step("end-on-lock-screen")
            pause(1)
            end.tap()
            pause(3.5)
            if springboard.buttons["End"].firstMatch.exists { miss("the bar is still there after End") }
        } else { miss("End on the Lock Screen") }
        XCUIDevice.shared.press(.home)
        pause(1)
        app.activate()
        pause(2)
        step("back-in-app")
    }

    /// Today's one invitation from Kaiku (for the seeded person: something she said that was left open). It is
    /// read here, not answered: an answer is final for the day.
    func invitation() {
        let card = app.descendants(matching: .any).matching(identifier: "today.invitation").firstMatch
        guard card.waitForExistence(timeout: 6) || app.buttons["Not now"].exists else { miss("today.invitation"); return }
        step("invitation")
        pause(4.5)
    }

    /// The quiet way through the check-in, and the only one on a service without a live voice: Kaiku's hello is
    /// on screen as text, she turns the three dials, "That's it", and Kaiku answers what was dialled in one line.
    func dials() {
        step("check-in-dials")
        pause(3.5)
        turnDial("Mood", to: 0.62)
        turnDial("Energy", to: 0.45)
        turnDial("Last night's sleep", to: 0.7)
        // "That's it" sits under the third dial, below the fold on a 6.3-inch phone. Scroll from the words above
        // the dials: on 2026-11-14 a drag that started on a dial card did not move the page.
        let done = app.buttons["That's it"].firstMatch
        for _ in 0..<3 where done.exists && !done.isHittable {
            app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.44))
                .press(forDuration: 0.05, thenDragTo: app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.16)),
                       withVelocity: .slow, thenHoldForDuration: 0.1)
            pause(0.8)
        }
        tap("That's it", after: 4.5, scrolls: false)
    }

    /// Today's first stop. With Kaiku on the line it is a small chat: her typed lines, Kaiku's real answers, and
    /// then either Kaiku wraps it up (an ordinary day: "Good to see you") or it simply goes on (a hard or a very
    /// good day) until she ends it. `lock`: the phone is locked before her last line, which is then answered on
    /// the Lock Screen, and the call is ended from there. Returns true when the take ended on the end screen.
    @discardableResult
    func checkIn(_ said: [String], every delay: Double, lock: Bool = false) -> Bool {
        let end = app.buttons["call.end"].firstMatch
        let closed = app.staticTexts["Good to see you."].firstMatch
        let voiceless = element(containing: "can't talk right now")
        wait(25) { end.exists || closed.exists || voiceless.exists }
        guard end.exists || closed.exists else { dials(); return true }
        step("check-in-chat")
        if scripted { wait(7) } else {
            let inApp = lock ? Array(said.dropLast()) : said
            let r = follow(inApp, every: delay, closed: closed)
            if lock && r.seen == inApp.count {
                // lock a few seconds before her last line is due: it and Kaiku's answer arrive on the Lock Screen
                wait(max(4, delay - 7 - Date().timeIntervalSince(r.at))) { closed.exists }
            } else {
                // Kaiku's answer to her last line; on an ordinary day it also wraps the chat up
                wait(delay + 14) { closed.exists }
            }
        }
        if lock, !closed.exists, end.exists {
            lockScreen(for: scripted ? 8 : 24)
            endOnLockScreen()
            logSaid()
            shot("check-in-after-lock")
            return false
        }
        if !closed.exists, end.exists {
            // nothing counts turns or sets a timer: the chat goes on until she ends it
            wait(4)
            step("enough")
            end.tap()
        }
        logSaid()
        guard see("Good to see you", timeout: 12) else { return false }
        step("check-in-end")
        pause(4.5)
        return true
    }

    func pause(_ s: Double = 1.5) { Thread.sleep(forTimeInterval: s) }

    func shot(_ name: String) {
        guard let dir = env["KAIKU_SHOT_DIR"] else { return }
        let safe = name.replacingOccurrences(of: "[^A-Za-z0-9-]+", with: "-", options: .regularExpression)
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: dir).appendingPathComponent("\(safe).png"))
    }

    /// A chapter mark (and a screenshot of where the flow is).
    func step(_ name: String) {
        print("DEMO-STEP \(name) \(Date().timeIntervalSince1970)")
        shot("\(self.name.split(separator: " ").last.map(String.init)?.dropLast() ?? "x")-\(name)")
    }

    func miss(_ what: String) {
        print("DEMO-MISSING \(what)")
        missing.append(what)
        shot("missing-\(what)")
        let labels = (app.buttons.allElementsBoundByIndex.prefix(40).map { "[\($0.label)]" }
            + app.staticTexts.allElementsBoundByIndex.prefix(40).map { $0.label }).joined(separator: " | ")
        print("DEMO-ONSCREEN \(labels)")
    }

    func element(containing text: String) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS[c] %@", text)).firstMatch
    }

    func button(containing text: String) -> XCUIElement {
        app.buttons.matching(NSPredicate(format: "label CONTAINS[c] %@", text)).firstMatch
    }

    /// Scrolls like a thumb would (a short, slow drag) until the element can be tapped.
    func reveal(_ e: XCUIElement, tries: Int = 6) {
        for _ in 0..<tries where !(e.exists && e.isHittable) { scroll(); pause(0.5) }
    }

    func scroll(_ amount: CGFloat = 0.3, up: Bool = true) {
        let a = app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: up ? 0.7 : 0.4))
        let b = app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: up ? 0.7 - amount : 0.4 + amount))
        a.press(forDuration: 0.05, thenDragTo: b, withVelocity: .slow, thenHoldForDuration: 0.1)
    }

    /// Taps the first button or text with this exact label; logs it as missing instead of failing the flow.
    @discardableResult
    func tap(_ label: String, timeout: TimeInterval = 8, after: Double = 1.5, scrolls: Bool = true) -> Bool {
        let b = app.buttons[label].firstMatch
        let t = app.staticTexts[label].firstMatch
        let deadline = Date().addingTimeInterval(timeout)
        var scrolled = 0
        while Date() < deadline {
            if b.exists && b.isHittable { b.tap(); pause(after); return true }
            if t.exists && t.isHittable { t.tap(); pause(after); return true }
            if scrolls, scrolled < 5, b.exists || t.exists { scroll(); scrolled += 1 }
            Thread.sleep(forTimeInterval: 0.25)
        }
        miss(label)
        return false
    }

    @discardableResult
    func tap(containing text: String, timeout: TimeInterval = 8, after: Double = 1.5) -> Bool {
        let b = button(containing: text)
        guard b.waitForExistence(timeout: timeout) else { miss("~\(text)"); return false }
        reveal(b)
        guard b.isHittable else { miss("~\(text) (not hittable)"); return false }
        b.tap(); pause(after)
        return true
    }

    @discardableResult
    func see(_ text: String, timeout: TimeInterval = 8) -> Bool {
        let ok = element(containing: text).waitForExistence(timeout: timeout)
        if !ok { miss("see:\(text)") }
        return ok
    }

    /// Back: the button when it can be tapped, else the edge swipe (after scrolling, the header may be covered).
    func back() {
        let b = app.buttons["Back"].firstMatch
        if b.waitForExistence(timeout: 2), b.isHittable { b.tap(); pause(1.2); return }
        let edge = app.coordinate(withNormalizedOffset: CGVector(dx: 0.0, dy: 0.5))
        edge.press(forDuration: 0.05, thenDragTo: app.coordinate(withNormalizedOffset: CGVector(dx: 0.8, dy: 0.5)))
        pause(1.2)
    }

    func tab(_ name: String, after: Double = 2.5) {
        let b = app.tabBars.buttons[name]
        if b.waitForExistence(timeout: 5) { b.tap(); pause(after) } else { tap(name, after: after) }
    }

    func allowSystemAlert(timeout: TimeInterval = 4) {
        for label in ["Allow", "Allow While Using App", "OK"] {
            let b = springboard.buttons[label]
            if b.waitForExistence(timeout: label == "Allow" ? timeout : 0.3) { pause(1); b.tap(); pause(1); return }
        }
    }

    /// Drags a weather dial to about `to` (0…1 across its width), the way a thumb would.
    func turnDial(_ name: String, to: CGFloat) {
        let d = app.descendants(matching: .any)[name].firstMatch
        guard d.waitForExistence(timeout: 4) else { miss("dial \(name)"); return }
        reveal(d)
        let from = d.coordinate(withNormalizedOffset: CGVector(dx: 0.2, dy: 0.72))
        from.press(forDuration: 0.2, thenDragTo: d.coordinate(withNormalizedOffset: CGVector(dx: to, dy: 0.72)),
                   withVelocity: .slow, thenHoldForDuration: 0.2)
        pause(1.2)
    }

    /// A game's end screen: read it, then carry on along today's path ("Up next: …") or back to Today.
    func finishGame(wait: TimeInterval) {
        let enough = app.buttons["That's enough for today"]
        if !enough.waitForExistence(timeout: wait) { miss("game end"); back(); return }
        shot("end-\(Date().timeIntervalSince1970)")
        pause(4)                                            // the completion moment and the end picture
        let next = button(containing: "Up next")
        if next.exists && next.isHittable { next.tap(); pause(2.5) } else { enough.tap(); pause(2) }
    }

    /// Opens a stop of today's path from Today unless the app is already on it.
    func openPathStop(_ title: String, alreadyOn marker: String) {
        if app.buttons[marker].waitForExistence(timeout: 3) { return }
        if app.buttons["Back"].exists { back() }
        tab("Today", after: 2)
        tap(containing: title, after: 2.5)
    }

    // MARK: a · first run: welcome → what Kaiku is and is not → nearby service → choices → permissions → hello → Today

    func testA_FirstRun() {
        launch(["-kaiku.onboarded", "NO", "-kaikuOnboardingStep", "0"], paired: false)
        step("welcome")
        _ = see("Hi, I'm Kaiku")
        pause(3.5)
        tap("Say hello", after: 2)

        step("what-kaiku-is")
        _ = see("Not emergency care")
        pause(3)
        scroll(0.25); pause(2.5)
        tap("I understand", after: 2.5)

        step("nearby-service")
        _ = see("Nearby Kaiku services")
        let name = app.staticTexts[serviceName].firstMatch
        // A build with a configured service (KAIKU_SERVICE_URL) connects by itself: then Kaiku's hello has its voice.
        let connected = element(containing: "Connected to your Kaiku service")
        var hasVoice = false
        if connected.waitForExistence(timeout: 5) {
            hasVoice = true
            pause(3)
            tap("Continue", after: 2.5)
        } else if name.waitForExistence(timeout: 3) {
            hasVoice = true
            pause(2)
            // the Connect button of that service's card (another service on the network may be listed too)
            let y = name.frame.maxY
            let connect = app.buttons.matching(identifier: "Connect").allElementsBoundByIndex
                .filter { $0.frame.minY >= y }.min { $0.frame.minY < $1.frame.minY }
            if let connect {
                if !connect.isHittable { scroll(0.2); pause(0.6) }
                connect.tap(); pause(3.5)
            } else { miss("Connect for \(serviceName)") }
        } else {
            // nothing nearby (Bonjour does not reach the simulator): go on without a service, as a person would
            print("DEMO-NOTE no nearby service listed: continuing without connecting")
            pause(2)
            if !tap("Continue without connecting", timeout: 4, after: 2.5) { tap("Skip for now", timeout: 3, after: 2.5) }
        }

        step("choices")
        _ = see("Your choices")
        if springboard.buttons["Allow"].waitForExistence(timeout: 2.5) {   // must not happen: asked only when a walk starts
            miss("system prompt on Your choices"); allowSystemAlert(timeout: 1)
        }
        pause(3)
        let keep = app.switches.matching(NSPredicate(format: "label CONTAINS[c] %@", "Keep our conversations")).firstMatch
        if keep.exists {
            reveal(keep)
            keep.coordinate(withNormalizedOffset: CGVector(dx: 0.9, dy: 0.5)).tap()   // on: her own choice
            pause(2)
        } else { scroll(0.3); pause(2) }
        tap("Continue", after: 2.5)

        step("permissions")
        _ = see("A few permissions")
        pause(2.5)
        if tap("Allow: Microphone", timeout: 4, after: 1) { allowSystemAlert(); pause(1) }
        if tap("Allow: Gentle nudges", timeout: 4, after: 1) { allowSystemAlert(); pause(1.5) }
        tap("Continue", after: 2.5)

        step("hello-and-first-task")
        _ = see("good to meet you")
        pause(hasVoice ? 9.5 : 4)                           // Kaiku says hello aloud (8.7 s) when there is a service
        if see("One small thing to try", timeout: 3) {
            let dial = app.descendants(matching: .any).matching(NSPredicate(format: "label IN %@", ["Mood", "Energy"])).firstMatch
            if dial.exists {
                scroll(0.22); pause(1.5)                    // the practice dial sits below the fold
                dial.coordinate(withNormalizedOffset: CGVector(dx: 0.2, dy: 0.72))
                    .press(forDuration: 0.2, thenDragTo: dial.coordinate(withNormalizedOffset: CGVector(dx: 0.75, dy: 0.72)),
                           withVelocity: .slow, thenHoldForDuration: 0.2)
                pause(1.5)
            }
        }
        if app.buttons["That's it"].exists { tap("That's it", timeout: 2, after: 1) }
        step("you-did-it")
        _ = see("You did it")
        pause(hasVoice ? 9.5 : 4)                           // "That's all a check-in is…" aloud (8.4 s)
        tap("Go to Today", after: 3)
        step("today")
        _ = app.tabBars.buttons["Today"].waitForExistence(timeout: 8)
        pause(5)
    }

    // MARK: b · today's path: Kaiku's invitation → the check-in chat → Kaiku's suggestion → Lantern → today's rotating game → "All done for today"

    func testB_TodayPath() {
        let said = lines("KAIKU_DEMO_CHECKIN_SAY", Self.ordinaryDay)
        let every = seconds("KAIKU_DEMO_CHECKIN_DELAY", 15)
        launch(quiet + typed(said, every: every))
        step("today")
        _ = see("Today's path", timeout: 12)
        pause(2.5)
        invitation()

        // The first stop is a small chat with Kaiku (still titled "Weather check" on the path).
        step("check-in")
        if !tap(containing: "Weather check", timeout: 5, after: 2) { tap("Start here", after: 2) }
        checkIn(said, every: every)

        // Back to Today, where the first stop is now ticked, then Kaiku's suggestion from the path (the nudge
        // decides: a walk, a breath or "Tell Kaiku"). Not "Up next" on the check-in's end screen: that leaves the
        // check-in on the Today tab's stack, and coming back to that tab at the end of the path starts a new
        // conversation behind the end screen (seen 2026-11-14; on a keyed service it reserves a Live session).
        if app.buttons["Back"].exists { back() }
        tab("Today", after: 3)
        step("suggestion")
        if button(containing: "Kaiku picked this").waitForExistence(timeout: 5) {
            tap(containing: "Kaiku picked this", after: 2.5)
            suggestion()
        } else { miss("suggestion stop") }

        step("lantern")
        openPathStop("Lantern", alreadyOn: "Start")
        pause(3)                                            // the intro and its looping demo
        tap("Start", after: 0.5)
        playLantern()
        finishGame(wait: 20)

        step("rotating-game")
        if !app.buttons["Start"].waitForExistence(timeout: 3) {
            if app.buttons["Back"].exists { back() }
            tab("Today", after: 2.5)
            tap(containing: "And one more", after: 2.5)
        }
        pause(3)
        let title = ["Seed shelf", "Watering", "Pebble path"].first { app.staticTexts[$0].exists } ?? "?"
        print("DEMO-ROTATING \(title)")
        tap("Start", after: 0.8)
        switch title {
        case "Seed shelf": playSeeds()
        case "Pebble path": playPebbles()
        default: pause(20)                                  // Watering has no scripted player: show it, then leave
        }
        finishGame(wait: 30)

        step("all-done")
        if app.buttons["Back"].exists { back() }
        tab("Today", after: 2)
        if !element(containing: "All done for today").waitForExistence(timeout: 3), app.buttons["Back"].exists { back() }
        _ = see("All done for today", timeout: 10)
        pause(5)
    }

    /// The suggested stop. A walk: start it, find three green things over a little more than a minute (shorter
    /// walks are not saved), end it. A breath: one full cycle. Tell Kaiku: shown, then left (it needs a voice).
    func suggestion() {
        if app.buttons["Walk with Kaiku"].exists || app.buttons["Start the walk"].exists {
            pause(2.5)
            if !tap("Walk with Kaiku", timeout: 2, after: 1.5) { tap("Start the walk", after: 1.5) }
            allowSystemAlert(timeout: 3)
            step("walking")
            let started = Date()
            pause(12)
            for i in 1...3 {
                if app.buttons["Found one"].exists { tap("Found one", timeout: 2, after: 1, scrolls: false) }
                if i < 3 { pause(14) }
            }
            while Date().timeIntervalSince(started) < 66 { pause(1) }
            tap("End walk", after: 4)
            step("walk-summary")
            pause(3)
            tap("Done", timeout: 5, after: 2.5)
        } else if app.staticTexts["Breathe with Kaiku"].exists || app.buttons["Start"].exists {
            pause(3)
            tap("Start", after: 1)
            step("breathing")
            if app.buttons["That's enough for today"].waitForExistence(timeout: 100) { finishGame(wait: 2) }
            else { tap("Stop", timeout: 3, after: 2.5); if app.buttons["That's enough for today"].exists { finishGame(wait: 2) } }
        } else {
            miss("suggestion screen")
            if app.buttons["Back"].exists { back() }
        }
    }

    /// Lantern: touch when the flame appears. The test sees the flame through the `lantern-lit` identifier and
    /// answers after a human-sized delay; one early touch during practice shows what "too early" looks like.
    func playLantern() {
        let lit = app.descendants(matching: .any).matching(identifier: "lantern-lit").firstMatch
        let enough = app.buttons["That's enough for today"]
        let spot = app.coordinate(withNormalizedOffset: CGVector(dx: 0.62, dy: 0.62))
        let deadline = Date().addingTimeInterval(170)
        var answered = 0, loops = 0
        pause(0.8)
        spot.tap()                                          // too early, once, in practice
        while Date() < deadline {
            loops += 1
            if lit.exists {
                Thread.sleep(forTimeInterval: Double.random(in: 0.05...0.25))
                spot.tap()
                answered += 1
                Thread.sleep(forTimeInterval: 0.9)
            } else if loops % 12 == 0, enough.exists { break }
            else { Thread.sleep(forTimeInterval: 0.03) }
        }
        print("DEMO-LANTERN answered=\(answered)")
    }

    /// Seed shelf: look up the packet's mark on the shelf, tap its pot. The right pot comes from the packet's
    /// `seed-pot-<n>` identifier; the pace is a person's (about one packet every second and a half).
    func playSeeds() {
        let packet = app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH %@", "seed-pot-")).firstMatch
        let enough = app.buttons["That's enough for today"]
        let deadline = Date().addingTimeInterval(140)
        var picked = 0
        pause(1.5)
        while Date() < deadline {
            if picked % 6 == 5, enough.exists { break }
            guard packet.exists, let id = (try? packet.snapshot())?.identifier,   // it may vanish as the round ends
                  let n = Int(id.dropFirst("seed-pot-".count)) else {
                if enough.exists { break }
                Thread.sleep(forTimeInterval: 0.3); continue
            }
            let pot = app.buttons["Pot \(n)"]
            guard pot.exists else { if enough.exists { break }; Thread.sleep(forTimeInterval: 0.3); continue }
            pot.tap()
            picked += 1
            Thread.sleep(forTimeInterval: Double.random(in: 0.5...1.1))
        }
        print("DEMO-SEEDS picked=\(picked)")
    }

    func playPebbles() {
        let enough = app.buttons["That's enough for today"]
        let deadline = Date().addingTimeInterval(60)
        while !enough.exists && Date() < deadline {
            let p = app.buttons["Pebble 1"]
            if p.exists && p.isEnabled && app.staticTexts["Your turn"].exists { p.tap(); pause(0.6) }
            Thread.sleep(forTimeInterval: 0.5)
        }
    }

    // MARK: c · Your days → "Today, so far": what was noticed, from where, what is shared

    func testC_TodaySoFar() {
        launch()
        step("today")
        pause(3)
        tab("History", after: 3.5)   // Your days sits under History since the History tab arrived
        let days = app.staticTexts["Your garden, today so far and little moments"].firstMatch
        if days.waitForExistence(timeout: 6) { days.tap(); pause(2.5) } else { NSLog("DEMO-MISSING your days row under History") }
        step("your-days")
        let title = app.staticTexts["Today, so far"].firstMatch
        _ = title.waitForExistence(timeout: 8)
        reveal(title)
        step("today-so-far")
        pause(3)
        for _ in 0..<3 { scroll(0.28); pause(2.8) }
        let more = button(containing: "See every detail")
        if more.exists {
            reveal(more)
            more.tap(); pause(3.5)
            step("what-kaiku-saw")
            for _ in 0..<2 { scroll(0.3); pause(2.5) }
            back()
        }
        for _ in 0..<3 { scroll(0.3); pause(2) }                // the garden and the week's little moments
        pause(2)
    }

    // MARK: d · Talk is a call: Kaiku in the centre, captions of both sides, the call bar; then the Lock Screen

    /// With a live voice on the service: the call opens with the Talk tab, she types two lines and Kaiku answers
    /// each (Kaiku is muted for the second: its words keep coming as captions), she locks the phone, her last
    /// line and Kaiku's answer arrive on the Lock Screen's bar, and "End" there ends the call. The microphone
    /// button is never pressed (with the permission off it opens Settings). Without a live voice: the one line
    /// and the one action Talk shows instead. `KAIKU_DEMO_TALK_SAY` / `_DELAY`, `KAIKU_DEMO_LOCK=0` (stay in the app).
    func testD_Talk() {
        let said = lines("KAIKU_DEMO_TALK_SAY", Self.talkLines)
        let every = seconds("KAIKU_DEMO_TALK_DELAY", 17)
        let lock = env["KAIKU_DEMO_LOCK"] != "0"
        launch(quiet + ["-kaiku.talk.voiceMuted", "NO"] + typed(said, every: every))
        step("today")
        pause(2.5)
        tab("Talk", after: 1)
        step("talk")
        let end = app.buttons["call.end"].firstMatch
        guard end.waitForExistence(timeout: 40) else {
            // no call on this service: Talk says so in one line, with the one action that helps
            miss("call (no live voice on this service)")
            pause(5)
            shot("talk-no-call")
            return
        }
        step("call")
        let voice = app.buttons["call.voice"].firstMatch
        var last = Date()
        if scripted {
            wait(4)
            voice.tap(); wait(3); voice.tap(); wait(2)
        } else {
            let inApp = lock ? Array(said.dropLast()) : said
            for (i, line) in inApp.enumerated() {
                let r = follow([line], every: every, first: i + 1)
                guard r.seen == 1 else { break }
                last = r.at
                if inApp.count > 1, i == inApp.count - 2 {
                    wait(min(9, every - 6))                 // Kaiku's answer to this line
                    if voice.exists { step("mute-kaiku"); voice.tap() }   // from here Kaiku is captions only
                }
            }
            wait(min(9, every - 8))                         // the answer to her last in-app line, as captions
            if voice.exists, voice.label.hasPrefix("Unmute") { step("unmute-kaiku"); voice.tap(); pause(1) }
        }
        if lock {
            if !scripted { wait(max(1, every - 6 - Date().timeIntervalSince(last))) }
            lockScreen(for: scripted ? 8 : 24)
            endOnLockScreen()
            _ = see("Call ended", timeout: 10)
        } else {
            wait(every)
            step("end")
            end.tap()
            _ = see("Call ended", timeout: 10)
        }
        pause(4)
        logSaid()
        shot("talk-end")
    }

    // MARK: e · You: sharing choices, each with its own switch; Glasses check with no glasses connected

    func testE_YouAndGlassesCheck() {
        launch()
        step("today")
        pause(2.5)
        tab("You", after: 3.5)
        step("you")
        if tap("Sharing and permissions", after: 3) {
            step("sharing-choices")
            let walks = app.switches.matching(NSPredicate(format: "label CONTAINS[c] %@", "Walks")).firstMatch
            if walks.exists {
                reveal(walks)
                walks.coordinate(withNormalizedOffset: CGVector(dx: 0.9, dy: 0.5)).tap(); pause(2.2)   // off…
                walks.coordinate(withNormalizedOffset: CGVector(dx: 0.9, dy: 0.5)).tap(); pause(2)     // …and on again
            } else { miss("Walks switch") }
            for _ in 0..<2 { scroll(0.3); pause(2.2) }
        }
        step("glasses-check")
        let check = button(containing: "Glasses check")
        reveal(check, tries: 8)
        if check.exists && check.isHittable {
            check.tap(); pause(4)
            for _ in 0..<2 { scroll(0.3); pause(2.5) }
            let run = app.buttons["Run the self-test"]
            reveal(run)
            if run.exists && run.isHittable {
                step("self-test")
                run.tap()
                allowSystemAlert(timeout: 3)
                pause(16)
                scroll(0.3); pause(4)
            } else { miss("Run the self-test") }
            back()
        } else { miss("Glasses check row") }
        pause(2)
    }

    // MARK: extras (not in the default recording list; `TESTS=...` on the recorder)

    /// Firefly from Play: half a minute of catching, the round ends on its own, the end screen.
    func testF_Firefly() {
        launch()
        step("play")
        tab("Play", after: 2.5)
        let card = button(containing: "Firefly")
        reveal(card, tries: 8)
        guard card.exists && card.isHittable else { miss("Firefly card"); return }
        card.tap(); pause(3)
        step("firefly")
        tap("Start", after: 1)
        var caught = 0, moth = false
        let end = Date().addingTimeInterval(58)
        let enough = app.buttons["That's enough for today"]
        while Date() < end {
            let f = app.buttons["Firefly"].firstMatch
            if f.exists, let frame = Optional(f.frame), frame.width > 0 {
                Thread.sleep(forTimeInterval: 0.25)
                app.coordinate(withNormalizedOffset: .zero).withOffset(CGVector(dx: frame.midX, dy: frame.midY)).tap()
                caught += 1
                Thread.sleep(forTimeInterval: 0.5)
            } else if caught % 5 == 4, !moth, app.buttons["Moth"].firstMatch.exists { moth = true }
            if caught > 3, enough.exists { break }
            Thread.sleep(forTimeInterval: 0.2)
        }
        print("DEMO-FIREFLY caught=\(caught)")
        finishGame(wait: 70)
    }

    /// A walk with simulated glasses (`-kaikuGlasses mock`): the three walk styles chosen where the walk starts,
    /// the walk screen, the spotting game counted on the phone, the Dynamic Island. Typed nowhere, spoken
    /// nowhere: without a microphone the walk has no conversation, and says so on screen.
    func testG_GlassesWalkSimulated() {
        launch(quiet + ["-kaikuGlasses", "mock", "-kaikuRoute", "walk"])
        step("walk-start")
        pause(3.5)
        // Calm · Playful · Chatty: each shows its one line; she settles on Playful
        for (style, name) in [("Playful", "style-playful"), ("Chatty", "style-chatty"), ("Calm", "style-calm"), ("Playful", "style-chosen")] {
            if tap(style, timeout: 4, after: 0.3, scrolls: false) { step(name); pause(2.6) }
        }
        if !tap("Walk with Kaiku", timeout: 3, after: 3) { tap("Start the walk", after: 3) }
        allowSystemAlert(timeout: 3)
        step("walking")
        _ = see("glasses", timeout: 6)
        pause(6)
        // the spotting game: a find marked on the phone starts the count ("1 of 3"), the card shows it
        let goal = app.descendants(matching: .any).matching(identifier: "walk.goal").firstMatch
        tap("Found one", after: 1.5, scrolls: false)
        if goal.waitForExistence(timeout: 4) { step("spotting-game") } else { miss("walk.goal") }
        pause(4)
        tap("Found one", timeout: 4, after: 3, scrolls: false)
        XCUIDevice.shared.press(.home)
        pause(3)
        step("island")
        springboard.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.03)).press(forDuration: 1.2)
        pause(3)
        let found = springboard.buttons["Found one"]
        if found.exists { found.tap(); pause(2.5) }
        XCUIDevice.shared.press(.home)
        pause(1)
        app.activate()
        pause(3)
        step("endwalk")
        let started = Date()
        while Date().timeIntervalSince(started) < 40 && app.buttons["End walk"].exists { Thread.sleep(forTimeInterval: 1) } // > 1 min walk
        tap("End walk", after: 4)
        step("walk-summary")
        pause(3)
        tap("Done", after: 2)
    }

    /// A check-in on a hard day (needs a service with a live voice, paid: one Live session). Today → the first
    /// stop → she types that the day is hard; Kaiku's answers are the real model's, and the chat goes on for as
    /// long as she likes. By default the phone is locked before her last line: Kaiku's answer to it arrives on
    /// the Lock Screen's bar and the call is ended there (`KAIKU_DEMO_LOCK=0`: she ends it in the app instead).
    /// `KAIKU_DEMO_HARD_SAY` / `_DELAY` change the lines and their spacing.
    func testH_CheckInHardDay() {
        let said = lines("KAIKU_DEMO_HARD_SAY", Self.hardDay)
        let every = seconds("KAIKU_DEMO_HARD_DELAY", 21)
        launch(quiet + typed(said, every: every))
        step("today")
        _ = see("Today's path", timeout: 12)
        pause(3)
        step("check-in")
        if !tap(containing: "Weather check", timeout: 5, after: 2) { tap("Start here", after: 2) }
        checkIn(said, every: every, lock: env["KAIKU_DEMO_LOCK"] != "0")
        pause(3)
    }
}

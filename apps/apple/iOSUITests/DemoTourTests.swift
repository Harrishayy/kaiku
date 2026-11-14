import XCTest

/// The iPhone demo recordings (`apps/apple/scripts/record_app_demo.sh ios`): one method per clip, driven like a
/// person would at a person's pace (read, then tap). Needs a local cloud seeded with the one person
/// (`KAIKU_TEST_CLOUD`, home `KAIKU_TEST_HOME`, default `aino`) and no model keys: where Kaiku's voice would
/// play, the app shows its words. A control that is missing is logged as `DEMO-MISSING` with what was on screen
/// (and a screenshot in `KAIKU_SHOT_DIR`), and the flow goes on, so a recording doubles as a smoke test.
/// `DEMO-STEP <name> <epoch>` lines are the chapter marks the recorder turns into time codes.
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
        if name.waitForExistence(timeout: 6) {
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
        pause(4)
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
        pause(4)
        tap("Go to Today", after: 3)
        step("today")
        _ = app.tabBars.buttons["Today"].waitForExistence(timeout: 8)
        pause(5)
    }

    // MARK: b · today's path: weather → Kaiku's suggestion → Lantern → today's rotating game → "All done for today"

    func testB_TodayPath() {
        launch()
        step("today")
        _ = see("Today's path", timeout: 12)
        pause(4)

        step("weather-check")
        tap(containing: "Weather check", after: 2.5)
        turnDial("Mood", to: 0.62)
        turnDial("Energy", to: 0.45)
        turnDial("Last night's sleep", to: 0.7)
        tap("That's it", after: 3.5)
        if app.buttons["Back"].exists { back() }

        // Kaiku's suggestion for today (the nudge decides: a walk, a breath or "Tell Kaiku")
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
        tab("Your days", after: 3.5)
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

    // MARK: d · Talk: the one voice control, the honest "voice unavailable" state, a starter instead

    func testD_Talk() {
        launch()
        step("today")
        pause(2.5)
        tab("Talk", after: 4)
        step("talk")
        if tap("Talk with Kaiku", timeout: 5, after: 1.5) {
            allowSystemAlert(timeout: 3)
            step("voice-state")
            pause(7)                                         // connecting → the reason voice is not there, in words
        }
        // Without the voice she answers with one of the starters ("Not sure where to start?").
        // She types (`KAIKU_DEMO_TYPE=0` picks a starter instead; typing hung the app before 7421f1c).
        if env["KAIKU_DEMO_TYPE"] != "0" {
            // by position, not by its placeholder: the label is gone as soon as there is text
            let composer = app.textFields.firstMatch
            if composer.waitForExistence(timeout: 4) {
                step("typing")
                composer.tap(); pause(1)
                for word in "I walked to the lake today.".split(separator: " ") { composer.typeText(word + " "); pause(0.25) }
                pause(1)
                tap("Send", after: 5)
            } else { miss("talk composer") }
        } else {
            step("starter")
            scroll(0.2); pause(1.5)
            if !tap(containing: "I went outside for a bit", timeout: 4, after: 2) { tap(containing: "Something good happened", timeout: 3, after: 2) }
        }
        step("reply")
        pause(6)
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

    /// A walk with simulated glasses (`-kaikuGlasses mock`): the walk screen, Dynamic Island, Lock Screen.
    func testG_GlassesWalkSimulated() {
        launch(["-kaikuGlasses", "mock", "-kaikuRoute", "walk"])
        step("walk")
        pause(2.5)
        if !tap("Walk with Kaiku", timeout: 3, after: 3) { tap("Start the walk", after: 3) }
        allowSystemAlert(timeout: 3)
        _ = see("glasses", timeout: 6)
        pause(6)
        tap("Found one", after: 2)
        XCUIDevice.shared.press(.home)
        pause(3)
        step("island")
        springboard.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.03)).press(forDuration: 1.2)
        pause(3)
        let found = springboard.buttons["Found one"]
        if found.exists { found.tap(); pause(2) }
        XCUIDevice.shared.press(.home)
        pause(1)
        app.activate()
        pause(2)
        step("endwalk")
        let started = Date()
        while Date().timeIntervalSince(started) < 45 && app.buttons["End walk"].exists { Thread.sleep(forTimeInterval: 1) } // > 1 min walk
        tap("End walk", after: 4)
        tap("Done", after: 2)
    }
}

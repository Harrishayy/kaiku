import XCTest

/// A paced walk through every iPhone feature, for screen recordings (`apps/apple/scripts/record_app_demo.sh`).
/// Each step waits ~1.5 s so a person can follow; a step whose control is missing is logged as `DEMO-MISSING`
/// (and the tour goes on), so a recording doubles as a smoke test. Needs a seeded cloud (KAIKU_TEST_CLOUD).
/// The methods are numbered so `xcodebuild test` runs them in story order; the script records each separately.
final class DemoTourTests: XCTestCase {
    let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
    var cloud: String { ProcessInfo.processInfo.environment["KAIKU_TEST_CLOUD"] ?? "http://127.0.0.1:8000" }
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
        if !missing.isEmpty { print("DEMO-MISSING-SUMMARY \(missing)") }
    }

    // MARK: helpers

    func launch(_ extra: [String], paired: Bool = true) {
        app = XCUIApplication()
        var args = ["-kaiku.lang", "en", "-AppleLanguages", "(en)"]
        if paired { args += ["-kaikuSkipOnboarding", "YES", "-kaikuPairLink", "\(cloud)/?home=demo-aino"] }
        app.launchArguments = args + extra
        app.launch()
        pause(2)
    }

    /// Taps where the element is right now, without failing the test if it just vanished (fireflies, pebbles).
    @discardableResult
    func quickTap(_ e: XCUIElement) -> Bool {
        guard let snap = try? e.snapshot(), snap.frame.width > 0 else { return false }
        let origin = app.coordinate(withNormalizedOffset: .zero)
        origin.withOffset(CGVector(dx: snap.frame.midX, dy: snap.frame.midY)).tap()
        return true
    }

    func pause(_ s: Double = 1.5) { Thread.sleep(forTimeInterval: s) }

    func step(_ name: String) { print("DEMO-STEP \(name) \(Date().timeIntervalSince1970)") }

    /// Taps the first button or text with this label; logs it as missing instead of failing the tour.
    @discardableResult
    func tap(_ label: String, timeout: TimeInterval = 6, after: Double = 1.5) -> Bool {
        let b = app.buttons[label].firstMatch
        let t = app.staticTexts[label].firstMatch
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if b.exists && b.isHittable { b.tap(); pause(after); return true }
            if t.exists && t.isHittable { t.tap(); pause(after); return true }
            Thread.sleep(forTimeInterval: 0.25)
        }
        print("DEMO-MISSING \(label)")
        missing.append(label)
        return false
    }

    func see(_ text: String, timeout: TimeInterval = 6) -> Bool {
        let pred = NSPredicate(format: "label CONTAINS[c] %@", text)
        let ok = app.descendants(matching: .any).matching(pred).firstMatch.waitForExistence(timeout: timeout)
        if !ok { print("DEMO-MISSING see:\(text)"); missing.append("see:\(text)") }
        return ok
    }

    func back() { tap("Back", timeout: 3, after: 1.2) }

    func endGame() {
        if !tap("That's enough for today", timeout: 70) { back() }
    }

    func answerNotification(containing text: String, action: String) {
        let pred = NSPredicate(format: "label CONTAINS[c] %@", text)
        let banner = springboard.descendants(matching: .any).matching(pred).firstMatch
        guard banner.waitForExistence(timeout: 25) else { print("DEMO-MISSING notification:\(text)"); missing.append("notification"); return }
        pause(2)
        let c = banner.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
        c.press(forDuration: 0.3, thenDragTo: c.withOffset(CGVector(dx: 0, dy: 260)))
        pause(2)
        let b = springboard.buttons[action]
        if b.waitForExistence(timeout: 6) { b.tap() } else { print("DEMO-MISSING action:\(action)"); missing.append(action) }
        pause(2)
    }

    // MARK: 1 · first launch → Today → weather check → every game → Talk → Your days → You

    func test1Tour() {
        launch([], paired: false)
        step("onboarding")
        tap("Say hello", after: 2)
        tap("Paste a link instead")
        let field = app.textFields.firstMatch.exists ? app.textFields.firstMatch : app.textViews.firstMatch
        if field.waitForExistence(timeout: 4) {
            field.tap()
            field.typeText("\(cloud)/?home=demo-aino")
            pause(1)
            tap("Continue", after: 3)            // pairs, shows "Found you!", moves on by itself
        } else { missing.append("pair field") }
        step("consent")
        pause(1.5)
        tap("Continue", after: 2)
        step("notifications")
        tap("Allow nudges", after: 1)
        let allow = springboard.buttons["Allow"]
        if allow.waitForExistence(timeout: 4) { allow.tap() }
        pause(1.5)
        step("meet")
        let mascot = app.descendants(matching: .any)["Kaiku"].firstMatch
        if mascot.exists && mascot.isHittable { mascot.tap() }
        pause(1.5)
        tap("Let's start", after: 3)

        step("today")
        _ = see("Aino", timeout: 10)
        pause(2.5)
        step("weather")
        tap("Weather check", after: 2)
        for name in ["Mood", "Energy", "Last night's sleep"] {
            let d = app.otherElements[name].firstMatch.exists ? app.otherElements[name].firstMatch : app.descendants(matching: .any)[name].firstMatch
            guard d.exists else { missing.append("dial \(name)"); continue }
            let from = d.coordinate(withNormalizedOffset: CGVector(dx: 0.15, dy: 0.72))
            from.press(forDuration: 0.15, thenDragTo: d.coordinate(withNormalizedOffset: CGVector(dx: 0.8, dy: 0.72)))
            pause(1)
        }
        tap("That's it", after: 2.5)
        _ = see("noted", timeout: 4)
        pause(1)
        if app.buttons["Back"].exists { back() }
        if app.buttons["Today"].exists && app.buttons["Today"].isHittable { app.buttons["Today"].tap() }

        step("play")
        tap("Play", after: 2)
        step("firefly")
        tap("Firefly", after: 2.5)            // intro with its looping demo
        tap("Start", after: 1)
        var caught = 0, moth = false
        let end = Date().addingTimeInterval(14)
        while Date() < end {
            let f = app.buttons["Firefly"].firstMatch
            if quickTap(f) { caught += 1; Thread.sleep(forTimeInterval: 0.6) }
            if !moth, quickTap(app.buttons["Moth"].firstMatch) { moth = true }
            Thread.sleep(forTimeInterval: 0.2)
        }
        print("DEMO-FIREFLY caught=\(caught) moth=\(moth)")
        endGame()                            // waits for the 60 s round to end on its own

        step("pebbles")
        tap("Pebble path", after: 2.5)
        tap("Start", after: 1)
        let pbEnd = app.buttons["That's enough for today"]
        let pbDeadline = Date().addingTimeInterval(45)
        while !pbEnd.exists && Date() < pbDeadline {
            let p = app.buttons["Pebble 1"]
            if p.exists && p.isEnabled && app.staticTexts["Your turn"].exists { quickTap(p); pause(0.5); quickTap(p); pause(0.5) }
            Thread.sleep(forTimeInterval: 0.5)
        }
        pause(2)
        endGame()

        step("breathe")
        tap("Breathe", after: 2.5)
        tap("Start", after: 11)              // one in-and-out cycle
        tap("Stop", after: 2.5)
        if app.buttons["That's enough for today"].exists { endGame() } else if app.buttons["Back"].exists { back() }

        step("tell")
        tap("Tell Kaiku", after: 2.5)
        tap("Start", after: 1.5)
        tap("Start talking", after: 5)
        tap("I'm done", after: 4)
        endGame()

        step("talk")
        tap("Talk", after: 2.5)
        _ = see("online", timeout: 4)        // the offline card: Live needs a cloud token
        let composer = app.textFields["Type a message"].firstMatch.exists ? app.textFields["Type a message"].firstMatch
            : app.textViews.firstMatch
        if composer.waitForExistence(timeout: 4) {
            composer.tap()
            composer.typeText("I walked to the lake today.")
            pause(1)
            tap("Send", after: 3)
        } else { missing.append("talk composer") }

        step("days")
        tap("Your days", after: 3)
        step("you")
        tap("You", after: 2)
        tap("What Kaiku remembers", after: 3)
        _ = see("rain", timeout: 6)
        back()
        tap("What Kaiku saw today", after: 3)
        back()
        if !app.staticTexts["Devices"].isHittable { app.swipeUp(); pause(1) }
        tap("Devices", after: 3)
        back()
        pause(1.5)
    }

    // MARK: 2 · a walk with the (mock) Meta glasses → Dynamic Island + Lock Screen Live Activity

    func test2GlassesWalk() {
        launch(["-kaikuMute", "YES", "-kaikuGlasses", "mock"])
        step("walk")
        tap("Play", after: 1.5)
        tap("Light hunt", after: 2)
        tap("Start the walk", after: 3)
        _ = see("glasses", timeout: 6)
        pause(2)
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
        step("lock")
        XCUIDevice.shared.perform(NSSelectorFromString("pressLockButton"))
        pause(2)
        XCUIDevice.shared.press(.home)
        pause(4)
        XCUIDevice.shared.press(.home)
        pause(1)
        XCUIDevice.shared.press(.home)
        app.activate()
        pause(2)
        step("endwalk")
        let started = Date()
        while Date().timeIntervalSince(started) < 40 && app.buttons["End walk"].exists { Thread.sleep(forTimeInterval: 1) } // > 1 min walk
        tap("End walk", after: 3)
        tap("Done", after: 1.5)
    }

    // MARK: 3 · the check-in reminder answered "Low" from the notification

    func test3Notification() {
        launch(["-kaikuMute", "YES", "-kaikuNotifyTest", "checkin", "-kaikuNotifyDelay", "6"])
        let allow = springboard.buttons["Allow"]
        if allow.waitForExistence(timeout: 3) { allow.tap() }
        XCUIDevice.shared.press(.home)
        step("notification")
        answerNotification(containing: "weather inside", action: "Low")
        app.activate()
        pause(2)
        tap("You", after: 1.5)
        tap("What Kaiku saw today", after: 3)
    }

    // MARK: 4 · Apple Health sample night → daily totals (Watch signal)

    func test4Health() {
        launch(["-kaikuMute", "YES", "-kaikuHealthSample", "YES"])
        step("health")
        let all = app.staticTexts["Turn On All"]
        if all.waitForExistence(timeout: 10) {
            pause(1.5)
            all.tap()
            pause(1.5)
            if app.buttons["Allow"].firstMatch.exists { app.buttons["Allow"].firstMatch.tap() }
        } else { print("DEMO-MISSING health sheet") }
        pause(4)
        tap("You", after: 1.5)
        if !app.staticTexts["Devices"].isHittable { app.swipeUp(); pause(1) }
        tap("Devices", after: 3)
    }
}

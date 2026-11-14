import XCTest

/// First-run setup end to end on a fresh install, against a local demo cloud (KAIKU_TEST_CLOUD):
/// welcome → what Kaiku is and isn't → connect → choices → permissions → first hello + practice task →
/// celebration → Today; then resume after a relaunch mid-setup and "Run setup again" from You.
/// Never opens the microphone or camera: the microphone row is checked for, not pressed.
/// Screenshots go to $KAIKU_SHOT_DIR when set.
final class SetupFlowTests: XCTestCase {
    let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
    var cloud: String { ProcessInfo.processInfo.environment["KAIKU_TEST_CLOUD"] ?? "http://127.0.0.1:8000" }
    var app: XCUIApplication!

    override func setUp() {
        continueAfterFailure = false
        addUIInterruptionMonitor(withDescription: "system alerts") { alert in
            for b in ["Allow", "OK", "Allow While Using App"] where alert.buttons[b].exists { alert.buttons[b].tap(); return true }
            return false
        }
    }

    func launch(_ extra: [String] = []) {
        app = XCUIApplication()
        app.launchArguments = ["-kaiku.lang", "en", "-AppleLanguages", "(en)", "-kaikuMute", "YES"] + extra
        app.launch()
    }

    func shot(_ name: String) {
        let s = XCUIScreen.main.screenshot()
        let a = XCTAttachment(screenshot: s)
        a.name = name; a.lifetime = .keepAlways
        add(a)
        if let dir = ProcessInfo.processInfo.environment["KAIKU_SHOT_DIR"] {
            try? s.pngRepresentation.write(to: URL(fileURLWithPath: dir).appendingPathComponent("\(name).png"))
        }
    }

    func see(_ text: String, timeout: TimeInterval = 8, file: StaticString = #filePath, line: UInt = #line) {
        let pred = NSPredicate(format: "label CONTAINS[c] %@", text)
        XCTAssertTrue(app.descendants(matching: .any).matching(pred).firstMatch.waitForExistence(timeout: timeout),
                      "expected to see: \(text)", file: file, line: line)
    }

    func tap(_ label: String, file: StaticString = #filePath, line: UInt = #line) {
        let b = app.buttons[label].firstMatch
        XCTAssertTrue(b.waitForExistence(timeout: 8), "no button: \(label)", file: file, line: line)
        if !b.isHittable { app.swipeUp() }
        b.tap()
    }

    func testFirstRunSetupToTodayThenResumeAndRunAgain() {
        // A fresh person: not onboarded, no service, start of setup (argument domain overrides stored values).
        launch(["-kaiku.onboarded", "NO", "-kaikuOnboardingStep", "0"])
        see("Hi, I'm Kaiku"); shot("setup-1-welcome")
        tap("Say hello")

        see("What I am, and what I'm not")
        see("Not emergency care"); see("112"); see("Not a medical opinion")
        XCTAssertFalse(app.buttons["Skip"].exists, "the limits cannot be skipped")
        shot("setup-2-about")
        tap("I understand")

        see("Nearby Kaiku services"); see("Step 3 of 6"); shot("setup-3-connect")
        tap("Advanced: service address or account link")
        let field = app.textFields.firstMatch
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        field.tap()
        field.typeText("\(cloud)/?home=setup-ui-test")
        tap("Find service")

        see("Your choices"); see("Keep our conversations"); shot("setup-4-choices")
        tap("Continue")

        see("A few permissions"); see("Microphone"); see("Gentle nudges"); see("Apple Health", timeout: 2)
        XCTAssertTrue(app.buttons["Allow: Microphone"].exists, "asked for in context, not on arrival")
        shot("setup-5-permissions")
        tap("Continue")

        see("It's really good to meet you"); see("One small thing to try"); see("Nothing is saved"); shot("setup-6-hello")
        tap("That's it")
        see("You did it"); shot("setup-7-celebration")
        tap("Go to Today")

        XCTAssertTrue(app.tabBars.buttons["Today"].waitForExistence(timeout: 8))
        shot("setup-8-today")

        // Run setup again from You: same flow, choices and connection kept.
        app.tabBars.buttons["You"].tap()
        let again = app.buttons.matching(NSPredicate(format: "label CONTAINS[c] %@", "Run setup again")).firstMatch
        for _ in 0..<4 where !(again.exists && again.isHittable) { app.swipeUp() }
        XCTAssertTrue(again.waitForExistence(timeout: 5))
        again.tap()
        see("Hi, I'm Kaiku")
        tap("Say hello"); tap("I understand")
        see("Connected to your Kaiku service")   // still connected
        shot("setup-9-again-connected")
    }

    func testSetupResumesWhereItWasLeft() {
        launch(["-kaiku.onboarded", "NO", "-kaikuOnboardingStep", "0"])
        tap("Say hello"); tap("I understand")
        see("Nearby Kaiku services")
        // No service: Skip is allowed and the app still works; already connected: Continue.
        if app.buttons["Skip for now"].waitForExistence(timeout: 3) { app.buttons["Skip for now"].tap() }
        else if app.buttons["Skip"].exists { app.buttons["Skip"].tap() } else { tap("Continue") }
        see("Your choices")
        app.terminate()
        launch(["-kaiku.onboarded", "NO"])           // no step argument: the saved step decides
        see("Your choices")
        shot("setup-resumed-choices")
    }
}

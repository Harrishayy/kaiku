import XCTest

/// A2 end-to-end against a local cloud (make cloud-local + make seed), driving the real system surfaces:
/// a check-in reminder answered "Low" from the banner → obs.self_report{value: 2, channel: phone}; an invitation
/// answered "Not today" → obs.nudge_outcome{accepted: false}; a mock-glasses walk → Dynamic Island + Lock Screen
/// Live Activity (screenshots to $KAIKU_SHOT_DIR when set) → obs.outing{method: dat_imu}.
final class ExtrasFlowTests: XCTestCase {
    let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
    var cloud: String { ProcessInfo.processInfo.environment["KAIKU_TEST_CLOUD"] ?? "http://127.0.0.1:8000" }

    override func setUp() { continueAfterFailure = false }

    func launch(_ extra: [String]) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-kaikuSkipOnboarding", "YES", "-kaikuPairLink", "\(cloud)/?home=demo-aino", "-kaikuMute", "YES",
                               "-kaiku.lang", "en", "-AppleLanguages", "(en)"] + extra
        app.launch()
        return app
    }

    func allowNotificationsIfAsked() {
        let allow = springboard.buttons["Allow"]
        if allow.waitForExistence(timeout: 4) { allow.tap() }
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

    /// Opens Notification Center (reminders are `.passive`: no banner, they wait in the list), long-presses the
    /// notification to reveal its actions, then taps one.
    func answerBanner(containing text: String, action: String) {
        let pred = NSPredicate(format: "label CONTAINS[c] %@", text)
        let cell = springboard.buttons.matching(pred).firstMatch
        let banner = cell.waitForExistence(timeout: 3) ? cell : springboard.descendants(matching: .any).matching(pred).firstMatch
        if !banner.waitForExistence(timeout: 20) {
            try? springboard.debugDescription.write(toFile: (ProcessInfo.processInfo.environment["KAIKU_SHOT_DIR"] ?? "/tmp") + "/springboard.txt",
                                                     atomically: true, encoding: .utf8)
            XCTFail("no banner with \(text)")
        }
        shot("notification-banner-\(action)")
        // pull the banner down → the expanded notification with its action buttons
        let c = banner.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
        c.press(forDuration: 0.3, thenDragTo: c.withOffset(CGVector(dx: 0, dy: 260)))
        let button = springboard.buttons[action]
        if !button.waitForExistence(timeout: 6) {
            try? springboard.debugDescription.write(toFile: (ProcessInfo.processInfo.environment["KAIKU_SHOT_DIR"] ?? "/tmp") + "/springboard-actions.txt",
                                                     atomically: true, encoding: .utf8)
            shot("no-actions-\(action)")
            XCTFail("no action \(action)")
        }
        shot("notification-actions-\(action)")
        button.tap()
    }

    func events(since: Date) throws -> [[String: Any]] {
        let f = ISO8601DateFormatter()
        let url = URL(string: "\(cloud)/v1/events?home_id=demo-aino&limit=500&since=\(f.string(from: since))")!
        let data = try Data(contentsOf: url)
        return (try JSONSerialization.jsonObject(with: data) as? [String: Any])?["events"] as? [[String: Any]] ?? []
    }

    func waitForEvent(_ since: Date, timeout: TimeInterval = 20, _ match: ([String: Any]) -> Bool) throws -> [String: Any]? {
        let end = Date().addingTimeInterval(timeout)
        while Date() < end {
            if let e = try events(since: since).first(where: match) { return e }
            sleep(1)
        }
        return nil
    }

    func testCheckinReminderLow() throws {
        let start = Date().addingTimeInterval(-2)
        _ = launch(["-kaikuNotifyTest", "checkin", "-kaikuNotifyDelay", "8"])
        allowNotificationsIfAsked()
        answerBanner(containing: "weather inside", action: "Low")
        let e = try waitForEvent(start) { e in
            let p = e["payload"] as? [String: Any]
            return e["type"] as? String == "obs.self_report" && p?["channel"] as? String == "phone" && p?["value"] as? Int == 2
        }
        XCTAssertNotNil(e, "obs.self_report value 2 did not land")
    }

    func testInvitationNotToday() throws {
        let start = Date().addingTimeInterval(-2)
        _ = launch(["-kaikuNotifyTest", "invite", "-kaikuNotifyDelay", "8"])
        allowNotificationsIfAsked()
        answerBanner(containing: "feels right today", action: "Not today")
        let e = try waitForEvent(start) { e in
            e["type"] as? String == "obs.nudge_outcome" && (e["payload"] as? [String: Any])?["accepted"] as? Bool == false
        }
        XCTAssertNotNil(e, "obs.nudge_outcome did not land")
    }

    func testMockGlassesWalkLiveActivity() throws {
        let start = Date().addingTimeInterval(-2)
        let app = launch(["-kaikuRoute", "walk", "-kaikuAutostart", "YES", "-kaikuGlasses", "mock"])
        XCTAssertTrue(app.buttons["Found one"].waitForExistence(timeout: 10))
        sleep(4)
        app.buttons["Found one"].tap()
        shot("walk-app")
        XCUIDevice.shared.press(.home)
        sleep(2)
        shot("island-compact")
        // long-press the island → expanded
        let island = springboard.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.03))
        island.press(forDuration: 1.2)
        sleep(2)
        shot("island-expanded")
        XCUIDevice.shared.press(.home)
        // lock → the Lock Screen Live Activity
        XCUIDevice.shared.perform(NSSelectorFromString("pressLockButton"))
        sleep(2)
        XCUIDevice.shared.press(.home)   // wake to the Lock Screen
        sleep(2)
        shot("lock-screen")
        XCUIDevice.shared.press(.home)
        sleep(1)
        XCUIDevice.shared.press(.home)
        app.activate()
        // walks under one minute are not posted: wait until a minute has passed
        let minute = start.addingTimeInterval(64)
        while Date() < minute { sleep(2) }
        XCTAssertTrue(app.buttons["End walk"].waitForExistence(timeout: 10))
        app.buttons["End walk"].tap()
        let e = try waitForEvent(start) { e in
            e["type"] as? String == "obs.outing" && (e["payload"] as? [String: Any])?["method"] as? String == "dat_imu"
        }
        XCTAssertNotNil(e, "obs.outing dat_imu did not land")
        if let p = e?["payload"] { print("OUTING \(p)") }
    }

    func testHealthSampleWearableDaily() throws {
        let start = Date().addingTimeInterval(-2)
        let app = launch(["-kaikuHealthSample", "YES"])
        // the Health permission sheet (in the app's process)
        let all = app.staticTexts["Turn On All"]
        if all.waitForExistence(timeout: 10) {
            all.tap()
            shot("health-permission")
            app.buttons["Allow"].firstMatch.tap()
        }
        let day = { let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; return f.string(from: Date()) }()
        _ = start
        let e = try waitForEvent(Date().addingTimeInterval(-86400), timeout: 25) { e in
            e["type"] as? String == "obs.wearable_daily" && (e["payload"] as? [String: Any])?["date"] as? String == day
        }
        XCTAssertNotNil(e, "obs.wearable_daily did not land")
        if let p = e?["payload"] { print("WEARABLE \(p)") }
    }
}

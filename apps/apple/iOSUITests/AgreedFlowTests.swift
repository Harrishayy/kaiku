import XCTest

/// An activity agreed in one place shows up everywhere at once (D50), end to end against a local cloud:
///   1. Today is open; a yes said "on the robot" (the tool call posted to the cloud, as the hub does) puts the
///      card on Today within a second or two, with nobody touching the app; an observation that completes the
///      activity (played on another device) turns it to done.
///   2. A call is on and the phone is locked; the same yes posts a notification on the Lock Screen. Unlocked with
///      the app still behind, the next one is a banner whose Start opens the activity and tells the cloud so.
///   3. A walk is on and the phone is locked; a yes said on the walk posts the notification at once.
/// Opt-in: `KAIKU_AGREED_CLOUD=http://127.0.0.1:<port>` (a cloud started from this tree with its own database,
/// seeded with the one person; `KAIKU_AGREED_HOME`, default `aino`). Screenshots and `timing.txt` go to
/// `$KAIKU_SHOT_DIR`. The calls and walks here are scripted or silent: no microphone is opened.
/// The words of each yes are the person's own ask ("Can we …", "I want …", "Remind me …"): the seeded person is
/// on an extra-gentle day, when the cloud keeps only what they bring up themselves and refuses a plain "yes".
final class AgreedFlowTests: XCTestCase {
    let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
    let app = XCUIApplication(bundleIdentifier: "fi.kaiku.app")
    var env: [String: String] { ProcessInfo.processInfo.environment }
    var home: String { env["KAIKU_AGREED_HOME"] ?? "aino" }
    var shots: String { env["KAIKU_SHOT_DIR"] ?? NSTemporaryDirectory() }
    private var cloud = ""

    override func setUpWithError() throws {
        continueAfterFailure = false
        guard let url = env["KAIKU_AGREED_CLOUD"], !url.isEmpty else {
            throw XCTSkip("set KAIKU_AGREED_CLOUD to a local cloud seeded with the one person")
        }
        cloud = url
        try FileManager.default.createDirectory(atPath: shots, withIntermediateDirectories: true)
    }

    // MARK: the service, as another device would talk to it

    private func call(_ method: String, _ path: String, _ body: [String: Any]? = nil) throws -> (Int, [String: Any]) {
        var request = URLRequest(url: URL(string: cloud + path)!)
        request.httpMethod = method
        request.timeoutInterval = 10
        if let body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let done = DispatchSemaphore(value: 0)
        nonisolated(unsafe) var result: (Int, [String: Any]) = (0, [:])
        URLSession.shared.dataTask(with: request) { data, response, _ in
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            result = (code, (data.flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any]) ?? [:])
            done.signal()
        }.resume()
        _ = done.wait(timeout: .now() + 12)
        return result
    }

    private func agreed() throws -> [[String: Any]] {
        try call("GET", "/v1/me/invitation?home_id=\(home)&surface=iphone").1["agreed"] as? [[String: Any]] ?? []
    }

    /// Nothing open from an earlier run: the day starts clean.
    private func putEverythingAside() throws {
        for item in try agreed() where ["open", "started"].contains(item["state"] as? String ?? "") {
            _ = try call("POST", "/v1/me/agreed/answer?home_id=\(home)&surface=iphone", ["id": item["id"] as? String ?? "", "answer": "put_aside"])
        }
    }

    /// The model's tool call as a device forwards it (`POST /v1/companion/tool`).
    private func sayYes(on surface: String, to kind: String, when: String, said: String) throws -> [String: Any] {
        let (code, answer) = try call("POST", "/v1/companion/tool", [
            "home_id": home, "surface": surface, "name": "agree_activity",
            "args": ["kind": kind, "said": said, "when": when],
        ])
        XCTAssertEqual(code, 200)
        XCTAssertEqual(answer["ok"] as? Bool, true, "\(answer)")
        return answer["result"] as? [String: Any] ?? [:]
    }

    private func state(of id: String) throws -> String? {
        try agreed().first { $0["id"] as? String == id }?["state"] as? String
    }

    // MARK: the app

    private func launch(_ extra: [String], trace: String) {
        try? FileManager.default.removeItem(atPath: trace)
        app.launchArguments = ["-kaikuSkipOnboarding", "YES", "-kaikuPairLink", "\(cloud)/?home=\(home)", "-kaikuMute", "YES",
                               "-kaiku.lang", "en", "-AppleLanguages", "(en)", "-kaikuStreamTrace", trace] + extra
        app.launch()
    }

    private func allowNotificationsIfAsked() {
        let allow = springboard.buttons["Allow"]
        if allow.waitForExistence(timeout: 6) { allow.tap() }
    }

    private func shot(_ name: String) {
        let s = XCUIScreen.main.screenshot()
        let a = XCTAttachment(screenshot: s)
        a.name = name; a.lifetime = .keepAlways
        add(a)
        try? s.pngRepresentation.write(to: URL(fileURLWithPath: shots).appendingPathComponent("\(name).png"))
    }

    /// The time of the first trace line at or after `from` that starts with `prefix` (the app writes one line per
    /// stream step: `-kaikuStreamTrace`).
    private func traced(_ prefix: String, in trace: String, from: Date, within seconds: TimeInterval = 6) -> Date? {
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let end = Date().addingTimeInterval(seconds)
        repeat {
            let text = (try? String(contentsOfFile: trace, encoding: .utf8)) ?? ""
            for line in text.split(separator: "\n") {
                let parts = line.split(separator: " ", maxSplits: 1)
                guard parts.count == 2, parts[1].hasPrefix(prefix), let at = iso.date(from: String(parts[0])),
                      at >= from.addingTimeInterval(-0.002) else { continue }
                return at
            }
            usleep(50_000)
        } while Date() < end
        return nil
    }

    private func note(_ line: String) {
        let url = URL(fileURLWithPath: shots).appendingPathComponent("timing.txt")
        let text = ((try? String(contentsOf: url, encoding: .utf8)) ?? "") + line + "\n"
        try? text.write(to: url, atomically: true, encoding: .utf8)
        print("AGREED-TIMING \(line)")
    }

    private func ms(_ from: Date, _ to: Date?) -> String { to.map { String(format: "%.0f ms", $0.timeIntervalSince(from) * 1000) } ?? "not seen" }

    // MARK: 1. Today is open

    func testAYesOnTheRobotShowsOnTodayAtOnceAndTurnsDone() throws {
        try putEverythingAside()
        let trace = shots + "/trace-today.txt"
        launch([], trace: trace)
        XCTAssertTrue(app.staticTexts["Today's path"].waitForExistence(timeout: 20), "Today is open")
        XCTAssertNotNil(traced("hello", in: trace, from: .distantPast, within: 15), "the stream is open")
        sleep(2)
        XCTAssertFalse(app.otherElements["today.agreed"].exists)
        shot("1-today-before")

        // Said yes on the robot. Nobody touches the phone.
        let asked = Date()
        let result = try sayYes(on: "robot", to: "lantern", when: "later", said: "Can we play the lantern game later today?")
        let answered = Date()
        let card = app.otherElements["today.agreed"]
        XCTAssertTrue(card.waitForExistence(timeout: 5), "the card arrived by itself")
        let seen = Date()
        let event = traced("agreed open", in: trace, from: asked), read = traced("offers agreed=", in: trace, from: asked)
        note("today: tool call answered by the cloud after \(ms(asked, answered))")
        note("today: stream event in the app after \(ms(asked, event))")
        note("today: list read, card on Today after \(ms(asked, read))")
        note("today: card found by the test after \(ms(asked, seen)) (includes the test's own polling)")
        XCTAssertNotNil(read)
        XCTAssertLessThan(read!.timeIntervalSince(asked), 2, "within a second or two")
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "you said yes to Lantern")).firstMatch.exists)
        XCTAssertTrue(app.buttons["today.agreed.start"].exists, "one clear action")
        XCTAssertTrue(app.buttons["today.agreed.notnow"].exists)
        XCTAssertTrue(app.staticTexts["Today's path"].isHittable, "the day's path is still on screen")
        XCTAssertEqual(result["where"] as? String != nil, true, "what Kaiku says on the robot: \(result)")
        usleep(600_000)
        shot("2-today-card")

        // The activity is done on another device (a Lantern session from the Mac): the same item turns done here.
        let id = try XCTUnwrap(result["id"] as? String)
        let played = Date()
        let (code, taken) = try call("POST", "/v1/events", ["events": [[
            "v": 1, "id": UUID().uuidString.lowercased(), "ts": ISO8601DateFormatter().string(from: Date()), "home_id": home,
            "source": "laptop", "type": "obs.play_session", "sim": true,
            "payload": ["game": "lantern", "device": "mac", "duration_s": 60],
        ]]])
        XCTAssertEqual(code, 200, "\(taken)")
        XCTAssertEqual(taken["accepted"] as? Int, 1, "\(taken)")
        let done = app.descendants(matching: .any)["today.agreed.row.done"]
        XCTAssertTrue(done.waitForExistence(timeout: 5), "it turned done by itself")
        note("today: done on Today after \(ms(played, traced("agreed done", in: trace, from: played))) (event) / \(ms(played, Date())) (found by the test)")
        XCTAssertEqual(try state(of: id), "done")
        XCTAssertFalse(app.buttons["today.agreed.start"].exists)
        shot("3-today-done")
        usleep(900_000)
        shot("3b-today-done-settled")
    }

    // MARK: 2. A call is on, the phone is locked

    func testAYesDuringACallNotifiesOnTheLockScreen() throws {
        try putEverythingAside()
        let trace = shots + "/trace-call.txt"
        // A call on the scripted Live: no network for the voice, no microphone. `-kaikuNotifyTest` is how a debug
        // run asks for notification permission (its own test notification is an hour away).
        launch(["-kaikuTab", "talk", "-kaikuTalkDemo", "live", "-kaikuNotifyTest", "invite", "-kaikuNotifyDelay", "3600"], trace: trace)
        allowNotificationsIfAsked()
        XCTAssertNotNil(traced("hello", in: trace, from: .distantPast, within: 20), "the stream is open")
        sleep(3)
        shot("4-call")

        XCUIDevice.shared.perform(NSSelectorFromString("pressLockButton"))
        sleep(4)
        let asked = Date()
        let result = try sayYes(on: "robot", to: "breathe", when: "now", said: "I want to do the breathing now.")
        let id = try XCTUnwrap(result["id"] as? String)
        note("call, locked: stream event in the app after \(ms(asked, traced("agreed open", in: trace, from: asked)))")
        note("call, locked: list read after \(ms(asked, traced("offers agreed=", in: trace, from: asked)))")
        XCUIDevice.shared.press(.home)                     // wake to the Lock Screen
        let pred = NSPredicate(format: "label CONTAINS[c] %@", "you said yes to breathing together")
        let notice = springboard.descendants(matching: .any).matching(pred).firstMatch
        XCTAssertTrue(notice.waitForExistence(timeout: 12), "the notification is on the Lock Screen")
        note("call, locked: notification found on the Lock Screen after \(ms(asked, Date())) (includes waking the screen)")
        sleep(1)
        shot("5-lock-notification")

        // Unlocked, the app still behind (the call goes on): the next yes arrives as a banner, and its actions do
        // what the card does. Start opens the activity's screen and the cloud hears it was opened.
        XCUIDevice.shared.press(.home)                     // past the Lock Screen (no passcode on the simulator)
        sleep(2)
        if app.state == .runningForeground { XCUIDevice.shared.press(.home); sleep(2) }
        let second = try sayYes(on: "robot", to: "seeds", when: "later", said: "Remind me to do the seed shelf later.")
        let seeds = try XCTUnwrap(second["id"] as? String)
        let banner = springboard.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS[c] %@", "you said yes to Seed shelf")).firstMatch
        XCTAssertTrue(banner.waitForExistence(timeout: 10), "a banner while the app is behind")
        shot("6-banner")
        let c = banner.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
        c.press(forDuration: 0.3, thenDragTo: c.withOffset(CGVector(dx: 0, dy: 260)))   // pull it down: its actions
        let start = springboard.buttons["Start"]
        if start.waitForExistence(timeout: 6) {
            XCTAssertTrue(springboard.buttons["Not now"].exists)
            shot("7-banner-actions")
            start.tap()
        } else {
            try? springboard.debugDescription.write(toFile: shots + "/springboard-actions.txt", atomically: true, encoding: .utf8)
            shot("7-banner-no-actions")
            XCUIDevice.shared.press(.home)
            XCTFail("the banner did not show its actions")
        }
        let end = Date().addingTimeInterval(15)
        while try state(of: seeds) != "started", Date() < end { sleep(1) }
        XCTAssertEqual(try state(of: seeds), "started", "the cloud heard it was opened")
        XCTAssertTrue(app.wait(for: .runningForeground, timeout: 10))
        sleep(2)
        shot("8-started-from-the-notification")
        XCTAssertEqual(try state(of: id), "open", "the other one still waits")
    }

    // MARK: 3. A walk is on, the phone is locked

    func testAYesOnAWalkNotifiesOnTheLockedPhone() throws {
        try putEverythingAside()
        let trace = shots + "/trace-walk.txt"
        launch(["-kaikuRoute", "walk", "-kaikuAutostart", "YES", "-kaikuGlasses", "mock", "-kaikuNotifyTest", "invite", "-kaikuNotifyDelay", "3600"], trace: trace)
        allowNotificationsIfAsked()
        XCTAssertTrue(app.buttons["Found one"].waitForExistence(timeout: 20), "the walk is on")
        XCTAssertNotNil(traced("hello", in: trace, from: .distantPast, within: 20), "the stream is open")
        XCUIDevice.shared.perform(NSSelectorFromString("pressLockButton"))
        sleep(4)
        let asked = Date()
        let result = try sayYes(on: "glasses", to: "lantern", when: "later", said: "Remind me to play the lantern when I'm home.")
        XCTAssertNotNil(result["id"] as? String)
        note("walk, locked: stream event in the app after \(ms(asked, traced("agreed open", in: trace, from: asked)))")
        note("walk, locked: list read after \(ms(asked, traced("offers agreed=", in: trace, from: asked)))")
        XCUIDevice.shared.press(.home)
        let pred = NSPredicate(format: "label CONTAINS[c] %@", "On your walk you said yes to Lantern")
        XCTAssertTrue(springboard.descendants(matching: .any).matching(pred).firstMatch.waitForExistence(timeout: 12), "the notification is on the Lock Screen")
        sleep(1)
        shot("9-walk-lock-notification")
        XCUIDevice.shared.press(.home)
        app.activate()
        if app.buttons["End walk"].waitForExistence(timeout: 8) { app.buttons["End walk"].tap() }
    }
}

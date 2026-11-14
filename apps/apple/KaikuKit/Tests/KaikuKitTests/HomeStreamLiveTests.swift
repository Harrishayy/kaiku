import XCTest
@preconcurrency import UserNotifications
@testable import KaikuKit

/// The Mac's side of "agreed in one place, shown everywhere" against a running service (D50): the real
/// `HomeUpdates`, the real `URLSession` stream, the real list and the real notification rule, as the Mac app
/// runs them with its main window not in front. Only the notification centre is replaced (requests are caught,
/// nothing is shown on this Mac) and the pairing is in memory (the Keychain is never touched).
///
/// Opt-in: `KAIKU_STREAM_CLOUD=http://127.0.0.1:<port> swift test --filter HomeStreamLiveTests`, with a local
/// cloud seeded with the one person (`KAIKU_STREAM_HOME`, default `aino`). `KAIKU_SHOT_DIR`: where the measured
/// times are written (`timing-mac.txt`).
@MainActor final class HomeStreamLiveTests: XCTestCase {
    private var env: [String: String] { ProcessInfo.processInfo.environment }
    private var home: String { env["KAIKU_STREAM_HOME"] ?? "aino" }
    private var cloud = ""
    private var notes: [String] = []

    override func setUp() async throws {
        guard let url = env["KAIKU_STREAM_CLOUD"], !url.isEmpty else {
            throw XCTSkip("set KAIKU_STREAM_CLOUD to a local cloud seeded with the one person")
        }
        cloud = url
    }

    override func tearDown() async throws {
        guard let dir = env["KAIKU_SHOT_DIR"], !notes.isEmpty else { return }
        try? notes.joined(separator: "\n").appending("\n").write(toFile: dir + "/timing-mac.txt", atomically: true, encoding: .utf8)
    }

    // MARK: the service, as another device would talk to it

    private func call(_ method: String, _ path: String, _ body: [String: Any]? = nil) async throws -> (Int, [String: Any]) {
        var request = URLRequest(url: URL(string: cloud + path)!)
        request.httpMethod = method
        request.timeoutInterval = 10
        if let body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        return ((response as? HTTPURLResponse)?.statusCode ?? 0, (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:])
    }

    /// The model's tool call as a device forwards it (`POST /v1/companion/tool`). Returns the item's id.
    private func sayYes(on surface: String, to kind: String, when: String, said: String) async throws -> String {
        let (code, answer) = try await call("POST", "/v1/companion/tool", [
            "home_id": home, "surface": surface, "name": "agree_activity", "args": ["kind": kind, "said": said, "when": when],
        ])
        XCTAssertEqual(code, 200)
        XCTAssertEqual(answer["ok"] as? Bool, true, "\(answer)")
        return try XCTUnwrap((answer["result"] as? [String: Any])?["id"] as? String)
    }

    private func answer(_ id: String, _ answer: String, from surface: String) async throws {
        let (code, _) = try await call("POST", "/v1/me/agreed/answer?home_id=\(home)&surface=\(surface)", ["id": id, "answer": answer])
        XCTAssertEqual(code, 200)
    }

    /// Nothing open from an earlier run: the day starts clean.
    private func putEverythingAside() async throws {
        let listed = try await call("GET", "/v1/me/invitation?home_id=\(home)&surface=mac").1["agreed"] as? [[String: Any]] ?? []
        for item in listed where ["open", "started"].contains(item["state"] as? String ?? "") {
            try await answer(item["id"] as? String ?? "", "put_aside", from: "mac")
        }
    }

    private func until(_ seconds: TimeInterval = 5, _ what: String, file: StaticString = #filePath, line: UInt = #line,
                       _ done: () -> Bool) async {
        let end = Date().addingTimeInterval(seconds)
        while !done() && Date() < end { try? await Task.sleep(nanoseconds: 1_000_000) }
        XCTAssertTrue(done(), "timed out: \(what)", file: file, line: line)
    }

    private func ms(_ from: Date, _ to: Date = Date()) -> String { "\(Int((to.timeIntervalSince(from) * 1000).rounded())) ms" }

    private func note(_ line: String) { notes.append(line); print("LIVE " + line) }

    // MARK: the Mac

    func testAYesOnTheRobotReachesTheMacAtOnceNotifiesAndTurnsDone() async throws {
        try await putEverythingAside()

        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("live-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let pairing = Pairing(baseURL: try XCTUnwrap(URL(string: cloud)), homeID: home, token: nil)
        let app = AppModel(defaults: UserDefaults(suiteName: "live-" + UUID().uuidString)!, pairing: pairing, api: APIClient(pairing: pairing),
                           queue: OfflineQueue(url: dir.appendingPathComponent("e.json")), episodes: EpisodeOutbox(url: dir.appendingPathComponent("p.json")),
                           saveService: { _ in true })
        let now = Date()   // quiet hours that never include the moment the test runs
        app.quietFrom = now.addingTimeInterval(6 * 3600); app.quietTo = now.addingTimeInterval(7 * 3600); app.quietWeekend = false

        // The Mac with its main window not in front: the notification rule posts (into the probe, not the centre).
        let notifier = Notifier(defaults: UserDefaults(suiteName: "live-" + UUID().uuidString)!, center: nil)
        let probe = Notifier.AgreedProbe()
        notifier.agreedProbe = probe
        notifier.inFront = { false }
        notifier.surface = .mac
        let model = InvitationModel(isPhone: false, announce: { items, app in _ = await notifier.agreed(items, app: app) })
        var parts = HomeUpdates.Parts(offers: model, transport: URLSessionStreamTransport())
        parts.isPhone = false
        let updates = HomeUpdates(parts: parts)
        defer { updates.stop() }

        updates.start(app: app)
        await until(8, "the stream said hello") { updates.connected }
        try? await Task.sleep(nanoseconds: 400_000_000)   // the first read after hello
        XCTAssertNil(AgreedBoard.make(model.agreed, today: AppModel.dayKey(Date()), isPhone: false).card, "a clean day")
        let celebrations = app.celebration

        // 1. A yes on the robot: the item is on the Mac's list (what Today draws) and its notification is handed over.
        let said = Date()
        let id = try await sayYes(on: "robot", to: "lantern", when: "later", said: "Can we play the lantern game later today?")
        await until(5, "the item reached the Mac") { model.agreed.contains { $0.id == id && $0.state == .open } }
        let listed = Date()
        await until(5, "its notification") { probe.posted.count == 1 }
        note("mac: robot yes -> on the Mac's list after \(ms(said, listed)), notification handed over after \(ms(said)) (from the moment the tool call was sent)")
        let item = try XCTUnwrap(model.agreed.first { $0.id == id })
        let board = AgreedBoard.make(model.agreed, today: AppModel.dayKey(Date()), isPhone: false)
        XCTAssertEqual(board.card?.id, id, "it holds the card")
        XCTAssertTrue(item.startsHere(isPhone: false), "the Mac can start Lantern")
        XCTAssertEqual(item.surface, "robot")
        let request = probe.posted[0]
        XCTAssertEqual(request.identifier, NudgeScheduler.agreedID(id))
        XCTAssertEqual(request.content.body, item.text, "the service's sentence, unchanged")
        XCTAssertEqual(request.content.categoryIdentifier, NudgeScheduler.Category.agreed)
        XCTAssertEqual(request.content.userInfo["link"] as? String, "kaiku://play/lantern")
        XCTAssertNil(request.trigger, "at once")

        // 2. It is done on another device (a Lantern session from the phone): done here, its notification leaves,
        //    the completion moment plays once.
        let played = Date()
        let (code, taken) = try await call("POST", "/v1/events", ["events": [[
            "v": 1, "id": UUID().uuidString.lowercased(), "ts": ISO8601DateFormatter().string(from: Date()), "home_id": home,
            "source": "phone", "type": "obs.play_session", "sim": true,
            "payload": ["game": "lantern", "device": "phone", "duration_s": 60],
        ]]])
        XCTAssertEqual(code, 200, "\(taken)")
        XCTAssertEqual(taken["accepted"] as? Int, 1, "\(taken)")
        await until(5, "it turned done") { model.agreed.contains { $0.id == id && $0.state == .done } }
        note("mac: done on the phone -> done on the Mac after \(ms(played))")
        await until(3, "the notification left") { probe.removed.contains(NudgeScheduler.agreedID(id)) }
        XCTAssertEqual(app.celebration, celebrations + 1, "the completion moment, once")

        // 3. A yes said on this Mac: the item is here, and no notification is posted on the device it was said on.
        let here = try await sayYes(on: "mac", to: "breathe", when: "now", said: "I want to do the breathing now.")
        await until(5, "the Mac's own yes is listed") { model.agreed.contains { $0.id == here && $0.state == .open } }
        try? await Task.sleep(nanoseconds: 300_000_000)
        XCTAssertEqual(probe.posted.count, 1, "nothing posted for what was said on this device")

        // 4. Put aside on the phone: it leaves the Mac's card slot without anyone touching the Mac.
        let aside = Date()
        try await answer(here, "put_aside", from: "iphone")
        await until(5, "it left the Mac") { AgreedBoard.make(model.agreed, today: AppModel.dayKey(Date()), isPhone: false).card == nil }
        note("mac: put aside on the phone -> gone from the Mac after \(ms(aside))")
        XCTAssertEqual(app.celebration, celebrations + 1)
    }
}

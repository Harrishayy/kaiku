import AVFoundation
import UserNotifications
import XCTest
@testable import KaikuKit

// An activity agreed in one place shows up everywhere (D50): the shape, what an item is on this device, which
// item gets the card, the list's model, the notification rule and its bookkeeping, and the `agree_activity` tool
// going to the cloud from Talk, the check-in and the walk.

/// The local day as `AppModel.dayKey` writes it.
private let today: String = {
    let f = DateFormatter()
    f.calendar = Calendar(identifier: .gregorian); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "yyyy-MM-dd"
    return f.string(from: Date())
}()

private func item(_ id: String = "ag-1", kind: String = "lantern", name: String = "Lantern", state: AgreedActivity.State = .open,
                  surface: String = "robot", on: [String] = ["iphone", "mac"], opens: Bool = true, day: String = today,
                  at: String = "2026-11-14T12:05:00Z", stateAt: String? = nil) -> AgreedActivity {
    AgreedActivity(id: id, kind: kind, name: name, text: "At home you said yes to \(name). Ready when you are.", voice_key: "agreed.robot",
                   line: nil, surface: surface, at: at, day: day, when: "now", state: state, state_at: stateAt, on: on, opens_here: opens)
}

// MARK: shape

final class AgreedShapeTests: XCTestCase {
    func testMirrorsTheContract() throws {
        let schema = try json("contracts/schemas/api/AgreedActivity.schema.json") as! [String: Any]
        let props = schema["properties"] as! [String: Any]
        var full = item(stateAt: "2026-11-14T12:20:00Z")
        full.line = "A little light?"
        let sent = try JSONSerialization.jsonObject(with: JSONEncoder().encode(full)) as! [String: Any]
        XCTAssertEqual(Set(sent.keys), Set(props.keys), "every contract field is mirrored")
        XCTAssertTrue(Set(schema["required"] as! [String]).isSubset(of: Set(sent.keys)))
        XCTAssertEqual(Set((props["state"] as! [String: Any])["enum"] as! [String]), Set(AgreedActivity.State.allCases.map(\.rawValue)))

        let answer = try json("contracts/schemas/api/AgreedAnswer.schema.json") as! [String: Any]
        let answers = ((answer["properties"] as! [String: Any])["answer"] as! [String: Any])["enum"] as! [String]
        XCTAssertEqual(Set(answers), ["opened", "put_aside"], "there is no done answer: the activity's own observation does it")
        let body = try JSONSerialization.jsonObject(with: JSONEncoder().encode(AgreedAnswer(id: "ag-1", answer: .put_aside))) as? [String: String]
        XCTAssertEqual(body, ["id": "ag-1", "answer": "put_aside"])

        let response = try json("contracts/schemas/api/InvitationResponse.schema.json") as! [String: Any]
        XCTAssertNotNil((response["properties"] as! [String: Any])["agreed"])
        // The tool is the cloud's: a device forwards it.
        let registry = try json("contracts/schemas/companion_tools.json") as! [String: Any]
        let tool = try XCTUnwrap((registry["tools"] as? [String: Any])?["agree_activity"] as? [String: Any])
        XCTAssertEqual(tool["executor"] as? String, "cloud")
        XCTAssertFalse(ToolExecutor.isDevice("agree_activity"))
    }

    func testTheReadCarriesTheListAndAnItemThisBuildCannotReadIsLeftOut() throws {
        let text = #"""
        {"home_id":"h","invitation":null,"agreed":[
          {"id":"a1","kind":"lantern","name":"Lantern","text":"On your walk you said yes to Lantern. Ready when you are.","voice_key":"agreed.glasses",
           "line":null,"surface":"glasses","at":"2026-11-14T12:05:00Z","day":"2026-11-14","when":"later","state":"open","state_at":null,
           "on":["iphone","mac"],"opens_here":true},
          {"id":"a2","kind":"lantern","name":"Lantern","text":"x","voice_key":"k","surface":"robot","at":"2026-11-14T12:06:00Z","day":"2026-11-14","state":"snoozed"},
          {"id":"a3","kind":"hopscotch","name":"Hopscotch","text":"y","voice_key":"k","surface":"hologram","at":"2026-11-14T12:07:00Z","day":"2026-11-14","state":"done","state_at":"2026-11-14T12:20:00Z"}
        ]}
        """#
        let r = try JSONDecoder().decode(InvitationResponse.self, from: Data(text.utf8))
        XCTAssertEqual(r.agreed?.map(\.id), ["a1", "a3"], "a state from a newer service drops that item, not the answer")
        XCTAssertEqual(r.agreed?.first?.when, "later")
        XCTAssertEqual(r.agreed?.first?.opens_here, true)
        XCTAssertNil(r.agreed?.last?.opens_here, "defaults may be missing")
        XCTAssertEqual(r.agreed?.last?.kind, "hopscotch", "a kind or a surface from a newer service is kept as its word")
        // A service that does not know agreed activities yet.
        let old = try JSONDecoder().decode(InvitationResponse.self, from: Data(#"{"home_id":"h","invitation":null}"#.utf8))
        XCTAssertNil(old.agreed)
    }

    func testEveryActivityInTheRegistryOpensSomewhereOrSaysWhere() throws {
        let registry = try json("contracts/schemas/companion_tools.json") as! [String: Any]
        let activities = registry["activities"] as! [String]
        XCTAssertFalse(activities.isEmpty)
        for a in activities {
            let it = item(kind: a, name: a)
            switch a {
            case "drum":
                XCTAssertNil(it.route(isPhone: true)); XCTAssertNil(it.route(isPhone: false))
                XCTAssertFalse(it.startsHere(isPhone: true), "even if the cloud said this device opens it")
            case "walk", "light_hunt":
                XCTAssertEqual(it.route(isPhone: true), .walk)
                XCTAssertNil(it.route(isPhone: false), "no walk screen on the Mac")
                XCTAssertEqual(it.link(isPhone: true), "kaiku://walk")
            default:
                let route = try XCTUnwrap(it.route(isPhone: true), a)
                XCTAssertEqual(route, it.route(isPhone: false), a)
                // The notification's link opens the same screen as the card's button.
                let link = try XCTUnwrap(it.link(isPhone: true).flatMap(URL.init(string:)), a)
                XCTAssertEqual(DeepLink.parse(link), .route(route), a)
            }
            XCTAssertFalse(it.icon.isEmpty)
        }
        XCTAssertNil(item(kind: "hopscotch").route(isPhone: true))
    }

    func testStartNeedsAnOpenItemTheCloudSaysOpensHere() {
        XCTAssertTrue(item().startsHere(isPhone: true))
        XCTAssertFalse(item(opens: false).startsHere(isPhone: true), "the cloud says this device has no screen for it")
        XCTAssertFalse(item(state: .started).startsHere(isPhone: true))
        XCTAssertFalse(item(state: .done).startsHere(isPhone: true))
        XCTAssertFalse(item(kind: "walk", name: "a walk").startsHere(isPhone: false), "a walk on the Mac")
        var unknown = item(); unknown.opens_here = nil
        XCTAssertFalse(unknown.startsHere(isPhone: true), "not said: not offered")
    }

    func testTheWordsOnTheCard() {
        let utc = TimeZone(identifier: "UTC")!, fi = Locale(identifier: "fi_FI")
        XCTAssertEqual(item(surface: "robot").whereLine(timeZone: utc, locale: fi), "With the robot · 12.05")
        XCTAssertEqual(item(surface: "glasses").whereLine(timeZone: utc, locale: Locale(identifier: "en_GB")), "On a walk · 12:05")
        XCTAssertEqual(item(surface: "hologram", at: "nonsense").whereLine(timeZone: utc, locale: fi), "With Kaiku",
                       "a surface this build does not know and a time it cannot read")
        for s in ["robot", "glasses", "iphone", "mac", "web", "other"] {
            XCTAssertTrue(L10n.shared.has("agreed.where.\(s)", .en) && L10n.shared.has("agreed.where.\(s)", .fi), s)
        }
        for s in ["robot", "iphone", "mac"] { XCTAssertTrue(L10n.shared.has("agreed.on.\(s)", .en) && L10n.shared.has("agreed.on.\(s)", .fi), s) }

        // Where it can be started when not here: never this device, never the care team's web, a glasses walk is the iPhone's.
        XCTAssertEqual(item(kind: "walk", on: ["iphone", "glasses"], opens: false).elsewhereLine(here: .mac), "You can start it on your iPhone.")
        XCTAssertEqual(item(kind: "drum", on: ["robot"], opens: false).elsewhereLine(here: .iphone), "You can start it on the robot at home.")
        XCTAssertEqual(item(on: ["iphone", "mac", "web"], opens: false).elsewhereLine(here: .mac), "You can start it on your iPhone.")
        XCTAssertEqual(item(on: ["robot", "iphone", "mac"], opens: false).elsewhereLine(here: .web), "You can start it on the robot at home, your iPhone or your Mac.")
        XCTAssertEqual(item(on: [], opens: false).elsewhereLine(here: .mac), "It can't be started on this device.")

        // Started and done read calmly.
        XCTAssertEqual(item(state: .started).stateLine(), "Started")
        XCTAssertEqual(item(state: .done, stateAt: "2026-11-14T14:20:00Z").stateLine(timeZone: utc, locale: Locale(identifier: "en_GB")), "Done · 14:20")
        XCTAssertEqual(item(state: .done).stateLine(), "Done")
        XCTAssertEqual(item(state: .open).stateLine(), "Ready when you are")
        XCTAssertEqual(item(name: "a walk").title, "A walk")
        for state in AgreedActivity.State.allCases {
            let words = item(state: state).stateLine().lowercased()
            for never in ["score", "streak", "missed", "late", "overdue", "failed", "!"] { XCTAssertFalse(words.contains(never), words) }
        }
    }
}

// MARK: which item gets the card

final class AgreedBoardTests: XCTestCase {
    func testOneCardTheRestAsLines() {
        let items = [item("done-1", state: .done), item("walk", kind: "walk", name: "a walk", opens: false), item("lantern"),
                     item("seeds", kind: "seeds", name: "Seed shelf"), item("started", state: .started)]
        let mac = AgreedBoard.make(items, today: today, isPhone: false)
        XCTAssertEqual(mac.card?.id, "lantern", "the oldest open one this device can start, not the walk it cannot")
        XCTAssertEqual(mac.rows.map(\.id), ["walk", "seeds", "started"], "three lines; the done one is the first to go")
        XCTAssertEqual(mac.more, 1)
        XCTAssertEqual(AgreedBoard.make(items, today: today, isPhone: false, maxRows: 2).rows.map(\.id), ["walk", "seeds"])
        XCTAssertEqual(AgreedBoard.make(items, today: today, isPhone: false, maxRows: 2).more, 2)
        // Nothing this device can start: the oldest open one still gets the card, with no button.
        let only = AgreedBoard.make([item("drum", kind: "drum", name: "the drum", on: ["robot"], opens: false)], today: today, isPhone: true)
        XCTAssertEqual(only.card?.id, "drum")
        XCTAssertFalse(only.card!.startsHere(isPhone: true))
    }

    func testPutAsideAndAnotherDaysItemsAreNotShown() {
        let board = AgreedBoard.make([item("aside", state: .put_aside), item("yesterday", day: "2026-11-13"), item("done", state: .done)], today: today)
        XCTAssertNil(board.card, "nothing is open")
        XCTAssertEqual(board.rows.map(\.id), ["done"])
        XCTAssertTrue(AgreedBoard.make([item("aside", state: .put_aside)], today: today).isEmpty)
        XCTAssertTrue(AgreedBoard.make([], today: today).isEmpty)
        // The key moves when a state does, so the stack animates the change.
        XCTAssertNotEqual(AgreedBoard.make([item()], today: today).key, AgreedBoard.make([item(state: .started)], today: today).key)
    }

    func testOnlyAnItemSeenBeforeItWasDoneCountsAsFinishedNow() {
        let before = [item("a"), item("b", state: .started), item("c", state: .done), item("d", state: .put_aside)]
        let after = [item("a", state: .done), item("b", state: .done), item("c", state: .done), item("d", state: .done), item("new", state: .done)]
        XCTAssertEqual(AgreedBoard.finished(before: before, after: after), ["a", "b"],
                       "not the one already done, not one put aside, not one first seen done")
        XCTAssertEqual(AgreedBoard.finished(before: [], after: after), [])
    }
}

// MARK: the list's model

@MainActor final class AgreedModelTests: XCTestCase {
    private final class Service: @unchecked Sendable {
        var response: InvitationResponse?
        var settled: [(AgreedAnswer, CompanionSurface)] = []
        var reply: AgreedReply = .failed
        var announced: [[AgreedActivity]] = []
        /// Seconds the service takes to answer an answer.
        var slow: TimeInterval = 0
        var calls: InvitationService {
            InvitationService(fetch: { [self] _ in response }, answer: { _ in true },
                              settle: { [self] a, s in
                                  settled.append((a, s))
                                  if slow > 0 { try? await Task.sleep(nanoseconds: UInt64(slow * 1_000_000_000)) }
                                  return reply
                              })
        }
    }

    private func app(home: String = "home-a") -> AppModel {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("agreed-" + UUID().uuidString)
        try! FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let pairing = Pairing(baseURL: URL(string: "http://127.0.0.1:9")!, homeID: home, token: nil)
        return AppModel(defaults: UserDefaults(suiteName: UUID().uuidString)!, pairing: pairing, api: APIClient(pairing: pairing, timeout: 1),
                        queue: OfflineQueue(url: dir.appendingPathComponent("e.json")), episodes: EpisodeOutbox(url: dir.appendingPathComponent("p.json")),
                        saveService: { _ in true })
    }

    private func model(_ service: Service, phone: Bool = true) -> InvitationModel {
        InvitationModel(service: service.calls, isPhone: phone, announce: { items, _ in service.announced.append(items) })
    }

    func testTheReadFillsTheListAndTellsTheNotificationRules() async {
        let service = Service(), app = app()
        service.response = InvitationResponse(home_id: "home-a", invitation: nil, agreed: [item("a"), item("b", state: .done)])
        let model = model(service)
        let ok = await model.load(app: app)
        XCTAssertTrue(ok)
        XCTAssertEqual(model.agreed.map(\.id), ["a", "b"])
        XCTAssertEqual(service.announced.last?.map(\.id), ["a", "b"])
        // The service cannot be reached: what is shown stays, and the read says so.
        service.response = nil
        let again = await model.load(app: app)
        XCTAssertFalse(again)
        XCTAssertEqual(model.agreed.map(\.id), ["a", "b"])
        // An answer for another home is not this home's list.
        service.response = InvitationResponse(home_id: "someone-else", invitation: nil, agreed: [item("x")])
        await model.load(app: app)
        XCTAssertEqual(model.agreed.map(\.id), ["a", "b"])
    }

    func testStartReadsStartedAtOnceAndTheServiceHearsOpened() async {
        let service = Service(), app = app()
        service.response = InvitationResponse(home_id: "home-a", invitation: nil, agreed: [item("a")])
        service.reply = .taken(InvitationResponse(home_id: "home-a", invitation: nil, agreed: [item("a", state: .started, stateAt: "2026-11-14T12:10:00Z")]))
        let model = model(service)
        await model.load(app: app)
        await model.settle("a", .opened, app: app)
        XCTAssertEqual(service.settled.count, 1)
        XCTAssertEqual(service.settled.first?.0, AgreedAnswer(id: "a", answer: .opened))
        XCTAssertEqual(service.settled.first?.1, .iphone)
        XCTAssertEqual(model.agreed.first?.state, .started)
        XCTAssertEqual(model.agreed.first?.state_at, "2026-11-14T12:10:00Z", "the service's own answer is what stays")
        XCTAssertTrue(model.settling.isEmpty)
        XCTAssertEqual(service.announced.last?.first?.state, .started, "the notification rules hear it is no longer open")
    }

    func testNotNowLeavesAtOnceAndAnAnswerThatDidNotArriveIsSentAgain() async {
        let service = Service(), app = app()
        service.response = InvitationResponse(home_id: "home-a", invitation: nil, agreed: [item("a")])
        let model = model(service)
        await model.load(app: app)
        service.reply = .failed                                   // offline
        await model.settle("a", .put_aside, app: app)
        XCTAssertEqual(model.agreed.first?.state, .put_aside, "gone from the screen whether or not the service heard")
        XCTAssertTrue(AgreedBoard.make(model.agreed, today: today).isEmpty)
        // The next read: the service still says open (it never heard); the answer goes again first and the item
        // stays put aside here meanwhile.
        await model.load(app: app)
        XCTAssertEqual(service.settled.count, 2, "sent again before the read")
        XCTAssertEqual(model.agreed.first?.state, .put_aside)
        service.reply = .taken(nil)
        service.response = InvitationResponse(home_id: "home-a", invitation: nil, agreed: [item("a", state: .put_aside)])
        await model.load(app: app)
        XCTAssertEqual(service.settled.count, 3)
        await model.load(app: app)
        XCTAssertEqual(service.settled.count, 3, "delivered: not sent again")
    }

    func testAnIdThatIsNoLongerTodaysIsDroppedAndNothingOpensWhereThereIsNoScreen() async {
        let service = Service(), app = app()
        service.response = InvitationResponse(home_id: "home-a", invitation: nil,
                                              agreed: [item("a"), item("walk", kind: "walk", name: "a walk", opens: false)])
        let mac = model(service, phone: false)
        await mac.load(app: app)
        service.reply = .gone                                      // 404: the service no longer has it
        service.response = InvitationResponse(home_id: "home-a", invitation: nil,
                                              agreed: [item("walk", kind: "walk", name: "a walk", opens: false), item("fresh")])
        await mac.settle("a", .opened, app: app)
        XCTAssertEqual(mac.agreed.map(\.id), ["walk", "fresh"], "dropped, and the list read again")
        XCTAssertEqual(service.settled.last?.1, .mac)
        await mac.load(app: app)
        XCTAssertEqual(service.settled.count, 1, "refused for good: not sent again")
        // A walk has no screen on the Mac: nothing is reported as opened.
        await mac.settle("walk", .opened, app: app)
        XCTAssertEqual(service.settled.count, 1)
        XCTAssertEqual(mac.agreed.first { $0.id == "walk" }?.state, .open)
    }

    func testDoneElsewherePlaysTheCompletionMomentOnce() async {
        let service = Service(), app = app()
        service.response = InvitationResponse(home_id: "home-a", invitation: nil, agreed: [item("a"), item("old", state: .done)])
        let model = model(service)
        let start = app.celebration
        await model.load(app: app)
        XCTAssertEqual(app.celebration, start, "an item first seen done plays nothing")
        service.response = InvitationResponse(home_id: "home-a", invitation: nil, agreed: [item("a", state: .done, stateAt: "2026-11-14T14:20:00Z"), item("old", state: .done)])
        await model.load(app: app)
        XCTAssertEqual(app.celebration, start + 1, "done on another device")
        await model.load(app: app)
        await model.load(app: app)
        XCTAssertEqual(app.celebration, start + 1, "once")
    }

    func testAnActivityFinishedOnThisDeviceIsNotCelebratedTwice() async {
        let service = Service(), app = app()
        service.response = InvitationResponse(home_id: "home-a", invitation: nil, agreed: [item("a", state: .started)])
        let model = model(service)
        await model.load(app: app)
        app.celebrate()                                            // the game's own end, a second ago, on this device
        let after = app.celebration
        service.response = InvitationResponse(home_id: "home-a", invitation: nil, agreed: [item("a", state: .done)])
        await model.load(app: app)
        XCTAssertEqual(app.celebration, after)
        XCTAssertTrue(app.celebratedJustNow)
        app.celebrateUntil = Date().addingTimeInterval(-60)
        XCTAssertFalse(app.celebratedJustNow)
    }

    func testAnotherHomeNeverSeesThisHomesCards() async {
        let service = Service(), app = app()
        service.response = InvitationResponse(home_id: "home-a", invitation: nil, agreed: [item("a")])
        let model = model(service)
        await model.load(app: app)
        XCTAssertEqual(model.agreed.count, 1)
        // The answer for the old home arrives after the device was paired to another: it changes nothing.
        service.reply = .taken(InvitationResponse(home_id: "home-a", invitation: nil, agreed: [item("a", state: .started), item("a2")]))
        service.slow = 0.15
        let late = Task { await model.settle("a", .opened, app: app) }
        try? await Task.sleep(nanoseconds: 40_000_000)             // the answer is on its way
        XCTAssertEqual(service.settled.count, 1)
        await app.updatePairing(Pairing(baseURL: URL(string: "http://127.0.0.1:9")!, homeID: "home-b", token: nil))
        await late.value
        XCTAssertFalse(model.agreed.contains { $0.id == "a2" }, "the old home's late answer is not taken")
        service.slow = 0
        service.response = InvitationResponse(home_id: "home-a", invitation: nil, agreed: [item("a")])
        await model.load(app: app)
        XCTAssertTrue(model.agreed.isEmpty, "home a's answer is not home b's list")
        service.response = InvitationResponse(home_id: "home-b", invitation: nil, agreed: [item("b")])
        await model.load(app: app)
        XCTAssertEqual(model.agreed.map(\.id), ["b"])
        model.clearForPairingChange()
        XCTAssertTrue(model.agreed.isEmpty)
        await app.updatePairing(nil)
        await model.load(app: app)
        XCTAssertTrue(model.agreed.isEmpty)
        XCTAssertEqual(service.announced.last?.count, 0, "unpaired: the rules are told there is nothing, so a notification goes")
    }

    func testAStreamHintTakesACardAwayBeforeTheRead() async {
        let service = Service(), app = app()
        service.response = InvitationResponse(home_id: "home-a", invitation: nil, agreed: [item("a"), item("b")])
        let model = model(service)
        await model.load(app: app)
        await model.drop(agreed: "a", app: app)
        XCTAssertEqual(model.agreed.map(\.id), ["b"])
        XCTAssertEqual(service.announced.last?.map(\.id), ["b"])
    }

    func testTheAnswerRequestAsItLeavesTheDevice() async throws {
        URLProtocol.registerClass(AnswerStub.self)
        defer { URLProtocol.unregisterClass(AnswerStub.self) }
        AnswerStub.answer(200, forget: true)
        let api = APIClient(pairing: Pairing(baseURL: URL(string: "https://agreed.test")!, homeID: "home-a", token: "home-token"))
        let reply = await api.answerAgreed(AgreedAnswer(id: "ag-1", answer: .opened), surface: .iphone)
        guard case .taken(let fresh?) = reply else { return XCTFail("\(reply)") }
        XCTAssertEqual(fresh.agreed?.first?.state, .started)
        let seen = try XCTUnwrap(AnswerStub.all.first)
        let url = try XCTUnwrap(URLComponents(url: seen.url, resolvingAgainstBaseURL: false))
        XCTAssertEqual(seen.method, "POST"); XCTAssertEqual(url.path, "/v1/me/agreed/answer")
        XCTAssertEqual(Set(url.queryItems ?? []), [URLQueryItem(name: "home_id", value: "home-a"), URLQueryItem(name: "surface", value: "iphone")])
        XCTAssertEqual(seen.auth, "Bearer home-token")
        XCTAssertEqual(try JSONSerialization.jsonObject(with: seen.body) as? [String: String], ["id": "ag-1", "answer": "opened"])
        AnswerStub.answer(404)
        let gone = await api.answerAgreed(AgreedAnswer(id: "old", answer: .put_aside), surface: .mac)
        XCTAssertEqual(gone, .gone)
        AnswerStub.answer(503)
        let failed = await api.answerAgreed(AgreedAnswer(id: "ag-1", answer: .put_aside), surface: .mac)
        XCTAssertEqual(failed, .failed)
        let unpaired = await APIClient(pairing: nil).answerAgreed(AgreedAnswer(id: "x", answer: .opened), surface: .mac)
        XCTAssertEqual(unpaired, .failed)
    }
}

private final class AnswerStub: URLProtocol {
    static let lock = NSLock()
    nonisolated(unsafe) static var seen: [(method: String, url: URL, auth: String?, body: Data)] = []
    nonisolated(unsafe) static var status = 200
    static var all: [(method: String, url: URL, auth: String?, body: Data)] { lock.lock(); defer { lock.unlock() }; return seen }
    static func answer(_ code: Int, forget: Bool = false) { lock.lock(); defer { lock.unlock() }; status = code; if forget { seen = [] } }
    override class func canInit(with request: URLRequest) -> Bool { request.url?.host == "agreed.test" }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        var data = request.httpBody ?? Data()
        if let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable { let n = stream.read(&buffer, maxLength: buffer.count); if n <= 0 { break }; data.append(buffer, count: n) }
        }
        Self.lock.lock()
        Self.seen.append((request.httpMethod ?? "", request.url!, request.value(forHTTPHeaderField: "Authorization"), data))
        let status = Self.status
        Self.lock.unlock()
        let json = #"{"home_id":"home-a","invitation":null,"agreed":[{"id":"ag-1","kind":"lantern","name":"Lantern","text":"t","voice_key":"k","surface":"robot","at":"2026-11-14T12:05:00Z","day":"2026-11-14","when":"now","state":"started","state_at":"2026-11-14T12:10:00Z","on":["iphone","mac"],"opens_here":true}]}"#
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(json.utf8)); client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

// MARK: the notification rule

final class AgreedNotificationRuleTests: XCTestCase {
    private var cal: Calendar { var c = Calendar(identifier: .gregorian); c.timeZone = TimeZone(identifier: "Europe/Helsinki")!; return c }
    private func at(_ hour: Int, _ minute: Int = 0, day: Int = 11) -> Date {      // Wednesday 11 November 2026
        cal.date(from: DateComponents(year: 2026, month: 11, day: day, hour: hour, minute: minute))!
    }
    private func input(_ now: Date, inFront: Bool, items: [NudgeScheduler.AgreedItem], shown: Set<String> = [], posted: Set<String> = [],
                       paused: Bool = false) -> NudgeScheduler.AgreedInput {
        .init(now: now, calendar: cal, quiet: .init(), paused: paused, inFront: inFront, items: items, shown: shown, posted: posted)
    }
    private let open = NudgeScheduler.AgreedItem(id: "a", open: true)

    func testNotInFrontPostsOnceInFrontPostsNothing() {
        let behind = NudgeScheduler.agreed(input(at(14), inFront: false, items: [open]))
        XCTAssertEqual(behind, .init(post: ["a"], remove: [], shown: ["a"]))
        // In front: the card arriving is the notice, now and later.
        let front = NudgeScheduler.agreed(input(at(14), inFront: true, items: [open]))
        XCTAssertEqual(front, .init(post: [], remove: [], shown: ["a"]))
        // A second read of the same list (a resync, another event): nothing again.
        let again = NudgeScheduler.agreed(input(at(14, 1), inFront: false, items: [open], shown: ["a"], posted: ["a"]))
        XCTAssertEqual(again, .init())
        let seenInFront = NudgeScheduler.agreed(input(at(14, 1), inFront: false, items: [open], shown: ["a"]))
        XCTAssertEqual(seenInFront, .init(), "seen as a card: not notified about when the app goes behind")
        XCTAssertEqual(NudgeScheduler.agreedID("a"), "kaiku.agreed.a")
    }

    func testAYesSaidOnThisVeryDeviceDoesNotRingHere() {
        // Kaiku has just said "it's on your phone" in this conversation: the card is enough, behind or not.
        let mine = NudgeScheduler.AgreedItem(id: "a", open: true, here: true)
        XCTAssertEqual(NudgeScheduler.agreed(input(at(14), inFront: false, items: [mine])), .init(post: [], remove: [], shown: ["a"]))
        XCTAssertEqual(NudgeScheduler.agreed(input(at(14, 5), inFront: false, items: [mine], shown: ["a"])), .init(), "nor later")
        // The same yes on another device's screen does ring.
        XCTAssertEqual(NudgeScheduler.agreed(input(at(14), inFront: false, items: [open])).post, ["a"])
    }

    func testQuietHoursAndPauseShowTheCardButPostNothing() {
        XCTAssertEqual(NudgeScheduler.agreed(input(at(22), inFront: false, items: [open])), .init(), "22:00 is quiet")
        XCTAssertEqual(NudgeScheduler.agreed(input(at(21, 59), inFront: false, items: [open])).post, ["a"])
        XCTAssertEqual(NudgeScheduler.agreed(input(at(7, 59), inFront: false, items: [open])), .init())
        XCTAssertEqual(NudgeScheduler.agreed(input(at(8), inFront: false, items: [open])).post, ["a"])
        XCTAssertEqual(NudgeScheduler.agreed(input(at(9), inFront: false, items: [open])).post, ["a"], "a weekday morning")
        XCTAssertEqual(NudgeScheduler.agreed(input(at(9), inFront: false, items: [open]).with(day: at(9, day: 14))), .init(), "a weekend morning sleeps in")
        XCTAssertEqual(NudgeScheduler.agreed(input(at(14), inFront: false, items: [open], paused: true)), .init(), "pause everything")
        // Not posted and not counted as shown: a read after quiet hours, still open and not in front, posts it once.
        let later = NudgeScheduler.agreed(input(at(8, 5), inFront: false, items: [open]))
        XCTAssertEqual(later.post, ["a"])
        // In front during quiet hours it is still the card.
        XCTAssertEqual(NudgeScheduler.agreed(input(at(23), inFront: true, items: [open])).shown, ["a"])
    }

    func testWhatIsNoLongerOpenLosesItsNotification() {
        let closed = NudgeScheduler.AgreedItem(id: "a", open: false)        // started, done or put aside, here or elsewhere
        XCTAssertEqual(NudgeScheduler.agreed(input(at(14), inFront: false, items: [closed], shown: ["a"], posted: ["a"])).remove, ["a"])
        XCTAssertEqual(NudgeScheduler.agreed(input(at(14), inFront: true, items: [], shown: ["a"], posted: ["a", "b"])).remove, ["a", "b"], "removed from the list")
        XCTAssertEqual(NudgeScheduler.agreed(input(at(23), inFront: false, items: [closed], shown: ["a"], posted: ["a"], paused: true)).remove, ["a"],
                       "taking away is never held back")
        XCTAssertEqual(NudgeScheduler.agreed(input(at(14), inFront: false, items: [closed])).post, [], "a closed item is never posted")
        // Several at once: each on its own.
        let plan = NudgeScheduler.agreed(input(at(14), inFront: false,
                                               items: [open, .init(id: "b", open: true), .init(id: "c", open: false)], shown: ["a"], posted: ["a", "c"]))
        XCTAssertEqual(plan, .init(post: ["b"], remove: ["c"], shown: ["b"]))
    }
}

private extension NudgeScheduler.AgreedInput {
    func with(day now: Date) -> NudgeScheduler.AgreedInput { var copy = self; copy.now = now; return copy }
}

// MARK: the notification itself and its answers

@MainActor final class AgreedNotifierTests: XCTestCase {
    private final class Answers: @unchecked Sendable { var all: [(String, AgreedAnswer.Answer)] = [] }

    private func app(home: String = "home-a") -> AppModel {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("notice-" + UUID().uuidString)
        try! FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let pairing = Pairing(baseURL: URL(string: "http://127.0.0.1:9")!, homeID: home, token: nil)
        let app = AppModel(defaults: UserDefaults(suiteName: UUID().uuidString)!, pairing: pairing, api: APIClient(pairing: pairing, timeout: 1),
                           queue: OfflineQueue(url: dir.appendingPathComponent("e.json")), episodes: EpisodeOutbox(url: dir.appendingPathComponent("p.json")),
                           saveService: { _ in true })
        // Quiet hours that never include the moment the test runs.
        let now = Date()
        app.quietFrom = now.addingTimeInterval(6 * 3600); app.quietTo = now.addingTimeInterval(7 * 3600); app.quietWeekend = false
        return app
    }

    private func notifier(inFront: Bool, defaults: UserDefaults? = nil) -> (Notifier, Notifier.AgreedProbe, Answers) {
        let n = Notifier(defaults: defaults ?? UserDefaults(suiteName: "notice-" + UUID().uuidString)!, center: nil)
        let probe = Notifier.AgreedProbe(), answers = Answers()
        n.agreedProbe = probe
        n.inFront = { inFront }
        n.agreedAnswer = { id, answer, _ in answers.all.append((id, answer)) }
        return (n, probe, answers)
    }

    func testOneNotificationWithTheSentenceAndBothActions() async {
        let app = app()
        let (n, probe, _) = notifier(inFront: false)
        await n.agreed([item("ag-1")], app: app)
        XCTAssertEqual(probe.posted.count, 1)
        let c = probe.posted[0].content
        XCTAssertEqual(probe.posted[0].identifier, "kaiku.agreed.ag-1")
        XCTAssertNil(probe.posted[0].trigger, "at once")
        XCTAssertEqual(c.title, "Lantern")
        XCTAssertEqual(c.body, "At home you said yes to Lantern. Ready when you are.", "the cloud's sentence, unchanged")
        XCTAssertEqual(c.categoryIdentifier, NudgeScheduler.Category.agreed)
        XCTAssertEqual(c.userInfo["kind"] as? String, "agreed"); XCTAssertEqual(c.userInfo["agreed"] as? String, "ag-1")
        XCTAssertEqual(c.userInfo["home"] as? String, "home-a")
        XCTAssertEqual(c.userInfo["link"] as? String, "kaiku://play/lantern")
        XCTAssertNotEqual(c.interruptionLevel, .timeSensitive)
        // Read again (a resync, a second event, the foreground): still one.
        await n.agreed([item("ag-1")], app: app)
        await n.agreed([item("ag-1")], app: app)
        XCTAssertEqual(probe.posted.count, 1)
        XCTAssertTrue(probe.removed.isEmpty)
    }

    func testDedupeSurvivesARelaunch() async {
        let app = app()
        let defaults = UserDefaults(suiteName: "notice-" + UUID().uuidString)!
        let (first, probe, _) = notifier(inFront: false, defaults: defaults)
        await first.agreed([item("ag-1")], app: app)
        XCTAssertEqual(probe.posted.count, 1)
        let (second, probe2, _) = notifier(inFront: false, defaults: defaults)       // the app started again
        await second.agreed([item("ag-1")], app: app)
        XCTAssertTrue(probe2.posted.isEmpty)
        // ...and it still knows which notification is its own to take away.
        await second.agreed([item("ag-1", state: .done)], app: app)
        XCTAssertEqual(probe2.removed, ["kaiku.agreed.ag-1"])
    }

    func testABookSavedBeforeAgreedItemsExistedStillReads() throws {
        let defaults = UserDefaults(suiteName: "notice-" + UUID().uuidString)!
        defaults.set(Data(#"{"delivered":{},"offered":{},"resolved":["kaiku.invitation.2026-11-13"],"declinedDay":"2026-11-13","checkinMinutes":{"2026-11-13":600}}"#.utf8), forKey: "kaiku.notify")
        let n = Notifier(defaults: defaults, center: nil)
        let input = n.input(for: app(), now: Date())
        XCTAssertTrue(input.delivered.contains("kaiku.invitation.2026-11-13"), "what was known is kept")
    }

    func testInFrontNothingIsPostedNowOrLater() async {
        let app = app()
        let defaults = UserDefaults(suiteName: "notice-" + UUID().uuidString)!
        let (front, probe, _) = notifier(inFront: true, defaults: defaults)
        await front.agreed([item("ag-1")], app: app)
        XCTAssertTrue(probe.posted.isEmpty, "the card arriving is enough")
        let (behind, probe2, _) = notifier(inFront: false, defaults: defaults)
        await behind.agreed([item("ag-1")], app: app)
        XCTAssertTrue(probe2.posted.isEmpty, "already seen as a card")
        await behind.agreed([item("ag-1"), item("ag-2", kind: "breathe", name: "Breathe")], app: app)
        XCTAssertEqual(probe2.posted.map(\.identifier), ["kaiku.agreed.ag-2"], "a new one is its own")
    }

    func testQuietHoursPauseAndNoPermission() async {
        let app = app()
        let (n, probe, _) = notifier(inFront: false)
        let now = Date()
        app.quietFrom = now.addingTimeInterval(-3600); app.quietTo = now.addingTimeInterval(3600)
        await n.agreed([item("ag-1")], app: app)
        XCTAssertTrue(probe.posted.isEmpty, "quiet hours: the card is on Today, nothing rings")
        app.quietFrom = now.addingTimeInterval(6 * 3600); app.quietTo = now.addingTimeInterval(7 * 3600)
        app.pausedAll = true
        await n.agreed([item("ag-1")], app: app)
        XCTAssertTrue(probe.posted.isEmpty, "pause everything")
        app.pausedAll = false
        probe.allowed = false
        let refused = await n.agreed([item("ag-1")], app: app)
        XCTAssertTrue(probe.posted.isEmpty, "no permission: nothing is posted, and no new question is asked")
        XCTAssertEqual(refused, .init(), "and it does not count as shown")
        probe.allowed = true
        await n.agreed([item("ag-1")], app: app)
        XCTAssertEqual(probe.posted.count, 1, "once it can be posted, it is, once")
    }

    func testAYesOnThisDeviceIsSkippedAndAYesOnAWalkIsNot() async {
        let app = app()
        let (phone, probe, _) = notifier(inFront: false)
        phone.surface = .iphone
        // Said in Talk on this iPhone while it was locked: no notification on this iPhone.
        await phone.agreed([item("talk", surface: "iphone")], app: app)
        XCTAssertTrue(probe.posted.isEmpty)
        // Said on a walk (the glasses surface, though the conversation runs in this app): the locked phone rings.
        await phone.agreed([item("talk", surface: "iphone"), item("walk-yes", surface: "glasses")], app: app)
        XCTAssertEqual(probe.posted.map(\.identifier), ["kaiku.agreed.walk-yes"])
        // The Mac hears about both.
        let (mac, macProbe, _) = notifier(inFront: false)
        mac.surface = .mac
        await mac.agreed([item("talk", surface: "iphone"), item("walk-yes", surface: "glasses"), item("quick", surface: "mac")], app: app)
        XCTAssertEqual(macProbe.posted.map(\.identifier), ["kaiku.agreed.talk", "kaiku.agreed.walk-yes"], "not the one said to this Mac")
    }

    func testTheNotificationGoesWhenTheItemIsOver() async {
        for (state, list) in [(AgreedActivity.State.done, true), (.put_aside, true), (.started, true), (.open, false)] {
            let app = app()
            let (n, probe, _) = notifier(inFront: false)
            await n.agreed([item("ag-1")], app: app)
            XCTAssertEqual(probe.posted.count, 1)
            await n.agreed(list ? [item("ag-1", state: state)] : [], app: app)      // changed elsewhere, or removed
            XCTAssertEqual(probe.removed, ["kaiku.agreed.ag-1"], "\(state) \(list)")
            await n.agreed(list ? [item("ag-1", state: state)] : [], app: app)
            XCTAssertEqual(probe.removed.count, 1, "taken away once")
        }
        // Yesterday's item is not today's business.
        let app = app()
        let (n, probe, _) = notifier(inFront: false)
        await n.agreed([item("old", day: "2026-11-13")], app: app)
        XCTAssertTrue(probe.posted.isEmpty)
    }

    func testAnActivityWithNoScreenHereSaysWhereAndHasNoStart() async {
        let app = app()
        let (n, probe, answers) = notifier(inFront: false)
        await n.agreed([item("drum", kind: "drum", name: "the drum", on: ["robot"], opens: false)], app: app)
        let c = probe.posted[0].content
        XCTAssertEqual(c.categoryIdentifier, NudgeScheduler.Category.agreedElsewhere)
        XCTAssertEqual(c.title, "The drum")
        XCTAssertEqual(c.body, "At home you said yes to the drum. Ready when you are. You can start it on the robot at home.")
        // A tap opens Today (where the card is); nothing is reported as opened.
        let info = c.userInfo.reduce(into: [String: String]()) { if let k = $1.key as? String, let v = $1.value as? String { $0[k] = v } }
        let link = await n.handle(action: UNNotificationDefaultActionIdentifier, userInfo: info, app: app)
        XCTAssertEqual(link, URL(string: "kaiku://today"))
        await n.answering?.value
        XCTAssertTrue(answers.all.isEmpty)
    }

    func testStartAndNotNowDoWhatTheCardDoes() async {
        let app = app()
        let (n, probe, answers) = notifier(inFront: false)
        await n.agreed([item("ag-1")], app: app)
        let info = probe.posted[0].content.userInfo.reduce(into: [String: String]()) { if let k = $1.key as? String, let v = $1.value as? String { $0[k] = v } }

        let start = await n.handle(action: Notifier.Action.start, userInfo: info, app: app)
        XCTAssertEqual(start, URL(string: "kaiku://play/lantern"))
        XCTAssertTrue(app.open(start!)); XCTAssertEqual(app.deepLink, .lantern)
        await n.answering?.value
        XCTAssertEqual(answers.all.map(\.0), ["ag-1"]); XCTAssertEqual(answers.all.last?.1, .opened)

        let tap = await n.handle(action: UNNotificationDefaultActionIdentifier, userInfo: info, app: app)
        XCTAssertEqual(tap, start, "a tap on the notification is a Start")
        await n.answering?.value
        XCTAssertEqual(answers.all.count, 2)

        let aside = await n.handle(action: Notifier.Action.aside, userInfo: info, app: app)
        XCTAssertNil(aside, "Not now opens nothing")
        XCTAssertEqual(answers.all.last?.1, .put_aside, "and is answered before the handler returns")
        XCTAssertEqual(answers.all.count, 3)

        let dismissed = await n.handle(action: UNNotificationDismissActionIdentifier, userInfo: info, app: app)
        XCTAssertNil(dismissed)
        XCTAssertEqual(answers.all.count, 3, "swiping it away answers nothing")
    }

    func testAnAnswerForAPreviousHomeIsDropped() async {
        let app = app()
        let (n, probe, answers) = notifier(inFront: false)
        await n.agreed([item("ag-1")], app: app)
        let info = probe.posted[0].content.userInfo.reduce(into: [String: String]()) { if let k = $1.key as? String, let v = $1.value as? String { $0[k] = v } }
        await app.updatePairing(Pairing(baseURL: URL(string: "http://127.0.0.1:9")!, homeID: "home-b", token: nil))
        let link = await n.handle(action: Notifier.Action.start, userInfo: info, app: app)
        XCTAssertNil(link)
        _ = await n.handle(action: Notifier.Action.aside, userInfo: info, app: app)
        await n.answering?.value
        XCTAssertTrue(answers.all.isEmpty)
        // The new home's list does not have it: its notification is taken away.
        await n.agreed([], app: app)
        XCTAssertEqual(probe.removed, ["kaiku.agreed.ag-1"])
    }
}

// MARK: the tool goes to the cloud from every conversation on this device

private final class ToolAudio: ConversationAudioIO, @unchecked Sendable {
    var onPCM: ((Data) -> Void)?
    var onBuffer: ((AVAudioPCMBuffer) -> Void)?
    var onLevel: ((Float) -> Void)?
    var onPlaying: ((Bool) -> Void)?
    var onFailure: (() -> Void)?
    var isPlaying: Bool { false }
    func start() throws {}
    func stop() {}
    func setMic(_ on: Bool) {}
    func play(_ pcm: Data) {}
    func flush() {}
}

private final class ToolLine: ConversationTransport, @unchecked Sendable {
    let onEvent: @Sendable (LiveSession.Event) -> Void
    private let lock = NSLock()
    private var _responses: [(name: String, result: JSONValue)] = []
    var responses: [(name: String, result: JSONValue)] { lock.lock(); defer { lock.unlock() }; return _responses }
    init(_ onEvent: @escaping @Sendable (LiveSession.Event) -> Void) { self.onEvent = onEvent }
    func connect(token: String, session: CompanionSessionResponse, options: LiveSession.Options) { onEvent(.ready) }
    func close() {}
    func sendAudio(_ pcm: Data) {}
    func audioStreamEnd() {}
    func sendText(_ text: String) {}
    func sendContext(_ event: String) {}
    func respond(id: String, name: String, result: JSONValue) { lock.lock(); _responses.append((name, result)); lock.unlock() }
}

private final class ToolHTTP: URLProtocol {
    static let lock = NSLock()
    nonisolated(unsafe) static var calls: [[String: Any]] = []
    nonisolated(unsafe) static var refuse = false
    static var all: [[String: Any]] { lock.lock(); defer { lock.unlock() }; return calls }
    static func refusing(_ on: Bool, forget: Bool = false) { lock.lock(); defer { lock.unlock() }; refuse = on; if forget { calls = [] } }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        var data = request.httpBody ?? Data()
        if let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable { let n = stream.read(&buffer, maxLength: buffer.count); if n <= 0 { break }; data.append(buffer, count: n) }
        }
        let path = request.url!.path
        var json = #"{"accepted":1,"duplicates":0,"rejected":[]}"#
        if path.hasSuffix("session") {
            json = #"{"session_id":"s-1","model":"m","voice":"v","system_instruction":"i","tools":[{"name":"agree_activity","description":"d","parameters":{}}],"context_card":{"time_of_day":"afternoon"},"persona_version":"p","safety_phrases_version":"s","live_token":{"token":"t","expires_at":"2099-01-01T00:00:00Z","new_session_expires_at":"2099-01-01T00:00:00Z"},"walk":null}"#
        } else if path.hasSuffix("tool") {
            Self.lock.lock()
            Self.calls.append((try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:])
            let refuse = Self.refuse
            Self.lock.unlock()
            json = refuse
                ? #"{"ok":false,"name":"agree_activity","executor":"cloud","error":"Nothing was kept: that did not sound like a clear yes. Ask again if you are unsure.","result":{"agreed":false,"reason":"no_clear_yes"}}"#
                : #"{"ok":true,"name":"agree_activity","executor":"cloud","result":{"agreed":true,"id":"ag-1","kind":"lantern","name":"Lantern","when":"later","on":["iphone","mac"],"where":"your phone and your Mac","already":false,"listening":["iphone"]}}"#
        } else if path.hasSuffix("episode") {
            json = #"{"ok":true,"id":"s-1","transcript_stored":false}"#
        } else if path.hasSuffix("events"), request.httpMethod == "GET" { json = #"{"events":[]}"# }
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(json.utf8)); client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

@MainActor final class AgreeActivityToolTests: XCTestCase {
    private final class Lines: @unchecked Sendable { var all: [ToolLine] = []; var last: ToolLine { all[all.count - 1] } }
    private var wasMuted = false

    override func setUp() async throws {
        wasMuted = VoiceLines.shared.muted; VoiceLines.shared.muted = true
        ToolHTTP.refusing(false, forget: true)
    }
    override func tearDown() async throws { VoiceLines.shared.muted = wasMuted }

    private func app() -> (AppModel, UserDefaults, URL) {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("tool-" + UUID().uuidString)
        try! FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let pairing = Pairing(baseURL: URL(string: "https://tool.test")!, homeID: "tool-home", token: nil)
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [ToolHTTP.self]
        let defaults = UserDefaults(suiteName: "tool-" + UUID().uuidString)!
        defaults.set(true, forKey: "kaikuMute")
        let app = AppModel(defaults: defaults, pairing: pairing, api: APIClient(pairing: pairing, maxAttempts: 1, session: URLSession(configuration: config)),
                           queue: OfflineQueue(url: dir.appendingPathComponent("e.json")), episodes: EpisodeOutbox(url: dir.appendingPathComponent("p.json")),
                           saveService: { _ in true })
        return (app, defaults, dir)
    }

    private func wait(_ seconds: TimeInterval = 3, _ what: String, until done: () -> Bool) async {
        let end = Date().addingTimeInterval(seconds)
        while !done() && Date() < end { try? await Task.sleep(nanoseconds: 20_000_000) }
        XCTAssertTrue(done(), "timed out: \(what)")
    }

    /// The model calls the tool; what the cloud was asked and what the model was told.
    private func call(_ line: ToolLine, when: String = "later") async -> (asked: [String: Any]?, told: JSONValue?) {
        let before = line.responses.count, asked = ToolHTTP.all.count
        line.onEvent(.userText("Yes, let's do the lantern later.")); line.onEvent(.userTranscriptComplete)
        line.onEvent(.toolCall(id: UUID().uuidString, name: "agree_activity",
                               args: ["kind": .string("lantern"), "said": .string("Yes, let's do the lantern later."), "when": .string(when)]))
        await wait(3, "the tool's answer") { line.responses.count > before }
        return (ToolHTTP.all.count > asked ? ToolHTTP.all.last : nil, line.responses.last?.result)
    }

    private func check(_ r: (asked: [String: Any]?, told: JSONValue?), surface: String, file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(r.asked?["name"] as? String, "agree_activity", file: file, line: line)
        XCTAssertEqual(r.asked?["surface"] as? String, surface, file: file, line: line)
        XCTAssertEqual(r.asked?["home_id"] as? String, "tool-home", file: file, line: line)
        XCTAssertEqual(r.asked?["session_id"] as? String, "s-1", file: file, line: line)
        let args = r.asked?["args"] as? [String: Any]
        XCTAssertEqual(args?["kind"] as? String, "lantern", file: file, line: line)
        XCTAssertEqual(args?["said"] as? String, "Yes, let's do the lantern later.", file: file, line: line)
        XCTAssertEqual(args?["when"] as? String, "later", file: file, line: line)
        XCTAssertEqual(r.told?["where"], .string("your phone and your Mac"), "what Kaiku then says", file: file, line: line)
        XCTAssertEqual(r.told?["agreed"], .bool(true), file: file, line: line)
    }

    private func checkRefusal(_ told: JSONValue?, file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(told?["ok"], .bool(false), file: file, line: line)
        XCTAssertEqual(told?["agreed"], .bool(false), file: file, line: line)
        XCTAssertEqual(told?["error"], .string("Nothing was kept: that did not sound like a clear yes. Ask again if you are unsure."),
                       "the cloud's sentence reaches the model", file: file, line: line)
    }

    func testTalkForwardsItAndARefusalReachesTheModel() async {
        let (app, _, dir) = app()
        defer { try? FileManager.default.removeItem(at: dir) }
        let lines = Lines()
        let talk = TalkModel {
            Conversation(surface: .iphone, intent: .talk, audio: ToolAudio(), transport: { let l = ToolLine($0); lines.all.append(l); return l },
                         permission: { true }, localListener: false, purpose: .talk, typedWithoutMic: true)
        }
        await talk.start(app: app)
        await wait(3, "live") { talk.hasLive && !lines.all.isEmpty }
        check(await call(lines.last), surface: "iphone")
        XCTAssertNil(talk.activityCard, "nothing else on this screen: the card arrives on Today through the stream")
        ToolHTTP.refusing(true)
        checkRefusal(await call(lines.last).told)
        talk.screenDisappeared()
    }

    func testTheCheckInForwardsIt() async {
        let (app, _, dir) = app()
        defer { try? FileManager.default.removeItem(at: dir) }
        let lines = Lines()
        let talk = TalkModel(opening: CheckInChat.opening) {
            Conversation(surface: .mac, intent: .checkin, audio: ToolAudio(), transport: { let l = ToolLine($0); lines.all.append(l); return l },
                         permission: { true }, localListener: false, purpose: .check_in, typedWithoutMic: true)
        }
        let chat = CheckInChat(talk: talk)
        await chat.start(app: app)
        await wait(3, "live") { chat.hasLive && !lines.all.isEmpty }
        check(await call(lines.last), surface: "mac")
        ToolHTTP.refusing(true)
        checkRefusal(await call(lines.last).told)
        talk.screenDisappeared()
    }

    func testTheWalkForwardsIt() async {
        let (app, defaults, dir) = app()
        defer { try? FileManager.default.removeItem(at: dir) }
        let lines = Lines()
        let walk = WalkModel(defaults: defaults)
        walk.draftFile = dir.appendingPathComponent("walk.json")
        walk.makeConversation = { surface in
            Conversation(surface: surface, intent: .walk, audio: ToolAudio(), transport: { let l = ToolLine($0); lines.all.append(l); return l },
                         permission: { true }, localListener: false, purpose: .walk)
        }
        walk.begin(app: app, adapter: MockGlasses())        // with glasses the conversation is the glasses surface, run by the iPhone app
        await wait(6, "voice") { walk.talking && walk.companion?.phase == .listening && !lines.all.isEmpty }
        check(await call(lines.last), surface: "glasses")
        ToolHTTP.refusing(true)
        checkRefusal(await call(lines.last).told)
        await walk.end()
    }

    func testWhatTheModelIsToldAboutACloudTool() {
        let kept = CompanionToolResult(ok: true, name: "remember", executor: "cloud", result: .object(["action": .string("stored")]), error: nil, crisis: nil)
        XCTAssertEqual(kept.forModel, .object(["action": .string("stored")]), "an answer goes through as it is")
        XCTAssertEqual(CompanionToolResult(ok: true, name: "x", executor: nil, result: nil, error: nil, crisis: nil).forModel, .object(["ok": .bool(true)]))
        let refused = CompanionToolResult(ok: false, name: "remember", executor: "cloud", result: nil, error: "not stored: pass `said`", crisis: nil)
        XCTAssertEqual(refused.forModel, .object(["ok": .bool(false), "error": .string("not stored: pass `said`")]),
                       "a refusal without a result still says why")
        let own = CompanionToolResult(ok: false, name: "x", executor: nil, result: .object(["error": .string("its own")]), error: "the route's", crisis: nil)
        XCTAssertEqual(own.forModel["error"], .string("its own"), "a result that already says why keeps its words")
        XCTAssertEqual(CompanionToolResult(ok: false, name: "x", executor: nil, result: nil, error: nil, crisis: nil).forModel, .object(["ok": .bool(false)]))
    }
}

import XCTest
@testable import KaikuKit

// Today's invitation card: what a yes leads to, what is shown, and what goes to the service.

final class InvitationShapeTests: XCTestCase {
    private func make(_ kind: Invitation.Kind, activity: String? = nil, text: String = "Do you want to talk about the lake?") -> Invitation {
        Invitation(id: "inv-1", kind: kind, text: text, voice_key: "invite.talk_about", topic: kind == .talk_about ? "the lake" : nil, activity: activity)
    }

    func testMirrorsTheContract() throws {
        let schema = try json("contracts/schemas/api/Invitation.schema.json") as! [String: Any]
        let props = schema["properties"] as! [String: Any]
        let sent = try JSONSerialization.jsonObject(with: JSONEncoder().encode(make(.activity, activity: "breathe"))) as! [String: Any]
        XCTAssertTrue(Set(sent.keys).isSubset(of: Set(props.keys)))
        XCTAssertTrue(Set(schema["required"] as! [String]).isSubset(of: Set(sent.keys)))
        XCTAssertEqual(Set((props["kind"] as! [String: Any])["enum"] as! [String]), ["talk_about", "activity"])
        let answer = try json("contracts/schemas/api/InvitationAnswer.schema.json") as! [String: Any]
        let answers = ((answer["properties"] as! [String: Any])["answer"] as! [String: Any])["enum"] as! [String]
        XCTAssertEqual(Set(answers), ["yes", "not_now"])
        XCTAssertEqual(String(decoding: try JSONEncoder().encode(InvitationAnswer(id: "a", answer: .not_now)), as: UTF8.self).contains(#""answer":"not_now""#), true)
        // No invitation is an ordinary answer.
        let empty = try JSONDecoder().decode(InvitationResponse.self, from: Data(#"{"home_id":"h","invitation":null}"#.utf8))
        XCTAssertNil(empty.invitation)
        let full = try JSONDecoder().decode(InvitationResponse.self, from: Data(
            #"{"home_id":"h","invitation":{"id":"i1","kind":"talk_about","text":"Want to talk about the lake?","voice_key":"invite.talk_about","topic":"the lake","activity":null}}"#.utf8))
        XCTAssertEqual(full.invitation?.kind, .talk_about)
        XCTAssertEqual(full.invitation?.topic, "the lake")
    }

    func testEveryActivityInTheRegistryLeadsSomewhereOrIsLeftOutOnPurpose() throws {
        let reg = try json("contracts/schemas/companion_tools.json") as! [String: Any]
        let activities = reg["activities"] as! [String]
        XCTAssertFalse(activities.isEmpty)
        for a in activities {
            let inv = make(.activity, activity: a)
            if a == "drum" {
                XCTAssertNil(inv.destination(isPhone: true), "the drum is the robot's: no screen here")
                XCTAssertNil(inv.destination(isPhone: false))
            } else if a == "walk" || a == "light_hunt" {
                XCTAssertEqual(inv.destination(isPhone: true), .route(.walk))
                XCTAssertNil(inv.destination(isPhone: false), "no walk screen on the Mac")
            } else {
                XCTAssertNotNil(inv.destination(isPhone: true), a)
                XCTAssertEqual(inv.destination(isPhone: true), inv.destination(isPhone: false), a)
            }
            XCTAssertTrue(L10n.shared.has(inv.yesKey, .en) && L10n.shared.has(inv.yesKey, .fi), inv.yesKey)
        }
        XCTAssertEqual(make(.talk_about).destination(isPhone: false), .talk)
        XCTAssertEqual(make(.talk_about).yesKey, "invite.yes.talk")
        XCTAssertEqual(make(.activity, activity: "breathe").yesKey, "invite.yes.breathe")
        XCTAssertEqual(make(.activity, activity: "walk").yesKey, "invite.yes.walk")
        XCTAssertEqual(make(.activity, activity: "seeds").yesKey, "invite.yes.play")
        XCTAssertNil(make(.activity, activity: "karaoke").destination(isPhone: true), "a kind this build does not know is not shown")
        XCTAssertNil(make(.activity, activity: nil).destination(isPhone: true))
    }
}

@MainActor final class InvitationModelTests: XCTestCase {
    private final class Service: @unchecked Sendable {
        var response: InvitationResponse?
        var answers: [InvitationAnswer] = []
        var surfaces: [CompanionSurface] = []
        var accepts = true
        var calls: InvitationService {
            InvitationService(fetch: { [self] s in surfaces.append(s); return response },
                              answer: { [self] a in answers.append(a); return accepts })
        }
    }

    private func app(home: String = "home-a") -> AppModel {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("invite-" + UUID().uuidString)
        try! FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let pairing = Pairing(baseURL: URL(string: "http://127.0.0.1:9")!, homeID: home, token: nil)
        return AppModel(defaults: UserDefaults(suiteName: UUID().uuidString)!, pairing: pairing, api: APIClient(pairing: pairing, timeout: 1),
                        queue: OfflineQueue(url: dir.appendingPathComponent("e.json")), episodes: EpisodeOutbox(url: dir.appendingPathComponent("p.json")))
    }

    private func talk(_ id: String = "i1") -> Invitation {
        Invitation(id: id, kind: .talk_about, text: "You mentioned the lake. Want to talk about it?", voice_key: "invite.talk_about", topic: "the lake")
    }

    func testNoInvitationNoCard() async {
        let service = Service(), app = app()
        service.response = InvitationResponse(home_id: "home-a", invitation: nil)
        let model = InvitationModel(service: service.calls, isPhone: true)
        await model.load(app: app)
        XCTAssertNil(model.invitation)
        XCTAssertEqual(service.surfaces, [.iphone])
        let mac = InvitationModel(service: service.calls, isPhone: false)
        await mac.load(app: app)
        XCTAssertEqual(service.surfaces.last, .mac)
    }

    func testYesPostsTheAnswerAndSaysWhereToGo() async {
        let service = Service(), app = app()
        service.response = InvitationResponse(home_id: "home-a", invitation: talk())
        let model = InvitationModel(service: service.calls, isPhone: true)
        await model.load(app: app)
        XCTAssertEqual(model.invitation?.id, "i1")
        let destination = await model.answer(.yes, app: app)
        XCTAssertEqual(destination, .talk)
        XCTAssertEqual(service.answers, [InvitationAnswer(id: "i1", answer: .yes)])
        XCTAssertNil(model.invitation, "answered: the card is gone")
        // The service has not caught up yet and still returns it: it does not come back on this device.
        await model.load(app: app)
        XCTAssertNil(model.invitation)
    }

    func testNotNowPostsAndTheCardLeaves() async {
        let service = Service(), app = app()
        service.response = InvitationResponse(home_id: "home-a", invitation:
            Invitation(id: "i2", kind: .activity, text: "Shall we light the lantern now?", voice_key: "invite.activity", activity: "lantern"))
        let model = InvitationModel(service: service.calls, isPhone: true)
        await model.load(app: app)
        XCTAssertEqual(model.invitation?.destination(isPhone: true), .route(.lantern))
        let destination = await model.answer(.not_now, app: app)
        XCTAssertNil(destination, "a not-now goes nowhere")
        XCTAssertEqual(service.answers, [InvitationAnswer(id: "i2", answer: .not_now)])
        XCTAssertNil(model.invitation)
        let again = await model.answer(.not_now, app: app)
        XCTAssertNil(again); XCTAssertEqual(service.answers.count, 1, "answered once")
    }

    func testAnAnswerThatDidNotArriveIsSentAgain() async {
        let service = Service(), app = app()
        service.response = InvitationResponse(home_id: "home-a", invitation: talk("i3"))
        service.accepts = false
        let model = InvitationModel(service: service.calls, isPhone: true)
        await model.load(app: app)
        _ = await model.answer(.not_now, app: app)
        XCTAssertNil(model.invitation, "the card leaves even when the service is away")
        service.accepts = true
        await model.load(app: app)
        XCTAssertEqual(service.answers.map(\.id), ["i3", "i3"], "sent again before the next load")
        XCTAssertNil(model.invitation)
        await model.load(app: app)
        XCTAssertEqual(service.answers.count, 2, "and only until it arrived")
    }

    func testWhatCannotBeHonouredIsNotShown() async {
        let service = Service(), app = app()
        let model = InvitationModel(service: service.calls, isPhone: false)
        service.response = InvitationResponse(home_id: "home-a", invitation:
            Invitation(id: "w", kind: .activity, text: "A short walk?", voice_key: "invite.activity", activity: "walk"))
        await model.load(app: app)
        XCTAssertNil(model.invitation, "no walk screen on the Mac")
        service.response = InvitationResponse(home_id: "home-a", invitation:
            Invitation(id: "e", kind: .talk_about, text: "  ", voice_key: "invite.talk_about"))
        await model.load(app: app)
        XCTAssertNil(model.invitation, "no sentence, no card")
        service.response = InvitationResponse(home_id: "someone-else", invitation: talk("x"))
        await model.load(app: app)
        XCTAssertNil(model.invitation, "an answer for another home is refused")
    }

    func testUnreachableKeepsWhatIsShownAndAnotherHomeNeverSeesIt() async {
        let service = Service(), app = app()
        service.response = InvitationResponse(home_id: "home-a", invitation: talk("i5"))
        let model = InvitationModel(service: service.calls, isPhone: true)
        await model.load(app: app)
        service.response = nil
        await model.load(app: app)
        XCTAssertEqual(model.invitation?.id, "i5", "offline for a moment: the card stays")
        await app.updatePairing(Pairing(baseURL: URL(string: "http://127.0.0.1:9")!, homeID: "home-b", token: nil))
        await model.load(app: app)
        XCTAssertNil(model.invitation, "a new home starts without the old home's card")
        await app.updatePairing(nil)
        await model.load(app: app)
        XCTAssertNil(model.invitation)
    }
}

/// The two requests, as they leave the device (a registered URL protocol stands in for the service).
final class InvitationRequestTests: XCTestCase {
    private final class Stub: URLProtocol {
        static let lock = NSLock()
        nonisolated(unsafe) static var seen: [(method: String, url: URL, auth: String?, body: Data)] = []
        static var all: [(method: String, url: URL, auth: String?, body: Data)] { lock.lock(); defer { lock.unlock() }; return seen }
        override class func canInit(with request: URLRequest) -> Bool { request.url?.host == "invitation.test" }
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
            Self.lock.unlock()
            let json = request.httpMethod == "GET"
                ? #"{"home_id":"home-a","invitation":{"id":"i9","kind":"activity","text":"A few slow breaths?","voice_key":"invite.activity","activity":"breathe"}}"#
                : #"{"ok":true}"#
            client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: Data(json.utf8)); client?.urlProtocolDidFinishLoading(self)
        }
        override func stopLoading() {}
    }

    override func setUp() { URLProtocol.registerClass(Stub.self); Stub.lock.lock(); Stub.seen = []; Stub.lock.unlock() }
    override func tearDown() { URLProtocol.unregisterClass(Stub.self) }

    func testGetAndAnswerRequests() async throws {
        let api = APIClient(pairing: Pairing(baseURL: URL(string: "https://invitation.test")!, homeID: "home-a", token: "home-token"))
        let r = await api.invitation(surface: .iphone)
        XCTAssertEqual(r?.invitation?.activity, "breathe")
        let ok = await api.answerInvitation(InvitationAnswer(id: "i9", answer: .yes))
        XCTAssertTrue(ok)
        let seen = Stub.all
        XCTAssertEqual(seen.count, 2)
        let get = try XCTUnwrap(URLComponents(url: seen[0].url, resolvingAgainstBaseURL: false))
        XCTAssertEqual(seen[0].method, "GET"); XCTAssertEqual(get.path, "/v1/me/invitation")
        XCTAssertEqual(Set(get.queryItems ?? []), [URLQueryItem(name: "home_id", value: "home-a"), URLQueryItem(name: "surface", value: "iphone")])
        XCTAssertEqual(seen[0].auth, "Bearer home-token")
        let post = try XCTUnwrap(URLComponents(url: seen[1].url, resolvingAgainstBaseURL: false))
        XCTAssertEqual(seen[1].method, "POST"); XCTAssertEqual(post.path, "/v1/me/invitation/answer")
        XCTAssertEqual(post.queryItems, [URLQueryItem(name: "home_id", value: "home-a")])
        let body = try JSONSerialization.jsonObject(with: seen[1].body) as? [String: String]
        XCTAssertEqual(body, ["id": "i9", "answer": "yes"])
        let unpaired = APIClient(pairing: nil)
        let none = await unpaired.invitation(surface: .mac)
        XCTAssertNil(none)
        let refused = await unpaired.answerInvitation(InvitationAnswer(id: "x", answer: .yes))
        XCTAssertFalse(refused)
    }
}

import XCTest
@testable import KaikuKit

// The home stream (GET /v1/me/stream): the frame parser, the events, the reconnect and heartbeat rules, the
// connection loop on a stand-in transport and on URLSession, when the stream runs, and what each event sets off.

private func sse(_ event: String, _ data: String, id: String? = nil) -> String {
    (id.map { "id: \($0)\n" } ?? "") + "event: \(event)\ndata: \(data)\n\n"
}

private func hello(home: String = "home-a", beat: Double = 15, last: String? = nil, resync: Bool = false, replayed: Int = 0) -> String {
    let lastID = last.map { "\"\($0)\"" } ?? "null"
    return "retry: 2000\n" + sse("hello", #"{"home_id":"\#(home)","heartbeat_s":\#(beat),"last_id":\#(lastID),"resync":\#(resync),"replayed":\#(replayed)}"#)
}

private func agreed(_ id: String, _ state: String, n: String) -> String {
    sse("agreed", #"{"id":"\#(id)","kind":"lantern","state":"\#(state)","surface":"robot","when":"now","on":["iphone","mac"],"day":"2026-11-14"}"#, id: n)
}

// MARK: parser

final class SSEParserTests: XCTestCase {
    func testWholeFramesAsTheServiceWritesThem() {
        var p = SSEParser()
        let text = hello(last: "e1-3") + agreed("ag-1", "open", n: "e1-4") + "event: ping\ndata: {}\n\n"
        let frames = p.feed(Data(text.utf8))
        XCTAssertEqual(frames.map(\.event), ["hello", "agreed", "ping"])
        XCTAssertNil(frames[0].id, "hello carries no id")
        XCTAssertEqual(frames[1].id, "e1-4")
        XCTAssertNil(frames[2].id)
        XCTAssertEqual(p.lastEventID, "e1-4", "a frame without an id leaves the last one alone")
        XCTAssertEqual(p.retryMS, 2000)
        XCTAssertTrue(frames[1].data.contains(#""state":"open""#))
    }

    func testAnEventSplitAnywhereAcrossChunksIsTheSameEvent() {
        let text = hello() + agreed("ag-1", "open", n: "e1-1") + ": keep-alive\n\n" + sse("day", #"{"day":"2026-11-14","types":["obs.play_session"],"sources":["phone"]}"#, id: "e1-2")
        var whole = SSEParser()
        let expected = whole.feed(Data(text.utf8))
        XCTAssertEqual(expected.count, 3)
        let bytes = Array(text.utf8)
        for cut in 1..<bytes.count {
            var p = SSEParser()
            let got = p.feed(Data(bytes[..<cut])) + p.feed(Data(bytes[cut...]))
            XCTAssertEqual(got, expected, "cut at \(cut)")
            XCTAssertEqual(p.lastEventID, "e1-2")
        }
        var single = SSEParser()
        var got: [SSEFrame] = []
        for b in bytes { got += single.feed(Data([b])) }
        XCTAssertEqual(got, expected, "one byte at a time")
    }

    func testCommentsMultiLineDataAndLineEndings() {
        var p = SSEParser()
        let frames = p.feed(Data(": a comment\r\nevent: note\r\ndata: first\r\ndata:second\r\ndata\r\n\r\n".utf8))
        XCTAssertEqual(frames, [SSEFrame(event: "note", data: "first\nsecond\n")], "data lines join with a newline; a bare field is empty")
        // `\r` alone ends a line, and a `\r\n` cut between its two bytes is still one line end.
        var q = SSEParser()
        var got = q.feed(Data("data: a\r".utf8))
        got += q.feed(Data("\n\r".utf8))
        got += q.feed(Data("\ndata: b\r\r".utf8))
        XCTAssertEqual(got.map(\.data), ["a", "b"])
        XCTAssertEqual(got.map(\.event), ["message", "message"], "no event field: the default name")
    }

    func testIdsCountOnlyWithACompleteFrame() {
        var p = SSEParser()
        XCTAssertEqual(p.feed(Data("id: 7\nevent: day\ndata: {}\n".utf8)), [], "no blank line yet")
        XCTAssertNil(p.lastEventID, "the connection could still drop inside this frame")
        XCTAssertEqual(p.feed(Data("\n".utf8)).first?.id, "7")
        XCTAssertEqual(p.lastEventID, "7")
        // An id with a NUL is ignored; an id-only frame is not an event but its id counts.
        XCTAssertEqual(p.feed(Data("id: bad\u{0}id\ndata: x\n\n".utf8)).first?.id, nil)
        XCTAssertEqual(p.lastEventID, "7")
        XCTAssertEqual(p.feed(Data("id: 9\n\n".utf8)), [])
        XCTAssertEqual(p.lastEventID, "9")
        // Ids are opaque: kept exactly as sent.
        _ = p.feed(Data("id: 18f3a9c-12\ndata: x\n\n".utf8))
        XCTAssertEqual(p.lastEventID, "18f3a9c-12")
    }

    func testBOMUnknownFieldsRetryAndSplitCharacters() {
        var p = SSEParser()
        var data = Data([0xEF, 0xBB, 0xBF])
        data.append(Data("retry: abc\nretry: 1500\nfoo: bar\nevent: day\ndata: päivä ☀️\n\n".utf8))
        // cut inside the multi-byte sun
        let cut = data.count - 6
        let frames = p.feed(data.prefix(cut)) + p.feed(data.suffix(from: cut))
        XCTAssertEqual(frames, [SSEFrame(event: "day", data: "päivä ☀️")])
        XCTAssertEqual(p.retryMS, 1500, "only digits count")
    }
}

// MARK: events and rules

final class HomeStreamEventTests: XCTestCase {
    private func event(_ name: String, _ data: String) -> HomeStreamEvent? { HomeStreamEvent(SSEFrame(event: name, data: data)) }

    func testEveryKnownEventIsRead() {
        XCTAssertEqual(event("hello", #"{"home_id":"h","heartbeat_s":15.0,"last_id":"e-2","resync":true,"replayed":0}"#),
                       .hello(StreamHello(home_id: "h", heartbeat_s: 15, last_id: "e-2", resync: true, replayed: 0)))
        XCTAssertEqual(event("hello", #"{"home_id":"h","heartbeat_s":15}"#), .hello(StreamHello(home_id: "h", heartbeat_s: 15)),
                       "fields with a default may be missing")
        XCTAssertEqual(event("agreed", #"{"id":"a","kind":"walk","state":"removed","surface":"glasses","day":"2026-11-14"}"#),
                       .agreed(StreamAgreed(id: "a", kind: "walk", state: "removed", surface: "glasses", day: "2026-11-14")))
        XCTAssertEqual(event("day", #"{"day":"2026-11-14","types":["obs.outing"],"sources":["phone"]}"#),
                       .day(StreamDay(day: "2026-11-14", types: ["obs.outing"], sources: ["phone"])))
        XCTAssertEqual(event("invitation", #"{"id":"i1","state":"answered"}"#), .invitation(StreamInvitation(id: "i1", state: "answered")))
        XCTAssertEqual(event("ping", "{}"), .ping)
    }

    func testUnknownNamesAndUnreadableDataAreNoEvent() {
        XCTAssertNil(event("weather", #"{"rain":true}"#), "an event name from a newer service")
        XCTAssertNil(event("message", "hello"))
        XCTAssertNil(event("agreed", "not json"))
        XCTAssertNil(event("hello", #"{"heartbeat_s":15}"#), "a hello without a home is not one")
        // A state word from a newer service is still an event: it means "read the list again".
        XCTAssertNotNil(event("agreed", #"{"id":"a","kind":"lantern","state":"snoozed","surface":"robot","day":"2026-11-14"}"#))
    }

    func testMirrorsTheContract() throws {
        func check<T: Encodable>(_ name: String, _ value: T, file: StaticString = #filePath, line: UInt = #line) throws {
            let schema = try json("contracts/schemas/api/\(name).schema.json") as! [String: Any]
            let props = Set((schema["properties"] as! [String: Any]).keys)
            let sent = Set((try JSONSerialization.jsonObject(with: JSONEncoder().encode(value)) as! [String: Any]).keys)
            XCTAssertTrue(sent.isSubset(of: props), "\(name): \(sent.subtracting(props))", file: file, line: line)
            XCTAssertEqual(sent, props, "\(name): every contract field is mirrored", file: file, line: line)
            XCTAssertTrue(Set(schema["required"] as! [String]).isSubset(of: sent), name, file: file, line: line)
        }
        try check("StreamHello", StreamHello(home_id: "h", heartbeat_s: 15, last_id: "x", resync: false, replayed: 0))
        try check("StreamAgreed", StreamAgreed(id: "a", kind: "walk", state: "open", surface: "robot", when: "now", on: ["iphone"], day: "2026-11-14"))
        try check("StreamDay", StreamDay(day: "2026-11-14", types: [], sources: []))
        try check("StreamInvitation", StreamInvitation(id: "i", state: "answered"))
    }

    func testBackoffGrowsIsCappedAndJittered() {
        let b = StreamBackoff(base: 1, cap: 30, refusedFloor: 60)
        XCTAssertEqual(b.delay(attempt: 1, jitter: 1), 1)
        XCTAssertEqual(b.delay(attempt: 1, jitter: 0), 0.5, "up to half shorter, never zero")
        XCTAssertEqual(b.delay(attempt: 2, jitter: 1), 2)
        XCTAssertEqual(b.delay(attempt: 4, jitter: 1), 8)
        XCTAssertEqual(b.delay(attempt: 6, jitter: 1), 30, "capped")
        XCTAssertEqual(b.delay(attempt: 60, jitter: 1), 30, "a long outage does not overflow")
        XCTAssertEqual(b.delay(attempt: 0, jitter: 1), 1)
        for attempt in 1...10 {
            for j in stride(from: 0.0, through: 1.0, by: 0.25) {
                let d = b.delay(attempt: attempt, jitter: j)
                let full = min(30, pow(2, Double(attempt - 1)))
                XCTAssertGreaterThanOrEqual(d, full / 2); XCTAssertLessThanOrEqual(d, full)
            }
        }
        // A service that says "no such route" or "not allowed" is asked again only slowly.
        XCTAssertGreaterThanOrEqual(b.delay(attempt: 1, jitter: 0, refused: true), 45)
        XCTAssertLessThanOrEqual(b.delay(attempt: 1, jitter: 1, refused: true), 60)
        XCTAssertTrue(StreamEnd.refused(404).refusedForNow); XCTAssertTrue(StreamEnd.refused(401).refusedForNow)
        XCTAssertTrue(StreamEnd.wrongHome.refusedForNow)
        XCTAssertFalse(StreamEnd.refused(503).refusedForNow); XCTAssertFalse(StreamEnd.closed.refusedForNow)
        XCTAssertFalse(StreamEnd.silent.refusedForNow)
    }

    func testNoFrameForWellOverTwiceTheHeartbeatIsDead() {
        let w = StreamWatch(heartbeat: 15)
        let t = Date(timeIntervalSince1970: 1_000_000)
        XCTAssertFalse(w.isDead(lastFrame: t, now: t.addingTimeInterval(15)))
        XCTAssertFalse(w.isDead(lastFrame: t, now: t.addingTimeInterval(30)), "twice the heartbeat is still alive")
        XCTAssertFalse(w.isDead(lastFrame: t, now: t.addingTimeInterval(37)))
        XCTAssertTrue(w.isDead(lastFrame: t, now: t.addingTimeInterval(38)))
        XCTAssertEqual(StreamWatch(heartbeat: 4).limit, 10)
    }

    func testWhenTheStreamRuns() {
        func runs(paired: Bool = true, paused: Bool = false, phone: Bool, foreground: Bool = true, kept: Bool = false) -> Bool {
            StreamGate(paired: paired, paused: paused, isPhone: phone, foreground: foreground, keptAlive: kept).runs
        }
        // Mac: always, while paired and not paused (the app lives in the menu bar).
        XCTAssertTrue(runs(phone: false))
        XCTAssertTrue(runs(phone: false, foreground: false), "there is no background on the Mac")
        XCTAssertFalse(runs(paired: false, phone: false))
        XCTAssertFalse(runs(paused: true, phone: false))
        // iPhone: in the foreground, or in the background while a call or a walk keeps the app running.
        XCTAssertTrue(runs(phone: true))
        XCTAssertFalse(runs(phone: true, foreground: false), "in the background without a call it stops")
        XCTAssertTrue(runs(phone: true, foreground: false, kept: true))
        XCTAssertFalse(runs(paused: true, phone: true, foreground: false, kept: true), "pause everything wins")
        XCTAssertFalse(runs(paired: false, phone: true))
    }
}

// MARK: the connection on a stand-in transport

/// A service the test drives: every open is recorded with its request, and the test writes frames to it.
private final class FakeService: HomeStreamTransport, @unchecked Sendable {
    private let lock = NSLock()
    private var _requests: [URLRequest] = []
    private var bodies: [AsyncThrowingStream<Data, Error>.Continuation] = []
    /// Status per connection index (default 200); `nil` = the open itself fails.
    var status: @Sendable (Int) -> Int? = { _ in 200 }
    /// Written the moment a connection opens.
    var greeting: @Sendable (Int, URLRequest) -> String? = { _, _ in nil }

    var requests: [URLRequest] { lock.lock(); defer { lock.unlock() }; return _requests }
    var opens: Int { requests.count }

    private func register(_ request: URLRequest, _ continuation: AsyncThrowingStream<Data, Error>.Continuation) -> Int {
        lock.lock(); defer { lock.unlock() }
        _requests.append(request); bodies.append(continuation)
        return _requests.count - 1
    }

    func open(_ request: URLRequest) async throws -> (status: Int, body: AsyncThrowingStream<Data, Error>) {
        let (stream, continuation) = AsyncThrowingStream<Data, Error>.makeStream()
        let n = register(request, continuation)
        guard let code = status(n) else { throw URLError(.cannotConnectToHost) }
        if let text = greeting(n, request) { continuation.yield(Data(text.utf8)) }
        return (code, stream)
    }

    func send(_ text: String, on n: Int? = nil) {
        lock.lock(); let c = n.map { bodies[$0] } ?? bodies.last; lock.unlock()
        c?.yield(Data(text.utf8))
    }

    func close(_ n: Int? = nil) {
        lock.lock(); let c = n.map { bodies[$0] } ?? bodies.last; lock.unlock()
        c?.finish()
    }
}

private final class Seen: @unchecked Sendable {
    private let lock = NSLock()
    private var _events: [HomeStreamEvent] = []
    private var _notes: [HomeStreamClient.Note] = []
    var events: [HomeStreamEvent] { lock.lock(); defer { lock.unlock() }; return _events }
    var notes: [HomeStreamClient.Note] { lock.lock(); defer { lock.unlock() }; return _notes }
    func add(_ e: HomeStreamEvent) { lock.lock(); _events.append(e); lock.unlock() }
    func add(_ n: HomeStreamClient.Note) { lock.lock(); _notes.append(n); lock.unlock() }
    var ends: [StreamEnd] { notes.compactMap { if case .ended(let e) = $0 { return e }; return nil } }
    var waits: [TimeInterval] { notes.compactMap { if case .waiting(let w) = $0 { return w }; return nil } }
}

@MainActor
private func until(_ seconds: TimeInterval = 3, what: String = "", file: StaticString = #filePath, line: UInt = #line, _ done: () -> Bool) async {
    let end = Date().addingTimeInterval(seconds)
    while !done() && Date() < end { try? await Task.sleep(nanoseconds: 10_000_000) }
    XCTAssertTrue(done(), "timed out: \(what)", file: file, line: line)
}

final class HomeStreamClientTests: XCTestCase {
    private func timing(base: TimeInterval = 0.02, beat: TimeInterval = 15) -> HomeStreamClient.Timing {
        var t = HomeStreamClient.Timing()
        t.backoff = StreamBackoff(base: base, cap: 0.08, refusedFloor: 0.3)
        t.heartbeat = beat
        t.watchEvery = 0.02
        return t
    }

    private func client(_ service: FakeService, _ seen: Seen, cursor: StreamCursor = StreamCursor(), home: String = "home-a",
                        timing: HomeStreamClient.Timing? = nil, paired: @escaping @Sendable () -> Bool = { true }) -> HomeStreamClient {
        HomeStreamClient(homeID: home, cursor: cursor, transport: service, timing: timing ?? self.timing(), jitter: { 1 },
                         request: { _ in paired() ? URLRequest(url: URL(string: "https://stream.test/v1/me/stream?home_id=\(home)&surface=iphone")!) : nil },
                         onNote: { seen.add($0) }, onEvent: { seen.add($0) })
    }

    func testEventsArriveInOrderAndTheLastIdIsKept() async {
        let service = FakeService(), seen = Seen(), cursor = StreamCursor()
        service.greeting = { _, _ in hello(last: "e1-7") }
        let task = Task { await client(service, seen, cursor: cursor).run() }
        defer { task.cancel() }
        await until(what: "hello") { seen.events.count == 1 }
        guard case .hello(let h) = seen.events[0] else { return XCTFail("\(seen.events)") }
        XCTAssertEqual(h.resync, true, "a first connection has nothing to go on from: read everything")
        XCTAssertEqual(cursor.lastEventID, "e1-7", "and the next connection continues from the service's newest id")
        XCTAssertNil(service.requests[0].value(forHTTPHeaderField: "Last-Event-ID"))
        XCTAssertEqual(service.requests[0].value(forHTTPHeaderField: "Accept"), "text/event-stream")

        service.send(agreed("ag-1", "open", n: "e1-8"))
        service.send("event: ping\ndata: {}\n\n")
        service.send(sse("someday", #"{"x":1}"#, id: "e1-9"))            // unknown: skipped, its id still counts
        service.send(agreed("ag-1", "done", n: "e1-10"))
        await until(what: "four frames") { seen.events.count == 4 }
        XCTAssertEqual(seen.events.dropFirst().map { e -> String in
            switch e { case .agreed(let a): return "agreed:\(a.state)"; case .ping: return "ping"; default: return "other" }
        }, ["agreed:open", "ping", "agreed:done"])
        XCTAssertEqual(cursor.lastEventID, "e1-10")
        XCTAssertEqual(service.opens, 1)
    }

    func testAClosedConnectionComesBackWithLastEventID() async {
        let service = FakeService(), seen = Seen(), cursor = StreamCursor()
        service.greeting = { n, _ in n == 0 ? hello(last: nil) : hello(last: "e1-2", replayed: 1) + agreed("ag-2", "open", n: "e1-2") }
        let task = Task { await client(service, seen, cursor: cursor).run() }
        defer { task.cancel() }
        await until(what: "hello") { seen.events.count == 1 }
        XCTAssertNil(cursor.lastEventID, "the service has no event yet")
        service.send(agreed("ag-1", "open", n: "e1-1"))
        await until(what: "event") { seen.events.count == 2 }
        service.close()
        await until(what: "second connection") { service.opens == 2 && seen.events.count == 4 }
        XCTAssertEqual(service.requests[1].value(forHTTPHeaderField: "Last-Event-ID"), "e1-1", "sent back unchanged")
        guard case .hello(let again) = seen.events[2] else { return XCTFail() }
        XCTAssertNotEqual(again.resync, true, "the service could go on from our id: nothing to read again")
        XCTAssertEqual(cursor.lastEventID, "e1-2", "the replayed event moved it on")
        XCTAssertEqual(seen.ends.first, .closed)
        XCTAssertEqual(seen.waits.first ?? 9, 0.02, accuracy: 0.001, "a connection that worked starts the waits from the beginning")
    }

    func testAResyncHelloMovesTheCursorToTheServicesNewestId() async {
        let service = FakeService(), seen = Seen(), cursor = StreamCursor("old-epoch-41")
        service.greeting = { _, _ in hello(last: "new-epoch-3", resync: true) }
        let task = Task { await client(service, seen, cursor: cursor).run() }
        defer { task.cancel() }
        await until(what: "hello") { seen.events.count == 1 }
        XCTAssertEqual(service.requests[0].value(forHTTPHeaderField: "Last-Event-ID"), "old-epoch-41")
        guard case .hello(let h) = seen.events[0] else { return XCTFail() }
        XCTAssertEqual(h.resync, true)
        XCTAssertEqual(cursor.lastEventID, "new-epoch-3", "the old id means nothing to this service any more")
    }

    func testSilenceLongerThanTheHeartbeatAllowsReconnects() async {
        let service = FakeService(), seen = Seen()
        // The service says 0.05 s heartbeats and then says nothing: dead after 0.125 s.
        service.greeting = { _, _ in hello(beat: 0.05, last: "e1-1") }
        let task = Task { await client(service, seen).run() }
        defer { task.cancel() }
        await until(what: "the watchdog") { service.opens >= 2 }
        XCTAssertEqual(seen.ends.first, .silent)
        XCTAssertEqual(service.requests[1].value(forHTTPHeaderField: "Last-Event-ID"), "e1-1")
        // Pings keep a quiet connection alive.
        let live = FakeService(), seenLive = Seen()
        live.greeting = { _, _ in hello(beat: 0.2) }
        let second = Task { await client(live, seenLive).run() }
        defer { second.cancel() }
        for _ in 0..<16 {                                   // 0.8 s of quiet, a ping every 50 ms; dead would be 0.5 s
            try? await Task.sleep(nanoseconds: 50_000_000)
            live.send("event: ping\ndata: {}\n\n")
        }
        XCTAssertEqual(live.opens, 1, "\(seenLive.notes)")
        XCTAssertTrue(seenLive.ends.isEmpty)
    }

    func testFailuresBackOffAndARefusalIsAskedAgainOnlySlowly() async {
        let service = FakeService(), seen = Seen()
        service.status = { n in n < 3 ? nil : 200 }        // three opens fail, the fourth works
        service.greeting = { n, _ in n >= 3 ? hello() : nil }
        let task = Task { await client(service, seen).run() }
        await until(what: "the fourth attempt") { seen.events.count == 1 }
        task.cancel()
        XCTAssertEqual(seen.ends.prefix(3), [.failed, .failed, .failed])
        XCTAssertEqual(Array(seen.waits.prefix(3)), [0.02, 0.04, 0.08], "doubling up to the cap (jitter fixed at 1)")

        let old = FakeService(), seenOld = Seen()
        old.status = { _ in 404 }                           // a service without the route
        let second = Task { await client(old, seenOld).run() }
        await until(what: "refused") { !seenOld.waits.isEmpty }
        try? await Task.sleep(nanoseconds: 120_000_000)
        second.cancel()
        XCTAssertEqual(seenOld.ends.first, .refused(404))
        XCTAssertEqual(seenOld.waits.first ?? 0, 0.3, accuracy: 0.001)
        XCTAssertEqual(old.opens, 1, "not hammered")
    }

    func testAConnectionThatNeverCarriedAnythingDoesNotResetTheWaits() async {
        let service = FakeService(), seen = Seen()
        service.greeting = { _, _ in hello() }
        let task = Task { await client(service, seen).run() }
        defer { task.cancel() }
        // hello, then closed at once, three times over: a service that keeps turning us away.
        for n in 0..<3 {
            await until(what: "hello \(n)") { seen.events.count == n + 1 }
            service.close(n)
            await until(what: "end \(n)") { seen.waits.count == n + 1 }
        }
        XCTAssertEqual(Array(seen.waits.prefix(3)), [0.02, 0.04, 0.08])
    }

    func testAnotherHomesStreamIsNeverUsed() async {
        let service = FakeService(), seen = Seen(), cursor = StreamCursor()
        service.greeting = { _, _ in hello(home: "someone-else", last: "x-9") + agreed("ag-9", "open", n: "x-10") }
        let task = Task { await client(service, seen, cursor: cursor).run() }
        await until(what: "end") { !seen.ends.isEmpty }
        task.cancel()
        XCTAssertEqual(seen.ends.first, .wrongHome)
        XCTAssertTrue(seen.events.isEmpty, "not the hello, not what followed it")
        XCTAssertNil(cursor.lastEventID, "not even its ids")
    }

    func testCancellingStopsItAndUnpairedAsksNothing() async {
        let service = FakeService(), seen = Seen()
        service.greeting = { _, _ in hello() }
        let task = Task { await client(service, seen).run() }
        await until(what: "hello") { seen.events.count == 1 }
        task.cancel()
        await task.value
        service.send(agreed("late", "open", n: "e1-5"))
        try? await Task.sleep(nanoseconds: 80_000_000)
        XCTAssertEqual(seen.events.count, 1, "nothing after the stop")
        XCTAssertEqual(service.opens, 1, "and no reconnect")

        let none = FakeService(), seenNone = Seen()
        await client(none, seenNone, paired: { false }).run()
        XCTAssertEqual(none.opens, 0)
    }
}

// MARK: the connection on URLSession

/// A registered URL protocol that answers like the service: frames written in pieces, the connection kept open.
private final class StreamHTTP: URLProtocol {
    static let lock = NSLock()
    nonisolated(unsafe) static var seen: [URLRequest] = []
    nonisolated(unsafe) static var plan: [[String]] = []     // per connection: the pieces to write
    nonisolated(unsafe) static var closes: [Bool] = []       // per connection: end it after the pieces
    static var requests: [URLRequest] { lock.lock(); defer { lock.unlock() }; return seen }
    static func set(plan: [[String]], closes: [Bool]) {
        lock.lock(); defer { lock.unlock() }
        seen = []; Self.plan = plan; Self.closes = closes
    }
    private var stopped = false

    override class func canInit(with request: URLRequest) -> Bool { request.url?.host == "stream.test" }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.lock.lock()
        Self.seen.append(request)
        let n = Self.seen.count - 1
        let pieces = n < Self.plan.count ? Self.plan[n] : []
        let close = n < Self.closes.count ? Self.closes[n] : false
        Self.lock.unlock()
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: "HTTP/1.1",
                                                              headerFields: ["Content-Type": "text/event-stream"])!, cacheStoragePolicy: .notAllowed)
        nonisolated(unsafe) let me = self
        DispatchQueue.global().async {
            for piece in pieces {
                Thread.sleep(forTimeInterval: 0.015)
                if me.stopped { return }
                me.client?.urlProtocol(me, didLoad: Data(piece.utf8))
            }
            if close { me.client?.urlProtocolDidFinishLoading(me) }
        }
    }
    override func stopLoading() { stopped = true }
}

final class HomeStreamURLSessionTests: XCTestCase {
    func testTheRealTransportReadsPiecesAndComesBackWithItsId() async throws {
        let first = hello(last: nil) + agreed("ag-1", "open", n: "e1-1")
        let mid = first.index(first.startIndex, offsetBy: first.count / 2)
        StreamHTTP.set(plan: [[String(first[..<mid]), String(first[mid...]), "event: ping\ndata: {}\n\n"],
                              [hello(last: "e1-2", replayed: 1), agreed("ag-1", "done", n: "e1-2")]],
                       closes: [true, false])
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [StreamHTTP.self]
        let pairing = Pairing(baseURL: URL(string: "https://stream.test")!, homeID: "home-a", token: "home-token")
        let api = APIClient(pairing: pairing)
        let seen = Seen(), cursor = StreamCursor()
        var timing = HomeStreamClient.Timing()
        timing.backoff = StreamBackoff(base: 0.02, cap: 0.05)
        let client = HomeStreamClient(homeID: "home-a", cursor: cursor, transport: URLSessionStreamTransport(session: URLSession(configuration: config)),
                                      timing: timing, jitter: { 1 },
                                      request: { _ in await api.streamRequest(for: pairing, surface: .mac) },
                                      onNote: { seen.add($0) }, onEvent: { seen.add($0) })
        let task = Task { await client.run() }
        defer { task.cancel() }
        await until(5, what: "both connections") { seen.events.count >= 5 }
        let names = seen.events.map { e -> String in
            switch e {
            case .hello: return "hello"; case .agreed(let a): return "agreed:\(a.state)"; case .ping: return "ping"
            default: return "other"
            }
        }
        XCTAssertEqual(names, ["hello", "agreed:open", "ping", "hello", "agreed:done"])
        let requests = StreamHTTP.requests
        XCTAssertEqual(requests.count, 2)
        let url = try XCTUnwrap(URLComponents(url: try XCTUnwrap(requests[0].url), resolvingAgainstBaseURL: false))
        XCTAssertEqual(url.path, "/v1/me/stream")
        XCTAssertEqual(Set(url.queryItems ?? []), [URLQueryItem(name: "home_id", value: "home-a"), URLQueryItem(name: "surface", value: "mac")])
        XCTAssertEqual(requests[0].value(forHTTPHeaderField: "Authorization"), "Bearer home-token", "the same auth as the other /v1/me routes")
        XCTAssertEqual(requests[0].value(forHTTPHeaderField: "Accept"), "text/event-stream")
        XCTAssertNil(requests[0].value(forHTTPHeaderField: "Last-Event-ID"))
        XCTAssertEqual(requests[1].value(forHTTPHeaderField: "Last-Event-ID"), "e1-1")
        XCTAssertEqual(cursor.lastEventID, "e1-2")
        // Paired to something else: this home's stream is not asked for again.
        let other = await APIClient(pairing: Pairing(baseURL: URL(string: "https://stream.test")!, homeID: "home-b", token: nil))
            .streamRequest(for: pairing, surface: .mac)
        XCTAssertNil(other)
    }
}

// MARK: what each event sets off, and for which home

private final class DayHTTP: URLProtocol {
    static let lock = NSLock()
    nonisolated(unsafe) static var paths: [String] = []
    static func count(_ path: String, home: String) -> Int {
        lock.lock(); defer { lock.unlock() }
        return paths.filter { $0 == "\(path)?\(home)" }.count
    }
    static func reset() { lock.lock(); defer { lock.unlock() }; paths = [] }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let home = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)?.queryItems?.first { $0.name == "home_id" }?.value ?? ""
        Self.lock.lock(); Self.paths.append("\(request.url!.path)?\(home)"); Self.lock.unlock()
        let json = request.url!.path == "/v1/events" ? #"{"events":[]}"# : "{}"
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(json.utf8)); client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

@MainActor final class HomeUpdatesTests: XCTestCase {
    private final class Offers: @unchecked Sendable {
        private let lock = NSLock()
        private var _response: [String: InvitationResponse] = [:]
        private var _fetches = 0
        var reachable = true
        var fetches: Int { lock.lock(); defer { lock.unlock() }; return _fetches }
        func set(_ r: InvitationResponse) { lock.lock(); _response[r.home_id] = r; lock.unlock() }
        func service(home: @escaping @Sendable () async -> String?) -> InvitationService {
            InvitationService(fetch: { [self] _ in
                let asked = await home()
                return answer(asked)
            }, answer: { _ in true })
        }
        private func answer(_ home: String?) -> InvitationResponse? {
            lock.lock(); defer { lock.unlock() }
            _fetches += 1
            return reachable ? home.flatMap { _response[$0] } : nil
        }
    }

    private final class Where: @unchecked Sendable { var foreground = true; var kept = false }

    private func item(_ id: String, _ state: AgreedActivity.State = .open, home: String = "home-a") -> AgreedActivity {
        AgreedActivity(id: id, kind: "lantern", name: "Lantern", text: "At home you said yes to Lantern. Ready when you are.",
                       voice_key: "agreed.robot", surface: "robot", at: "2026-11-14T12:05:00Z", day: AppModel.dayKey(Date()),
                       when: "now", state: state, on: ["iphone", "mac"], opens_here: true)
    }

    private struct Rig {
        var updates: HomeUpdates
        var app: AppModel
        var service: FakeService
        var offers: Offers
        var model: InvitationModel
        var place: Where
        var dir: URL
    }

    private func rig(phone: Bool = false, home: String = "home-a") -> Rig {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("stream-" + UUID().uuidString)
        try! FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        DayHTTP.reset()
        let pairing = Pairing(baseURL: URL(string: "https://day.test")!, homeID: home, token: nil)
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [DayHTTP.self]
        let app = AppModel(defaults: UserDefaults(suiteName: "stream-" + UUID().uuidString)!, pairing: pairing,
                           api: APIClient(pairing: pairing, maxAttempts: 1, session: URLSession(configuration: config)),
                           queue: OfflineQueue(url: dir.appendingPathComponent("e.json")), episodes: EpisodeOutbox(url: dir.appendingPathComponent("p.json")),
                           saveService: { _ in true })
        let service = FakeService()
        service.greeting = { _, request in
            let asked = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)?.queryItems?.first { $0.name == "home_id" }?.value ?? ""
            return hello(home: asked, last: request.value(forHTTPHeaderField: "Last-Event-ID"))
        }
        let offers = Offers()
        let model = InvitationModel(service: offers.service(home: { [app] in await MainActor.run { app.pairing?.homeID } }), isPhone: phone)
        let place = Where()
        var timing = HomeStreamClient.Timing()
        timing.backoff = StreamBackoff(base: 0.02, cap: 0.05, refusedFloor: 0.2)
        timing.watchEvery = 0.05
        var parts = HomeUpdates.Parts(offers: model, transport: service)
        parts.timing = timing; parts.isPhone = phone
        parts.foreground = { place.foreground }; parts.keptAlive = { place.kept }
        parts.retryAfter = 0.05
        return Rig(updates: HomeUpdates(parts: parts), app: app, service: service, offers: offers, model: model, place: place, dir: dir)
    }

    private func settle(_ seconds: TimeInterval = 0.12) async { try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000)) }

    func testAnAgreedEventBringsTheCardWithoutTouchingAnything() async {
        let r = rig()
        defer { r.updates.stop(); try? FileManager.default.removeItem(at: r.dir) }
        r.offers.set(InvitationResponse(home_id: "home-a", invitation: nil, agreed: []))
        r.updates.start(app: r.app)
        await until(what: "hello") { r.updates.connected }
        await until(what: "the first read") { r.offers.fetches == 1 }
        XCTAssertTrue(r.model.agreed.isEmpty)
        XCTAssertEqual(DayHTTP.count("/v1/me", home: "home-a"), 0, "the first hello leaves /v1/me to the app's own launch read")
        let url = URLComponents(url: r.service.requests[0].url!, resolvingAgainstBaseURL: false)
        XCTAssertEqual(url?.path, "/v1/me/stream")
        XCTAssertEqual(Set(url?.queryItems ?? []), [URLQueryItem(name: "home_id", value: "home-a"), URLQueryItem(name: "surface", value: "mac")])

        // Said yes on the robot: the cloud stores it and says so on the stream.
        r.offers.set(InvitationResponse(home_id: "home-a", invitation: nil, agreed: [item("ag-1")]))
        let sent = Date()
        r.service.send(agreed("ag-1", "open", n: "e1-1"))
        await until(what: "the card") { r.model.agreed.map(\.id) == ["ag-1"] }
        XCTAssertLessThan(Date().timeIntervalSince(sent), 1)
        XCTAssertEqual(r.model.agreed.first?.state, .open)

        // Done on another device: the same card turns done and the completion moment plays once.
        let before = r.app.celebration
        r.offers.set(InvitationResponse(home_id: "home-a", invitation: nil, agreed: [item("ag-1", .done)]))
        r.service.send(agreed("ag-1", "done", n: "e1-2"))
        await until(what: "done") { r.model.agreed.first?.state == .done }
        XCTAssertEqual(r.app.celebration, before + 1)
        r.service.send(agreed("ag-1", "done", n: "e1-3"))               // said twice: still one moment
        await settle()
        XCTAssertEqual(r.app.celebration, before + 1)

        // Removed: the card leaves at once, also when the read that follows fails.
        r.offers.reachable = false
        r.service.send(agreed("ag-1", "removed", n: "e1-4"))
        await until(what: "gone") { r.model.agreed.isEmpty }
    }

    func testADayEventReadsTodayAgainAndBurstsShareARead() async {
        let r = rig()
        defer { r.updates.stop(); try? FileManager.default.removeItem(at: r.dir) }
        r.offers.set(InvitationResponse(home_id: "home-a", invitation: nil, agreed: []))
        r.updates.start(app: r.app)
        await until(what: "hello") { r.updates.connected }
        let day = sse("day", #"{"day":"2026-11-14","types":["obs.self_report"],"sources":["hub"]}"#, id: "e1-1")
        r.service.send(day)
        await until(what: "the read") { DayHTTP.count("/v1/me", home: "home-a") == 1 && DayHTTP.count("/v1/events", home: "home-a") == 1 }
        for n in 2...6 { r.service.send(sse("day", #"{"day":"2026-11-14"}"#, id: "e1-\(n)")) }
        await settle(0.4)
        let reads = DayHTTP.count("/v1/me", home: "home-a")
        XCTAssertGreaterThanOrEqual(reads, 2, "what arrived during a read gets a read after it")
        XCTAssertLessThanOrEqual(reads, 4, "but not one read per event")
        XCTAssertEqual(r.offers.fetches, 1, "a day event is not about the invitation")
    }

    func testInvitationAnsweredElsewhereTakesItsCardAway() async {
        let r = rig()
        defer { r.updates.stop(); try? FileManager.default.removeItem(at: r.dir) }
        let inv = Invitation(id: "i1", kind: .talk_about, text: "You mentioned the lake. Want to talk about it?", voice_key: "invite.talk_about", topic: "the lake")
        r.offers.set(InvitationResponse(home_id: "home-a", invitation: inv, agreed: []))
        r.updates.start(app: r.app)
        await until(what: "the card") { r.model.invitation?.id == "i1" }
        r.offers.reachable = false                                         // the card leaves on the event alone
        r.service.send(sse("invitation", #"{"id":"i1","state":"answered"}"#, id: "e1-1"))
        await until(what: "gone") { r.model.invitation == nil }
        r.offers.reachable = true
        await r.model.load(app: r.app)
        XCTAssertNil(r.model.invitation, "and it does not come back on this device")
    }

    func testAResyncReadsEverythingAgain() async {
        let r = rig()
        defer { r.updates.stop(); try? FileManager.default.removeItem(at: r.dir) }
        r.offers.set(InvitationResponse(home_id: "home-a", invitation: nil, agreed: []))
        r.updates.start(app: r.app)
        await until(what: "hello") { r.updates.connected && r.offers.fetches == 1 }
        r.service.send(agreed("ag-0", "open", n: "old-1"))
        await until(what: "an id to go on from") { r.offers.fetches == 2 }
        // The service restarts: the connection ends, and the next hello cannot go on from our id.
        r.service.greeting = { _, _ in hello(last: "new-4", resync: true) }
        r.offers.set(InvitationResponse(home_id: "home-a", invitation: nil, agreed: [item("ag-7")]))
        r.service.close()
        await until(what: "everything read again") {
            r.service.opens == 2 && r.model.agreed.map(\.id) == ["ag-7"] && DayHTTP.count("/v1/me", home: "home-a") >= 1
        }
        XCTAssertEqual(r.service.requests[1].value(forHTTPHeaderField: "Last-Event-ID"), "old-1")
    }

    func testPauseUnpairAndTheBackgroundStopItAndItComesBack() async {
        let r = rig(phone: true)
        defer { r.updates.stop(); try? FileManager.default.removeItem(at: r.dir) }
        r.offers.set(InvitationResponse(home_id: "home-a", invitation: nil, agreed: []))
        r.updates.start(app: r.app)
        await until(what: "hello") { r.updates.connected }
        XCTAssertEqual(URLComponents(url: r.service.requests[0].url!, resolvingAgainstBaseURL: false)?.queryItems?.first { $0.name == "surface" }?.value, "iphone")
        r.service.send(agreed("ag-1", "open", n: "e1-1"))
        await until(what: "read") { r.offers.fetches == 2 }

        // Pause everything: closed. Unpaused: open again, going on from the last id.
        r.app.pausedAll = true
        await until(what: "stopped by pause") { !r.updates.connected }
        XCTAssertFalse(r.updates.gate.runs)
        r.app.pausedAll = false
        await until(what: "back after pause") { r.updates.connected && r.service.opens == 2 }
        XCTAssertEqual(r.service.requests[1].value(forHTTPHeaderField: "Last-Event-ID"), "e1-1")

        // The background without a call: closed. During a call it stays; when the call ends, the next ping closes it.
        r.place.foreground = false
        r.updates.evaluate()
        XCTAssertFalse(r.updates.connected)
        r.place.foreground = true
        r.updates.evaluate()
        await until(what: "back in the foreground") { r.updates.connected && r.service.opens == 3 }
        r.place.kept = true; r.place.foreground = false
        r.updates.evaluate()
        XCTAssertTrue(r.updates.connected, "a call keeps the app running, and the stream with it")
        r.place.kept = false
        r.service.send("event: ping\ndata: {}\n\n")
        await until(what: "the call ended") { !r.updates.connected }
        let opens = r.service.opens
        await settle()
        XCTAssertEqual(r.service.opens, opens, "nothing reconnects while it should not run")

        // Unpaired: closed, and nothing is asked.
        r.place.foreground = true
        r.updates.evaluate()
        await until(what: "open again") { r.updates.connected }
        await r.app.updatePairing(nil)
        await until(what: "stopped by unpairing") { !r.updates.connected }
        let after = r.service.opens
        await settle()
        XCTAssertEqual(r.service.opens, after)
    }

    func testALateEventFromAPreviousHomeChangesNothing() async {
        let r = rig()
        defer { r.updates.stop(); try? FileManager.default.removeItem(at: r.dir) }
        r.offers.set(InvitationResponse(home_id: "home-a", invitation: nil, agreed: [item("ag-a")]))
        r.offers.set(InvitationResponse(home_id: "home-b", invitation: nil, agreed: []))
        r.updates.start(app: r.app)
        await until(what: "home a") { r.updates.connected && r.model.agreed.map(\.id) == ["ag-a"] }
        r.service.send(agreed("ag-a", "open", n: "a-1"))
        await until(what: "home a's id") { r.offers.fetches >= 2 }

        // Paired to another home: a new stream for it, starting from nothing.
        await r.app.updatePairing(Pairing(baseURL: URL(string: "https://day.test")!, homeID: "home-b", token: nil))
        await until(what: "home b") { r.service.opens == 2 && r.updates.connected }
        let second = URLComponents(url: r.service.requests[1].url!, resolvingAgainstBaseURL: false)
        XCTAssertEqual(second?.queryItems?.first { $0.name == "home_id" }?.value, "home-b")
        XCTAssertNil(r.service.requests[1].value(forHTTPHeaderField: "Last-Event-ID"), "home a's id means nothing for home b")
        await until(what: "home b read") { r.model.agreed.isEmpty && r.offers.fetches >= 3 }

        // The old home's connection still has something in flight: it is dropped.
        let fetches = r.offers.fetches
        let reads = DayHTTP.count("/v1/me", home: "home-b")
        r.service.send(agreed("ag-a", "done", n: "a-2"), on: 0)
        r.service.send(sse("day", #"{"day":"2026-11-14"}"#, id: "a-3"), on: 0)
        r.updates.take(.agreed(StreamAgreed(id: "ag-a", kind: "lantern", state: "open", surface: "robot", day: "2026-11-14")), generation: 1)
        r.updates.take(.day(StreamDay(day: "2026-11-14")), generation: 1)
        await settle()
        XCTAssertEqual(r.offers.fetches, fetches)
        XCTAssertEqual(DayHTTP.count("/v1/me", home: "home-b"), reads)
        XCTAssertTrue(r.model.agreed.isEmpty)
        XCTAssertEqual(r.updates.taken.filter { $0 == "agreed" }.count, 1, "only home a's own event, while it was paired")
    }

    func testABackgroundRefreshReadsTheListOnce() async {
        let r = rig(phone: true)
        defer { try? FileManager.default.removeItem(at: r.dir) }
        r.offers.set(InvitationResponse(home_id: "home-a", invitation: nil, agreed: [item("ag-1")]))
        await r.updates.catchUp(app: r.app)
        XCTAssertEqual(r.model.agreed.map(\.id), ["ag-1"])
        XCTAssertEqual(r.service.opens, 0, "no stream is opened for it")
    }
}

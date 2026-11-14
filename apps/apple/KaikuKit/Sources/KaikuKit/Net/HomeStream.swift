import Foundation

// The home stream: `GET /v1/me/stream?home_id=&surface=` (Server-Sent Events, kept open). The cloud sends a small
// event whenever something a screen should react to changes for this home: an activity was agreed in a
// conversation somewhere (`agreed`), new observations were stored (`day`), today's invitation was answered
// (`invitation`). Events carry ids and kinds only; the screen reads what it shows with the ordinary routes.
//
// This file is the connection: a pure frame parser, the events, the reconnect and heartbeat rules, and the loop
// that keeps one connection open (`HomeStreamClient`). When it runs and what each event refreshes is
// `HomeUpdates`. It is an ordinary data task: it opens no microphone and holds no background task, so it never
// keeps the phone awake by itself; when iOS suspends the app the connection simply ends.

// MARK: frames

/// One Server-Sent Events frame as it arrived: the event name (`message` when none was given), the data lines
/// joined with a newline, and the id the frame itself carried (nil when it had none).
public struct SSEFrame: Equatable, Sendable {
    public var event: String
    public var data: String
    public var id: String?
    public init(event: String = "message", data: String, id: String? = nil) {
        self.event = event; self.data = data; self.id = id
    }
}

/// Server-Sent Events parser (the WHATWG event-stream rules): bytes in, whole frames out. Pure: no clock, no
/// network. A frame may be split across chunks anywhere, also inside a UTF-8 character or between `\r` and `\n`.
/// Lines end with `\n`, `\r\n` or `\r`; a line starting with `:` is a comment; `data` lines of one frame are
/// joined with `\n`; a frame without data is not dispatched; an `id` counts only once its frame is complete.
public struct SSEParser: Sendable {
    private var line: [UInt8] = []
    private var afterCR = false
    private var first = true
    private var event = ""
    private var data: [String] = []
    private var pendingID: String?
    /// The id of the newest complete frame that carried one (frames without an id leave it alone).
    public private(set) var lastEventID: String?
    /// The server's `retry:` hint in milliseconds, when it sent one.
    public private(set) var retryMS: Int?

    public init() {}

    public mutating func feed(_ chunk: Data) -> [SSEFrame] {
        var out: [SSEFrame] = []
        for byte in chunk {
            if afterCR {
                afterCR = false
                if byte == 0x0A { continue }          // the `\n` of a `\r\n` whose `\r` already ended the line
            }
            if byte == 0x0A || byte == 0x0D {
                afterCR = byte == 0x0D
                if let frame = take() { out.append(frame) }
            } else {
                line.append(byte)
            }
        }
        return out
    }

    /// A finished line: a field of the frame being read, or (empty) the end of that frame.
    private mutating func take() -> SSEFrame? {
        var bytes = line
        line.removeAll(keepingCapacity: true)
        if first {
            first = false
            if bytes.starts(with: [0xEF, 0xBB, 0xBF]) { bytes.removeFirst(3) }   // a byte-order mark opens the stream
        }
        guard !bytes.isEmpty else { return dispatch() }
        guard bytes[0] != 0x3A else { return nil }                                // ":" a comment (keep-alive)
        let text = String(decoding: bytes, as: UTF8.self)
        var name = text, value = ""
        if let colon = text.firstIndex(of: ":") {
            name = String(text[..<colon])
            value = String(text[text.index(after: colon)...])
            if value.hasPrefix(" ") { value.removeFirst() }
        }
        switch name {
        case "event": event = value
        case "data": data.append(value)
        case "id": if !value.contains("\u{0}") { pendingID = value }
        case "retry": if !value.isEmpty, value.allSatisfy(\.isASCIIDigit) { retryMS = Int(value) }
        default: break                                                            // a field this client does not know
        }
        return nil
    }

    private mutating func dispatch() -> SSEFrame? {
        defer { event = ""; data = []; pendingID = nil }
        if let id = pendingID { lastEventID = id }
        guard !data.isEmpty else { return nil }
        return SSEFrame(event: event.isEmpty ? "message" : event, data: data.joined(separator: "\n"), id: pendingID)
    }
}

private extension Character {
    var isASCIIDigit: Bool { ("0"..."9").contains(self) }
}

// MARK: events

/// What the stream can say. A frame with a name this build does not know, or data it cannot read, is no event
/// (`nil`): it is skipped, and its id still counts as seen.
public enum HomeStreamEvent: Equatable, Sendable {
    case hello(StreamHello)
    case agreed(StreamAgreed)
    case day(StreamDay)
    case invitation(StreamInvitation)
    case ping

    public init?(_ frame: SSEFrame) {
        func read<T: Decodable>(_ type: T.Type) -> T? { try? JSONDecoder().decode(type, from: Data(frame.data.utf8)) }
        switch frame.event {
        case "hello": guard let v = read(StreamHello.self) else { return nil }; self = .hello(v)
        case "agreed": guard let v = read(StreamAgreed.self) else { return nil }; self = .agreed(v)
        case "day": guard let v = read(StreamDay.self) else { return nil }; self = .day(v)
        case "invitation": guard let v = read(StreamInvitation.self) else { return nil }; self = .invitation(v)
        case "ping": self = .ping
        default: return nil
        }
    }
}

// MARK: rules (pure)

/// How long to wait before the next connection attempt: doubling from `base` up to `cap`, each wait shortened by
/// up to half at random so a houseful of screens does not come back in the same instant. A service that answers
/// "no such route" or "not allowed" is asked again only slowly.
public struct StreamBackoff: Equatable, Sendable {
    public var base: TimeInterval
    public var cap: TimeInterval
    /// The shortest wait after an answer that will not get better by itself (401, 403, 404).
    public var refusedFloor: TimeInterval

    public init(base: TimeInterval = 1, cap: TimeInterval = 30, refusedFloor: TimeInterval = 60) {
        self.base = base; self.cap = cap; self.refusedFloor = refusedFloor
    }

    /// `attempt` counts failures in a row from 1; `jitter` is a random number in 0...1.
    public func delay(attempt: Int, jitter: Double, refused: Bool = false) -> TimeInterval {
        let n = Double(max(1, min(attempt, 16)) - 1)
        let full = min(cap, base * pow(2, n))
        let wait = full * (0.5 + 0.5 * min(1, max(0, jitter)))
        return refused ? max(wait, refusedFloor * (0.75 + 0.25 * min(1, max(0, jitter)))) : wait
    }
}

/// The heartbeat rule: the service pings every `heartbeat` seconds; no frame at all for well over twice that
/// long means the connection is dead, however open it looks.
public struct StreamWatch: Equatable, Sendable {
    public static let defaultHeartbeat: TimeInterval = 15
    public var heartbeat: TimeInterval
    public var factor: Double
    public init(heartbeat: TimeInterval = StreamWatch.defaultHeartbeat, factor: Double = 2.5) {
        self.heartbeat = heartbeat; self.factor = factor
    }
    public var limit: TimeInterval { heartbeat * factor }
    public func isDead(lastFrame: Date, now: Date) -> Bool { now.timeIntervalSince(lastFrame) > limit }
}

/// Why one connection ended.
public enum StreamEnd: Equatable, Sendable {
    case closed                 // the service or the network ended it
    case silent                 // no frame for longer than the heartbeat allows
    case refused(Int)           // an HTTP answer other than 200
    case failed                 // it never opened (no route, timeout, TLS)
    case wrongHome              // the hello was for another home: nothing from it may be used

    var refusedForNow: Bool {
        if case .refused(let code) = self { return code == 401 || code == 403 || code == 404 }
        return self == .wrongHome
    }
}

// MARK: transport

/// Opens the stream and hands back the status and the body as it arrives. The URLSession one is used in the app;
/// tests hand in their own.
public protocol HomeStreamTransport: Sendable {
    func open(_ request: URLRequest) async throws -> (status: Int, body: AsyncThrowingStream<Data, Error>)
}

public struct URLSessionStreamTransport: HomeStreamTransport {
    let session: URLSession

    public init(session: URLSession? = nil) {
        if let session { self.session = session } else {
            let cfg = URLSessionConfiguration.ephemeral
            cfg.timeoutIntervalForRequest = 60            // between two chunks; the heartbeat rule ends it sooner
            cfg.timeoutIntervalForResource = 24 * 3600
            cfg.waitsForConnectivity = false
            cfg.requestCachePolicy = .reloadIgnoringLocalCacheData
            cfg.httpAdditionalHeaders = ["Accept": "text/event-stream", "Cache-Control": "no-cache"]
            self.session = URLSession(configuration: cfg)
        }
    }

    public func open(_ request: URLRequest) async throws -> (status: Int, body: AsyncThrowingStream<Data, Error>) {
        let (bytes, response) = try await session.bytes(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        // Lines, not single bytes, go to the parser; every line end flushes, so nothing waits in here.
        let body = AsyncThrowingStream<Data, Error> { continuation in
            let reader = Task {
                var chunk = Data()
                do {
                    for try await byte in bytes {
                        chunk.append(byte)
                        if byte == 0x0A || byte == 0x0D { continuation.yield(chunk); chunk = Data() }
                    }
                    if !chunk.isEmpty { continuation.yield(chunk) }
                    continuation.finish()
                } catch { continuation.finish(throwing: error) }
            }
            continuation.onTermination = { _ in reader.cancel() }
        }
        return (status, body)
    }
}

// MARK: the connection

/// Keeps one stream open until its task is cancelled: connect, read frames, watch the heartbeat, and on any end
/// wait (backoff with jitter) and connect again with `Last-Event-ID`, so the service sends what was missed.
/// Events reach `onEvent` in order; it must not wait for the network itself (a slow handler would look like a
/// silent connection to the service).
public struct HomeStreamClient: Sendable {
    public struct Timing: Sendable {
        public var backoff = StreamBackoff()
        public var heartbeat = StreamWatch.defaultHeartbeat
        public var factor = 2.5
        /// How often the heartbeat is checked.
        public var watchEvery: TimeInterval = 2
        /// A connection is counted as having worked once it carried a frame after its hello, or stayed open this
        /// long: only then does the next failure start the waits from the beginning again.
        public var settled: TimeInterval = 10
        public init() {}
    }

    /// Notes for the caller between connections (a trace in tests and debug runs; no words, no ids).
    public enum Note: Equatable, Sendable {
        case connecting(lastEventID: String?)
        case ended(StreamEnd)
        case waiting(TimeInterval)
    }

    let request: @Sendable (_ lastEventID: String?) async -> URLRequest?
    let transport: HomeStreamTransport
    let homeID: String
    let timing: Timing
    let jitter: @Sendable () -> Double
    let onEvent: @Sendable (HomeStreamEvent) async -> Void
    let onNote: (@Sendable (Note) -> Void)?
    let cursor: StreamCursor

    /// - request: builds the GET for this home (nil = not paired any more: the loop ends). The loop adds
    ///   `Last-Event-ID` itself.
    /// - cursor: where the last seen id is kept, so a stream that is stopped and started again goes on from it.
    public init(homeID: String, cursor: StreamCursor = StreamCursor(), transport: HomeStreamTransport = URLSessionStreamTransport(),
                timing: Timing = Timing(), jitter: @escaping @Sendable () -> Double = { Double.random(in: 0...1) },
                request: @escaping @Sendable (_ lastEventID: String?) async -> URLRequest?,
                onNote: (@Sendable (Note) -> Void)? = nil,
                onEvent: @escaping @Sendable (HomeStreamEvent) async -> Void) {
        self.homeID = homeID; self.cursor = cursor; self.transport = transport; self.timing = timing
        self.jitter = jitter; self.request = request; self.onNote = onNote; self.onEvent = onEvent
    }

    /// Runs until cancelled (or until there is nothing to ask any more).
    public func run() async {
        var failures = 0
        while !Task.isCancelled {
            let last = cursor.lastEventID
            guard var req = await request(last), !Task.isCancelled else { return }
            if let last { req.setValue(last, forHTTPHeaderField: "Last-Event-ID") }
            req.setValue("text/event-stream", forHTTPHeaderField: "Accept")
            req.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
            onNote?(.connecting(lastEventID: last))
            let (end, worked) = await connection(req)
            guard !Task.isCancelled else { return }
            onNote?(.ended(end))
            failures = worked ? 1 : failures + 1
            let wait = timing.backoff.delay(attempt: failures, jitter: jitter(), refused: end.refusedForNow)
            onNote?(.waiting(wait))
            try? await Task.sleep(nanoseconds: UInt64(max(0, wait) * 1_000_000_000))
        }
    }

    /// One connection, from the request to its end. `worked`: it carried a frame after its hello or stayed open
    /// for `timing.settled`.
    private func connection(_ req: URLRequest) async -> (StreamEnd, worked: Bool) {
        let opened: (status: Int, body: AsyncThrowingStream<Data, Error>)
        do { opened = try await transport.open(req) } catch { return (.failed, false) }
        guard opened.status == 200 else { return (.refused(opened.status), false) }
        let beat = Beat(StreamWatch(heartbeat: timing.heartbeat, factor: timing.factor))
        let start = Date()
        let sent = req.value(forHTTPHeaderField: "Last-Event-ID")
        let end: StreamEnd = await withTaskGroup(of: StreamEnd.self) { group in
            group.addTask {
                var parser = SSEParser()
                do {
                    for try await chunk in opened.body {
                        for frame in parser.feed(chunk) {
                            beat.frame()
                            var event = HomeStreamEvent(frame)
                            if case .hello(var hello)? = event {
                                // Another home's stream must never be used, not even its ids.
                                guard hello.home_id == homeID else { return .wrongHome }
                                beat.hello(heartbeat: hello.heartbeat_s)
                                // Nothing to continue from (a first connection, or the service could not go on
                                // from our id): everything is read again, and the next connection continues
                                // from the newest id the service has.
                                if sent == nil { hello.resync = true }
                                if hello.resync == true { cursor.set(hello.last_id) }
                                event = .hello(hello)
                            } else {
                                beat.afterHello()
                            }
                            if let id = frame.id { cursor.set(id) }
                            if let event { await onEvent(event) }
                        }
                    }
                } catch {}
                return .closed
            }
            group.addTask {
                while !Task.isCancelled {
                    try? await Task.sleep(nanoseconds: UInt64(timing.watchEvery * 1_000_000_000))
                    if beat.isDead(now: Date()) { return .silent }
                }
                return .closed
            }
            let first = await group.next() ?? .closed
            group.cancelAll()
            return first
        }
        return (end, beat.carried || Date().timeIntervalSince(start) >= timing.settled)
    }
}

/// The last event id seen for one home on this device, kept across connections (and across a stop and a start
/// of the stream) and sent back unchanged. In memory only: after a relaunch everything is read again anyway.
public final class StreamCursor: @unchecked Sendable {
    private let lock = NSLock()
    private var id: String?
    public init(_ id: String? = nil) { self.id = id }
    public var lastEventID: String? { lock.lock(); defer { lock.unlock() }; return id }
    func set(_ new: String?) { lock.lock(); id = new; lock.unlock() }
}

/// The heartbeat of one connection, shared by its reader and its watchdog.
private final class Beat: @unchecked Sendable {
    private let lock = NSLock()
    private var watch: StreamWatch
    private var last = Date()
    private var after = false
    init(_ watch: StreamWatch) { self.watch = watch }
    func frame() { lock.lock(); last = Date(); lock.unlock() }
    func hello(heartbeat: Double) { lock.lock(); if heartbeat > 0 { watch.heartbeat = heartbeat }; lock.unlock() }
    func afterHello() { lock.lock(); after = true; lock.unlock() }
    var carried: Bool { lock.lock(); defer { lock.unlock() }; return after }
    func isDead(now: Date) -> Bool { lock.lock(); defer { lock.unlock() }; return watch.isDead(lastFrame: last, now: now) }
}

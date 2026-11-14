import Foundation
@preconcurrency import Network

// The "Kaiku bot" tab listens to the home robot's own message bus (the MQTT broker on the home network) while the
// tab is on screen. This file is the listening side and nothing else: a small MQTT 3.1.1 client that connects,
// subscribes to four topic filters and reads. It has no way to publish: there is no PUBLISH encoder here at all.
//
// What it may hear: `kaiku/v1/<home>/raw/#`, `/cmd/#`, `/obs/#`, `/health/#` (contracts/AGENTS.md → topics).
// What it never asks for: `kaiku/v1/<home>/audio/#` (the robot's microphone and speaker as binary frames, 50 a
// second) and `kaiku/v1/#`. A frame on an audio topic that arrives anyway (a broker that ignores the filters) is
// dropped before it is looked at (`BotTopics.allowed`).

// MARK: what to listen to (pure)

public enum BotTopics {
    /// The four message kinds the tab reads. Never `audio`, never `log`.
    public static let kinds = ["raw", "cmd", "obs", "health"]

    /// The subscription filters for a home (`+` when the paired home is not known).
    public static func filters(home: String?) -> [String] {
        let h = home.flatMap { valid($0) ? $0 : nil } ?? "+"
        return kinds.map { "kaiku/v1/\(h)/\($0)/#" }
    }

    /// A home id is one topic level: no wildcard, no separator (the same rule as the pairing's home id, looser).
    static func valid(_ home: String) -> Bool {
        !home.isEmpty && home.count <= 64 && !home.contains(where: { "/+#\u{0}".contains($0) || $0.isWhitespace })
    }

    /// Whether a topic that arrived is one this tab looks at: `kaiku/v1/<home>/<raw|cmd|obs|health>/…`, for the
    /// home it asked for. Anything else (an audio frame above all) is dropped unread.
    public static func allowed(_ topic: String, home: String?) -> Bool {
        let parts = topic.split(separator: "/", omittingEmptySubsequences: false)
        guard parts.count >= 5, parts[0] == "kaiku", parts[1] == "v1" else { return false }
        if let home, valid(home), parts[2] != home { return false }
        return kinds.contains(String(parts[3])) && !parts.contains("audio")
    }
}

/// "The robot's address" as typed: `host`, `host:port`, `[v6]:port`. Port 1883 when none is given.
public struct BotAddress: Equatable, Sendable, Codable {
    public var host: String
    public var port: UInt16
    public static let defaultPort: UInt16 = 1883

    public init(host: String, port: UInt16 = BotAddress.defaultPort) { self.host = host; self.port = port }

    public static func parse(_ raw: String) -> BotAddress? {
        var text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if let r = text.range(of: "://") { text = String(text[r.upperBound...]) }   // mqtt://host:port
        while text.hasSuffix("/") { text.removeLast() }
        guard !text.isEmpty, !text.contains(where: { $0.isWhitespace || "/?#@".contains($0) }) else { return nil }
        var host = text
        var port = defaultPort
        if text.hasPrefix("[") {                                   // [fe80::1]:1883
            guard let close = text.firstIndex(of: "]") else { return nil }
            host = String(text[text.index(after: text.startIndex)..<close])
            let rest = text[text.index(after: close)...]
            if !rest.isEmpty {
                guard rest.hasPrefix(":"), let p = UInt16(rest.dropFirst()), p > 0 else { return nil }
                port = p
            }
        } else if text.filter({ $0 == ":" }).count == 1, let colon = text.firstIndex(of: ":") {
            host = String(text[..<colon])
            guard let p = UInt16(text[text.index(after: colon)...]), p > 0 else { return nil }
            port = p
        }
        guard !host.isEmpty, host.count <= 253 else { return nil }
        return BotAddress(host: host.lowercased(), port: port)
    }

    public var text: String {
        let h = host.contains(":") ? "[\(host)]" : host
        return port == Self.defaultPort ? h : "\(h):\(port)"
    }

    /// The guess when nothing was typed: the paired companion service's host, but only when it is this computer
    /// or a private address on the home network (a cloud host is never the robot).
    public static func guess(serviceURL: URL?) -> BotAddress? {
        guard let host = serviceURL?.host?.lowercased(), isLocal(host) else { return nil }
        return BotAddress(host: host)
    }

    /// Loopback, RFC 1918, link-local, IPv6 unique-local / link-local, or a `.local` name.
    public static func isLocal(_ host: String) -> Bool {
        let h = host.lowercased()
        if h == "localhost" || h.hasSuffix(".local") || h == "::1" { return true }
        if h.hasPrefix("fe80:") || h.hasPrefix("fc") || h.hasPrefix("fd") { return h.contains(":") }
        let p = h.split(separator: ".").compactMap { UInt8($0) }
        guard p.count == 4, h.split(separator: ".").count == 4 else { return false }
        switch (p[0], p[1]) {
        case (127, _), (10, _), (192, 168), (169, 254): return true
        case (172, let b): return (16...31).contains(b)
        default: return false
        }
    }
}

// MARK: the wire (pure)

/// The packets this client sends. No PUBLISH: the tab never puts anything on the robot's bus.
public enum MQTTOut {
    public static func connect(clientID: String, keepAlive: UInt16, user: String? = nil, password: String? = nil) -> Data {
        var body = Data()
        body.append(string("MQTT"))
        body.append(4)                                             // protocol level 4 = 3.1.1
        var flags: UInt8 = 0x02                                    // clean session
        let user = user.flatMap { $0.isEmpty ? nil : $0 }
        if user != nil { flags |= 0x80 }
        if user != nil, let password, !password.isEmpty { flags |= 0x40 }
        body.append(flags)
        body.append(UInt8(keepAlive >> 8)); body.append(UInt8(keepAlive & 0xFF))
        body.append(string(clientID))
        if let user { body.append(string(user)) }
        if flags & 0x40 != 0, let password { body.append(string(password)) }
        return packet(0x10, body)
    }

    /// SUBSCRIBE at QoS 0 (requested), packet id `id`.
    public static func subscribe(id: UInt16, filters: [String]) -> Data {
        var body = Data([UInt8(id >> 8), UInt8(id & 0xFF)])
        for f in filters { body.append(string(f)); body.append(0) }
        return packet(0x82, body)
    }

    public static let pingreq = Data([0xC0, 0x00])
    public static let disconnect = Data([0xE0, 0x00])
    /// Answers to a QoS 1 / QoS 2 delivery (a broker sends at most the granted QoS 0, so these are only tolerance).
    public static func puback(_ id: UInt16) -> Data { Data([0x40, 0x02, UInt8(id >> 8), UInt8(id & 0xFF)]) }
    public static func pubrec(_ id: UInt16) -> Data { Data([0x50, 0x02, UInt8(id >> 8), UInt8(id & 0xFF)]) }
    public static func pubcomp(_ id: UInt16) -> Data { Data([0x70, 0x02, UInt8(id >> 8), UInt8(id & 0xFF)]) }

    static func string(_ s: String) -> Data {
        let utf = Data(s.utf8.prefix(65_535))
        return Data([UInt8(utf.count >> 8), UInt8(utf.count & 0xFF)]) + utf
    }

    static func packet(_ header: UInt8, _ body: Data) -> Data {
        var out = Data([header])
        out.append(remainingLength(body.count))
        out.append(body)
        return out
    }

    static func remainingLength(_ n: Int) -> Data {
        var n = n, out = Data()
        repeat {
            var byte = UInt8(n % 128)
            n /= 128
            if n > 0 { byte |= 0x80 }
            out.append(byte)
        } while n > 0
        return out
    }
}

/// A packet the broker sent.
public enum MQTTIn: Equatable, Sendable {
    case connack(code: UInt8)
    case suback(id: UInt16, granted: [UInt8])
    case publish(topic: String, payload: Data, qos: UInt8, id: UInt16?)
    case pubrel(id: UInt16)
    case pingresp
    /// Any other packet type: read and let go.
    case other(type: UInt8)
}

public enum MQTTError: Error, Equatable { case malformed(String), tooLarge }

/// Reads packets out of a TCP byte stream: bytes come in any pieces (a packet over many reads, many packets in one
/// read). Malformed input throws; it never crashes, and after a throw the connection is to be dropped.
public struct MQTTDecoder: Sendable {
    /// The largest packet this client accepts (an envelope is a few kB; the robot's audio frames are 640 bytes).
    public static let maxPacket = 1 << 20
    private var buffer = Data()
    public init() {}

    public var pending: Int { buffer.count }

    public mutating func feed(_ data: Data) throws -> [MQTTIn] {
        buffer.append(data)
        var out: [MQTTIn] = []
        while true {
            let bytes = [UInt8](buffer.prefix(5))
            guard bytes.count >= 2 else { break }
            var length = 0, multiplier = 1, used = 0, complete = false
            for i in 1..<min(bytes.count, 5) {
                let b = bytes[i]
                length += Int(b & 0x7F) * multiplier
                multiplier *= 128
                used = i
                if b & 0x80 == 0 { complete = true; break }
                if i == 4 { throw MQTTError.malformed("remaining length longer than four bytes") }
            }
            guard complete else { break }                        // the length itself is not all here yet
            guard length <= Self.maxPacket else { buffer.removeAll(); throw MQTTError.tooLarge }
            let total = 1 + used + length
            guard buffer.count >= total else { break }
            let start = buffer.startIndex
            let header = bytes[0]
            let body = Data(buffer[(start + 1 + used)..<(start + total)])
            buffer = Data(buffer[(start + total)...])
            out.append(try Self.parse(header: header, body: body))
        }
        return out
    }

    static func parse(header: UInt8, body: Data) throws -> MQTTIn {
        let b = [UInt8](body)
        func u16(_ i: Int) -> UInt16 { UInt16(b[i]) << 8 | UInt16(b[i + 1]) }
        switch header >> 4 {
        case 2:
            guard b.count == 2 else { throw MQTTError.malformed("connack") }
            return .connack(code: b[1])
        case 3:
            let qos = (header >> 1) & 0x03
            guard qos < 3 else { throw MQTTError.malformed("publish qos 3") }
            guard b.count >= 2 else { throw MQTTError.malformed("publish without topic") }
            let n = Int(u16(0))
            var at = 2 + n
            guard b.count >= at else { throw MQTTError.malformed("topic runs past the packet") }
            guard let topic = String(bytes: b[2..<at], encoding: .utf8) else { throw MQTTError.malformed("topic not utf-8") }
            var id: UInt16?
            if qos > 0 {
                guard b.count >= at + 2 else { throw MQTTError.malformed("publish without packet id") }
                id = u16(at); at += 2
            }
            return .publish(topic: topic, payload: Data(b[at...]), qos: qos, id: id)
        case 6:
            guard b.count >= 2 else { throw MQTTError.malformed("pubrel") }
            return .pubrel(id: u16(0))
        case 9:
            guard b.count >= 2 else { throw MQTTError.malformed("suback") }
            return .suback(id: u16(0), granted: Array(b[2...]))
        case 13:
            return .pingresp
        case 0, 15:
            throw MQTTError.malformed("reserved packet type")
        default:
            return .other(type: header >> 4)
        }
    }
}

// MARK: the connection

/// What the connection is doing, for the tab's first card.
public enum BotLinkState: Equatable, Sendable {
    case idle
    case connecting
    /// Connected and subscribed.
    case listening
    /// Nothing answered at that address (or it went away): trying again in a moment.
    case unreachable
    /// The broker answered and said no (wrong user or password, not allowed).
    case refused
}

/// One read-only connection to the home broker: connect, subscribe, read, keep alive, reconnect with backoff.
/// Callbacks come on the main actor. `stop()` sends DISCONNECT and closes; nothing reconnects after it.
@MainActor
public final class BotBusClient {
    public struct Timing: Sendable {
        public var keepAlive: UInt16 = 30
        public var connectTimeout: TimeInterval = 5
        public var backoff: [TimeInterval] = [1, 2, 4, 8, 15]
        public init() {}
    }

    public let address: BotAddress
    public let home: String?
    private let user: String?
    private let password: String?
    private let timing: Timing
    private let onState: @MainActor (BotLinkState) -> Void
    private let onMessage: @MainActor (String, Data) -> Void

    private let queue = DispatchQueue(label: "fi.kaiku.botbus")
    private var connection: NWConnection?
    private var decoder = MQTTDecoder()
    private var stopped = true
    private var attempt = 0
    private var generation = 0
    private var lastHeard = Date()
    private var pinger: Task<Void, Never>?
    private var retry: Task<Void, Never>?
    private var timeout: Task<Void, Never>?
    private(set) public var state: BotLinkState = .idle { didSet { if state != oldValue { onState(state) } } }

    public init(address: BotAddress, home: String?, user: String? = nil, password: String? = nil, timing: Timing = Timing(),
                onState: @escaping @MainActor (BotLinkState) -> Void, onMessage: @escaping @MainActor (String, Data) -> Void) {
        self.address = address; self.home = home; self.user = user; self.password = password; self.timing = timing
        self.onState = onState; self.onMessage = onMessage
    }

    public func start() {
        guard stopped else { return }
        stopped = false
        attempt = 0
        open()
    }

    public func stop() {
        stopped = true
        retry?.cancel(); retry = nil
        close(sayGoodbye: true)
        state = .idle
    }

    private func open() {
        guard !stopped else { return }
        generation += 1
        let mine = generation
        decoder = MQTTDecoder()
        state = .connecting
        guard let port = NWEndpoint.Port(rawValue: address.port) else { state = .unreachable; return }
        let tcp = NWProtocolTCP.Options()
        tcp.connectionTimeout = Int(timing.connectTimeout)
        tcp.noDelay = true
        let c = NWConnection(host: NWEndpoint.Host(address.host), port: port, using: NWParameters(tls: nil, tcp: tcp))
        connection = c
        c.stateUpdateHandler = { [weak self] s in
            Task { @MainActor in self?.changed(s, generation: mine) }
        }
        c.start(queue: queue)
        timeout?.cancel()
        timeout = Task { [weak self, timing] in
            try? await Task.sleep(nanoseconds: UInt64((timing.connectTimeout + 2) * 1_000_000_000))
            guard !Task.isCancelled, let self, self.generation == mine, self.state == .connecting else { return }
            self.dropped(generation: mine, refused: false)
        }
    }

    private func changed(_ s: NWConnection.State, generation mine: Int) {
        guard mine == generation, !stopped, let c = connection else { return }
        switch s {
        case .ready:
            lastHeard = Date()
            let id = "kaiku-app-" + UUID().uuidString.prefix(8).lowercased()
            send(MQTTOut.connect(clientID: id, keepAlive: timing.keepAlive, user: user, password: password))
            read(c, generation: mine)
        case .failed, .cancelled:
            dropped(generation: mine, refused: false)
        case .waiting:
            dropped(generation: mine, refused: false)       // no route / refused: try again later, quietly
        default:
            break
        }
    }

    private func read(_ c: NWConnection, generation mine: Int) {
        c.receive(minimumIncompleteLength: 1, maximumLength: 65_536) { [weak self] data, _, done, error in
            Task { @MainActor in
                guard let self, mine == self.generation, !self.stopped else { return }
                if let data, !data.isEmpty { self.take(data, generation: mine) }
                guard mine == self.generation else { return }
                if done || error != nil { self.dropped(generation: mine, refused: false); return }
                self.read(c, generation: mine)
            }
        }
    }

    private func take(_ data: Data, generation mine: Int) {
        let packets: [MQTTIn]
        do { packets = try decoder.feed(data) } catch { dropped(generation: mine, refused: false); return }
        lastHeard = Date()
        for p in packets {
            guard mine == generation else { return }
            switch p {
            case .connack(let code):
                if code == 0 {
                    send(MQTTOut.subscribe(id: 1, filters: BotTopics.filters(home: home)))
                } else {
                    dropped(generation: mine, refused: true)   // 4 = bad user or password, 5 = not authorised
                    return
                }
            case .suback:
                attempt = 0
                timeout?.cancel()
                state = .listening
                keepAlive(generation: mine)
            case .publish(let topic, let payload, let qos, let id):
                if qos == 1, let id { send(MQTTOut.puback(id)) }
                if qos == 2, let id { send(MQTTOut.pubrec(id)) }
                if BotTopics.allowed(topic, home: home) { onMessage(topic, payload) }
            case .pubrel(let id):
                send(MQTTOut.pubcomp(id))
            case .pingresp, .other:
                break
            }
        }
    }

    private func keepAlive(generation mine: Int) {
        pinger?.cancel()
        let every = Double(timing.keepAlive) / 2
        pinger = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: UInt64(every * 1_000_000_000))
                guard !Task.isCancelled, let self, self.generation == mine else { return }
                if Date().timeIntervalSince(self.lastHeard) > Double(self.timing.keepAlive) * 1.5 {
                    self.dropped(generation: mine, refused: false)     // a silently dead network
                    return
                }
                self.send(MQTTOut.pingreq)
            }
        }
    }

    private func send(_ data: Data) {
        connection?.send(content: data, completion: .contentProcessed { _ in })
    }

    private func close(sayGoodbye: Bool) {
        pinger?.cancel(); pinger = nil
        timeout?.cancel(); timeout = nil
        generation += 1
        if let c = connection {
            c.stateUpdateHandler = nil
            if sayGoodbye, c.state == .ready {
                c.send(content: MQTTOut.disconnect, completion: .contentProcessed { _ in c.cancel() })
            } else {
                c.cancel()
            }
        }
        connection = nil
    }

    private func dropped(generation mine: Int, refused: Bool) {
        guard mine == generation, !stopped else { return }
        close(sayGoodbye: false)
        state = refused ? .refused : .unreachable
        let base = timing.backoff[min(attempt, timing.backoff.count - 1)] * (refused ? 4 : 1)
        attempt += 1
        let wait = base * Double.random(in: 0.85...1.15)
        retry?.cancel()
        retry = Task { [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(wait * 1_000_000_000))
            guard !Task.isCancelled, let self, !self.stopped else { return }
            self.open()
        }
    }
}

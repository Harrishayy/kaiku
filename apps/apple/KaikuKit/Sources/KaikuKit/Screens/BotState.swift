import Foundation

// What the "Kaiku bot" tab knows, made only from the envelopes it heard on the home broker (`BotBusClient`).
// `BotState.take` is the one reducer (pure: the time is passed in, nothing is read from anywhere else), so a test
// can turn recorded envelopes into exactly what the screen shows. Field names are the contract's
// (contracts/python/kaiku_contracts/payloads.py); every field is read leniently: a field that is missing or of
// another type is simply not shown, an unknown type is one plain feed line, and nothing here can throw.

/// One envelope as heard. Only what the tab uses; the payload stays loose JSON.
public struct BotEnvelope: Equatable, Sendable {
    public var type: String
    public var source: String
    public var home: String?
    public var sim: Bool
    public var payload: JSONValue

    public init(type: String, source: String, home: String? = nil, sim: Bool = false, payload: JSONValue = .object([:])) {
        self.type = type; self.source = source; self.home = home; self.sim = sim; self.payload = payload
    }

    /// nil for anything that is not a JSON object with a `type` (an audio frame never gets this far).
    public static func decode(_ data: Data) -> BotEnvelope? {
        // JSONDecoder, not JSONSerialization: through `Any` a 0 or a 1 would come back as a Bool.
        guard data.count <= MQTTDecoder.maxPacket, data.first == UInt8(ascii: "{"),
              let v = try? JSONDecoder().decode(JSONValue.self, from: data), case .object = v else { return nil }
        guard let type = v["type"]?.string, !type.isEmpty, type.count <= 80 else { return nil }
        return BotEnvelope(type: type, source: v["source"]?.string ?? "", home: v["home_id"]?.string,
                           sim: v["sim"]?.bool ?? false, payload: v["payload"] ?? .object([:]))
    }
}

/// Which filter of the feed a message belongs to.
public enum BotKind: String, CaseIterable, Sendable {
    case senses, body, voice, records, parts

    static func of(_ type: String) -> BotKind {
        if type == "health" { return .parts }
        if type == "raw.hub.trace" { return .voice }
        if type.hasPrefix("obs.") { return .records }
        if type.hasPrefix("cmd.") { return .body }
        return .senses
    }
}

/// One line of the feed. A flood (face frames, pulse samples, a run of taps, a held microphone) is ONE line that is
/// updated in place: `count` says how many messages it stands for.
public struct BotFeedItem: Identifiable, Equatable, Sendable {
    public let id: UUID
    public var at: Date
    public var source: String
    public var kind: BotKind
    public var line: String
    public var count: Int
    public var sim: Bool
    var key: String?
}

public struct BotState: Equatable, Sendable {
    public static let feedMax = 300
    public static let recordsMax = 40

    public struct Part: Equatable, Sendable {
        public var lastSeen: Date
        public var status: String?
        public var version: String?
        public var firmware: String?
        public var sim: Bool
    }

    public struct Face: Equatable, Sendable {
        public var x: Double, y: Double, size: Double, confidence: Double
        public var at: Date
    }

    public struct Said: Equatable, Sendable { public var text: String; public var by: String?; public var at: Date }
    public struct Tool: Equatable, Sendable {
        public var name: String; public var by: String?; public var ms: Int?; public var ok: Bool?; public var at: Date
    }

    // the parts
    public var parts: [String: Part] = [:]
    public var messages = 0
    public var simulated = 0

    // now
    public var step: String?
    public var stepAt: Date?
    public var headMode: String?
    public var eyes: String?
    public var chest: String?
    public var panMode: String?
    public var bpm: Double?
    public var panDeg: Double?
    public var moving: Bool?
    /// The hub's last `mic: open` (it re-sends one every 2 s while it holds the head's microphone open).
    public var micHeldAt: Date?
    public var micClosedAt: Date?
    /// The head's own word, from its heartbeat (`details.audio.mic_open`).
    public var micReported: Bool?
    public var micReportedAt: Date?
    var micRun = 0
    public var helpShown = false
    public var helpAt: Date?

    // senses
    public var ear: Int?
    public var earPressedAt: Date?
    public var earAt: Date?
    public var taps: [Date] = []
    var tapClock: [Int] = []
    public var tapCount = 0
    public var buttonAt: Date?
    public var buttonPressed: Bool?
    public var pulseAsked: Bool?
    public var pulseSamplesAt: Date?
    public var pulseSamples = 0
    public var hr: Double?
    public var rmssd: Double?
    public var breath: Double?
    public var hrvAt: Date?
    public var face: Face?
    public var faceFrames = 0
    public var distanceCm: Double?
    public var distanceAt: Date?
    public var lux: Double?
    public var luxAt: Date?
    public var cameraOK: Bool?

    // voice and mind
    public var said: [Said] = []
    public var heard = 0
    public var heardAt: Date?
    public var tools: [Tool] = []
    public var conversationOpen: Bool?
    public var conversationAt: Date?
    public var songBpm: Double?
    public var level: Int?
    public var yourTurnAt: Date?
    public var band: String?
    public var bandAt: Date?
    public var music: String?

    // what leaves the home
    public var records: [BotFeedItem] = []
    public var feed: [BotFeedItem] = []

    public init() {}

    // MARK: derived

    /// The microphone is open while the hub keeps holding it (an `open` in the last 10 s, the head's own limit) and
    /// has not closed it since, or while the head's latest heartbeat says it is open.
    public func micOpen(now: Date) -> Bool? {
        let held: Bool? = micHeldAt.map { at in now.timeIntervalSince(at) < 10 && (micClosedAt.map { $0 < at } ?? true) }
        let reported: Bool? = micReportedAt.flatMap { now.timeIntervalSince($0) < 15 ? micReported : nil }
        if held == true || reported == true { return true }
        if held == false || reported == false || micClosedAt != nil { return false }
        return parts["head"] != nil || parts["hub"] != nil ? false : nil
    }

    /// Someone is in front of the robot's camera: a face position in the last two seconds.
    public func someoneInView(now: Date) -> Bool? {
        if let face, now.timeIntervalSince(face.at) < 2 { return true }
        if faceFrames > 0 || cameraOK == true || distanceAt != nil { return false }
        return nil
    }

    /// The tempo of the last few taps, a minute's worth of beats: from the board's own clock when it has one.
    public var tapTempo: Double? {
        let gaps: [Double]
        if tapClock.count >= 3, zip(tapClock.dropFirst(), tapClock).allSatisfy({ $0 > $1 }) {
            gaps = zip(tapClock.dropFirst(), tapClock).map { Double($0 - $1) / 1000 }
        } else {
            gaps = zip(taps.dropFirst(), taps).map { $0.timeIntervalSince($1) }
        }
        let usable = gaps.filter { $0 > 0.15 && $0 < 2.5 }.sorted()
        guard usable.count >= 2 else { return nil }
        return 60 / usable[usable.count / 2]
    }

    public func helpOn(now: Date) -> Bool { helpShown && (helpAt.map { now.timeIntervalSince($0) < 600 } ?? false) }

    // MARK: the reducer

    public mutating func take(_ e: BotEnvelope, now: Date) {
        messages += 1
        if e.sim { simulated += 1 }
        let p = e.payload
        let source = e.source.isEmpty ? "?" : e.source
        func line(_ text: String, key: String? = nil, window: TimeInterval = 30) {
            add(BotFeedItem(id: UUID(), at: now, source: source, kind: BotKind.of(e.type), line: text, count: 1, sim: e.sim, key: key),
                window: window)
        }

        switch e.type {
        case "health":
            let d = p["details"]
            var part = parts[source] ?? Part(lastSeen: now, sim: e.sim)
            part.lastSeen = now
            part.status = p["status"]?.string ?? part.status
            part.version = p["version"]?.string ?? part.version
            part.firmware = d?["firmware"]?.string ?? part.firmware
            part.sim = e.sim || d?["sim"]?.bool == true
            parts[source] = part
            if source == "head" {
                if let s = d?["step"]?.string { setStep(s, now) }
                if let open = d?["audio"]?["mic_open"]?.bool { micReported = open; micReportedAt = now }
                if let h = d?["help_shown"]?.bool { helpShown = h; if h, helpAt == nil { helpAt = now } }
            }
            if source == "hub" {
                if let r = d?["ritual"]?.string { setStep(r.hasPrefix("head:") ? String(r.dropFirst(5)) : r, now) }
                headMode = d?["head_mode"]?.string ?? headMode
            }
            if source == "sensors", let ok = d?["camera_ok"]?.bool { cameraOK = ok }
            // One line per part and status: "on ×12", and a separate line when it goes off.
            line(BotWords.health(source, status: p["status"]?.string, version: p["version"]?.string),
                 key: "health/\(source)/\(p["status"]?.string ?? "")", window: 120)

        case "raw.head.ear":
            ear = p["value"]?.int ?? ear
            earAt = now
            let pressed = p["pressed"]?.bool == true
            if pressed { earPressedAt = now }
            line(BotWords.ear(ear, pressed: pressed), key: pressed ? nil : "ear", window: 4)

        case "raw.head.tap":
            taps.append(now); if taps.count > 8 { taps.removeFirst(taps.count - 8) }
            if let t = p["t_ms"]?.int { tapClock.append(t); if tapClock.count > 8 { tapClock.removeFirst(tapClock.count - 8) } }
            tapCount += 1
            line(BotWords.taps(tempo: tapTempo), key: "tap", window: 3)

        case "raw.head.button", "raw.sensors.button":
            buttonPressed = p["pressed"]?.bool
            buttonAt = now
            line(BotWords.button(id: p["id"]?.string, pressed: buttonPressed == true))

        case "raw.head.pan":
            panDeg = p["deg"]?.double ?? panDeg
            moving = p["moving"]?.bool ?? moving
            line(BotWords.pan(panDeg, moving: moving == true), key: "pan", window: 30)

        case "raw.sensors.ppg":
            pulseSamplesAt = now
            if case .array(let a)? = p["samples"] { pulseSamples += a.count }
            line(T("bot.feed.ppg"), key: "ppg", window: 30)

        case "raw.sensors.distance":
            distanceCm = p["cm"]?.double
            distanceAt = now
            line(BotWords.distance(distanceCm), key: "distance", window: 30)

        case "raw.sensors.light":
            lux = p["lux_est"]?.double
            luxAt = now
            line(BotWords.light(lux), key: "light", window: 60)

        case "raw.sensors.hall":
            line(T(p["at_home"]?.bool == true ? "bot.feed.hall.home" : "bot.feed.hall.away"), key: "hall", window: 30)

        case "raw.hub.face":
            faceFrames += 1
            if let x = p["x_norm"]?.double, let y = p["y_norm"]?.double {
                face = Face(x: max(-1, min(1, x)), y: max(-1, min(1, y)), size: max(0, min(1, p["size"]?.double ?? 0)),
                            confidence: p["confidence"]?.double ?? 0, at: now)
            }
            line(BotWords.face(face), key: "face", window: 30)

        case "raw.hub.trace":
            var out: [(String, String?)] = []
            trace(p, now: now, line: { out.append(($0, $1)) })
            for (text, key) in out { line(text, key: key, window: 30) }

        case "cmd.head":
            var out: [(String, String?)] = []
            head(p, now: now, line: { out.append(($0, $1)) })
            for (text, key) in out { line(text, key: key, window: 30) }

        case "cmd.sensors":
            if let ppg = p["ppg"]?.string { pulseAsked = ppg == "start"; line(T(ppg == "start" ? "bot.feed.ppg.start" : "bot.feed.ppg.stop")) }
            if let chime = p["chime"]?.string { line(T("bot.feed.chime", ["name": BotWords.chime(chime)])) }
            if let cam = p["camera_enable"]?.bool { line(T(cam ? "bot.feed.camera.on" : "bot.feed.camera.off")) }
            if p["ppg"] == nil, p["chime"] == nil, p["camera_enable"] == nil { line(BotWords.unknown(e.type, source)) }

        case "cmd.hub":
            // `say` is a typed line from a demo or a test: its words are never shown, like her spoken ones.
            if p["start_ritual"]?.bool == true { line(T("bot.feed.hub.start")) }
            else if p["say"] != nil { line(T("bot.feed.hub.say")) }
            else { line(T("bot.feed.hub.other")) }

        case "cmd.friendlink":
            line(T("bot.feed.friend"))

        default:
            if e.type.hasPrefix("obs.") {
                record(e, now: now)
                line(BotWords.record(e))
            } else {
                line(BotWords.unknown(e.type, source))
            }
        }
    }

    private mutating func setStep(_ s: String, _ now: Date) {
        step = s
        stepAt = now
    }

    private mutating func head(_ p: JSONValue, now: Date, line: (String, String?) -> Void) {
        var said = false
        if let mic = p["mic"]?.string {
            said = true
            if mic == "open" {
                let fresh: Bool = {
                    guard let last = micHeldAt else { return true }
                    if now.timeIntervalSince(last) >= 10 { return true }
                    if let closed = micClosedAt, closed >= last { return true }
                    return false
                }()
                if fresh { micRun += 1 }
                micHeldAt = now
                // One line for as long as it is held: "opened", then the hub's refreshes counted on it.
                line(T(fresh ? "bot.feed.mic.open" : "bot.feed.mic.held"), "mic.open.\(micRun)")
            } else {
                micClosedAt = now
                line(T("bot.feed.mic.close"), nil)
            }
        }
        if let show = p["show"]?.string {
            said = true
            helpShown = show == "help"
            helpAt = show == "help" ? now : nil
            line(T(show == "help" ? "bot.feed.help" : "bot.feed.help.off"), nil)
        }
        if let drum = p["drum"]?.string {
            said = true
            line(T(drum == "hold" ? "bot.feed.drum.hold" : "bot.feed.drum.end"), drum == "hold" ? "drum.hold" : nil)
        }
        var body: [String] = []
        if let eyes = p["eyes"]?.string { self.eyes = eyes; body.append(T("bot.feed.eyes", ["eyes": BotWords.eyes(eyes)])) }
        if let chest = p["chest"]?.string { self.chest = chest; body.append(T("bot.feed.chest", ["light": BotWords.chest(chest)])) }
        if let mode = p["pan_mode"]?.string { panMode = mode; body.append(BotWords.panMode(mode)) }
        if let bpm = p["bpm"]?.double { self.bpm = bpm; body.append(T("bot.feed.bpm", ["n": BotWords.whole(bpm)])) }
        if let g = p["gesture"]?.string { body.append(BotWords.gesture(g)) }
        if p["purr"] != nil { body.append(T("bot.feed.purr")) }
        if p["home"]?.bool == true { body.append(T("bot.feed.home")) }
        if !body.isEmpty { line(body.joined(separator: " · "), nil) }
        else if p["look"] != nil || p["pan"] != nil { line(T("bot.feed.look"), "look") }
        else if !said { line(BotWords.unknown("cmd.head", "hub"), nil) }
    }

    private mutating func trace(_ p: JSONValue, now: Date, line: (String, String?) -> Void) {
        let kind = p["kind"]?.string ?? ""
        let detail = p["detail"]?.string
        switch kind {
        case "said":
            let text = String((p["text"]?.string ?? "").prefix(300))
            guard !text.isEmpty else { line(T("bot.feed.said.empty"), nil); return }
            said.insert(Said(text: text, by: p["by"]?.string, at: now), at: 0)
            if said.count > 6 { said.removeLast(said.count - 6) }
            line(T("bot.feed.said", ["text": text]), nil)
        case "heard":
            heard += 1
            heardAt = now
            line(T("bot.feed.heard"), "heard")
        case "tool":
            let t = Tool(name: p["tool"]?.string ?? "", by: p["by"]?.string, ms: p["ms"]?.int, ok: p["ok"]?.bool, at: now)
            tools.insert(t, at: 0)
            if tools.count > 8 { tools.removeLast(tools.count - 8) }
            line(BotWords.tool(t), nil)
        case "session":
            conversationOpen = detail == "open" ? true : detail == "close" ? false : conversationOpen
            conversationAt = now
            line(T(detail == "close" ? "bot.feed.session.close" : "bot.feed.session.open"), nil)
        case "game":
            if let d = detail, d.hasPrefix("level:") {
                level = Int(d.dropFirst(6))
                songBpm = p["bpm"]?.double ?? songBpm
                band = nil
                line(BotWords.level(level, bpm: songBpm), nil)
            } else if detail == "your_turn" {
                yourTurnAt = now
                line(T("bot.feed.yourturn"), nil)
            } else if let d = detail, d.hasPrefix("band:") {
                band = String(d.dropFirst(5))
                bandAt = now
                line(T("bot.feed.band", ["band": BotWords.band(band)]), nil)
            } else {
                line(T("bot.feed.game"), nil)
            }
        case "music":
            music = detail
            if let bpm = p["bpm"]?.double { songBpm = bpm }
            line(BotWords.music(detail, bpm: p["bpm"]?.double), nil)
        default:
            line(T("bot.feed.trace.other"), nil)
        }
    }

    private mutating func record(_ e: BotEnvelope, now: Date) {
        if e.type == "obs.hrv_session" {
            hr = e.payload["hr_bpm"]?.double; rmssd = e.payload["rmssd_post_ms"]?.double ?? e.payload["rmssd_pre_ms"]?.double
            breath = e.payload["breath_bpm"]?.double; hrvAt = now
        }
        if e.type == "obs.ritual", let s = e.payload["step"]?.string, e.payload["status"]?.string == "started" { setStep(s, now) }
        let item = BotFeedItem(id: UUID(), at: now, source: e.source.isEmpty ? "?" : e.source, kind: .records,
                               line: BotWords.record(e), count: 1, sim: e.sim, key: nil)
        records.insert(item, at: 0)
        if records.count > Self.recordsMax { records.removeLast(records.count - Self.recordsMax) }
    }

    /// New line on top, or (a flood) the same line updated in place and brought to the top.
    mutating func add(_ item: BotFeedItem, window: TimeInterval) {
        if let key = item.key, let i = feed.firstIndex(where: { $0.key == key && item.at.timeIntervalSince($0.at) < window }) {
            var old = feed.remove(at: i)
            old.at = item.at; old.line = item.line; old.count += 1; old.sim = item.sim; old.source = item.source
            feed.insert(old, at: 0)
            return
        }
        feed.insert(item, at: 0)
        if feed.count > Self.feedMax { feed.removeLast(feed.count - Self.feedMax) }
    }
}

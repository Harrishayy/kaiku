import SwiftUI

/// "Today, so far": what was captured today, from which device, and what is shared (pure; tested).
/// Built only from today's stored observations for this home (`GET /v1/events`) plus this device's own count of
/// finished conversations. Honest by construction: a walk through glasses says the glasses carried the voice and
/// counted movement, never that they saw anything; daylight minutes appear only when a reading exists; practice
/// (simulated) records are labelled; nothing is inferred from a missing record.
public struct DayEvidence: Equatable, Sendable {
    public enum Kind: String, Sendable, CaseIterable { case outing, checkin, task, camera, talk, health, robot, mac }
    public enum Sharing: Equatable, Sendable { case numbers, wordsKept, wordsNotKept }

    public struct Item: Identifiable, Equatable, Sendable {
        public let kind: Kind
        /// Short facts, already worded ("24 min walking", "3 200 steps").
        public var facts: [String]
        /// Devices the records came from, as copy keys (`evidence.src.*`), in a stable order.
        public var sources: [String]
        public var sharing: Sharing
        /// Every record behind this item was practice data (`sim`).
        public var practice: Bool
        /// An extra honest sentence (glasses do not see).
        public var note: String?
        public var id: String { kind.rawValue }
    }

    public var items: [Item]

    static func sourceKey(_ source: String) -> String? {
        switch source {
        case "phone": return "evidence.src.phone"
        case "laptop": return "evidence.src.laptop"
        case "glasses": return "evidence.src.glasses"
        case "hub", "head", "sensors": return "evidence.src.robot"
        case "cloud": return "evidence.src.cloud"
        default: return nil
        }
    }
    static let sourceOrder = ["evidence.src.phone", "evidence.src.glasses", "evidence.src.laptop", "evidence.src.robot", "evidence.src.cloud"]

    /// The tasks in which the camera was on today, each once: what the service holds (`obs.face_signs`, and a game
    /// session of another kind of app that carries camera numbers of its own) and what this device sent. The list
    /// of this device's own sends makes the line true before the service knows the observation type.
    struct CameraTasks: Equatable, Sendable {
        var count: Int
        var sources: [String]
        var practice: Bool
    }

    static func cameraTasks(events: [AnyEnvelope], sent: [CameraChoice.Sent]) -> CameraTasks? {
        let signs = events.filter { $0.type == "obs.face_signs" }
        let ids = Set(signs.map(\.id)).union(sent.map(\.id))
        let refs = Set(signs.compactMap { $0.payload["ref"]?.string }).union(sent.compactMap(\.ref))
        let alone = events.filter { $0.type == "obs.play_session" && ($0.payload["camera_samples"]?.double ?? 0) > 0 && !refs.contains($0.id) }
        let count = ids.count + alone.count
        guard count > 0 else { return nil }
        var keys = Set((signs + alone).compactMap { sourceKey($0.source) })
        if !sent.isEmpty { keys.insert(KaikuPlatform.isPhone ? "evidence.src.phone" : "evidence.src.laptop") }
        let held = Set(signs.map(\.id))
        let practice = (signs + alone).allSatisfy { $0.sim == true } && sent.filter { !held.contains($0.id) }.allSatisfy(\.sim)
        return CameraTasks(count: count, sources: sourceOrder.filter(keys.contains), practice: practice)
    }

    /// The kinds of numbers today's Apple Health summaries hold, in plain words and a fixed order. They are named
    /// here, not shown: the numbers themselves are in History. Only what a summary really carries is named.
    static func healthNames(_ events: [AnyEnvelope]) -> [String] {
        let health = events.filter { $0.type == "obs.wearable_daily" }
        func has(_ fields: String...) -> Bool { health.contains { e in fields.contains { e.payload[$0]?.double != nil } } }
        var keys: [String] = []
        if has("sleep_min", "sleep_midpoint_min") { keys.append("sleep") }
        if has("sleep_deep_min", "sleep_rem_min", "sleep_core_min") { keys.append("stages") }
        if has("sleep_awake_min") { keys.append("awake") }
        if has("resting_hr_bpm") { keys.append("resting") }
        if has("walking_hr_bpm") { keys.append("walking") }
        if has("hrv_sdnn_ms") { keys.append("hrv") }
        if has("steps") { keys.append("steps") }
        if has("distance_km") { keys.append("distance") }
        if has("exercise_min") { keys.append("exercise") }
        if has("daylight_min") { keys.append("daylight") }
        return keys.map { T("health.name.\($0)") }
    }

    public static func build(events: [AnyEnvelope], talks: Int, transcriptsKept: Bool) -> DayEvidence {
        build(events: events, talks: talks, transcriptsKept: transcriptsKept, camera: [])
    }

    static func build(events: [AnyEnvelope], talks: Int, transcriptsKept: Bool, camera: [CameraChoice.Sent]) -> DayEvidence {
        func of(_ types: String...) -> [AnyEnvelope] { events.filter { types.contains($0.type) } }
        func sources(_ ev: [AnyEnvelope], extra: [String] = []) -> [String] {
            let keys = Set(ev.compactMap { sourceKey($0.source) } + extra)
            return sourceOrder.filter(keys.contains)
        }
        func practice(_ ev: [AnyEnvelope]) -> Bool { !ev.isEmpty && ev.allSatisfy { $0.sim == true } }
        var items: [Item] = []

        let outings = of("obs.outing")
        if !outings.isEmpty {
            let minutes = outings.compactMap { $0.payload["minutes"]?.double }.reduce(0, +)
            let steps = outings.compactMap { $0.payload["steps"]?.double }.reduce(0, +)
            let daylight = outings.compactMap { $0.payload["daylight_min"]?.double }.reduce(0, +)
            var facts = [T("evidence.outing.min", n: Int(minutes.rounded()))]
            if steps > 0 { facts.append(T("evidence.outing.steps", n: Int(steps))) }
            if daylight > 0 { facts.append(T("evidence.outing.daylight", n: Int(daylight.rounded()))) }
            // `dat_imu` = movement measured by the glasses' motion sensor (no camera involved).
            let glasses = outings.contains { $0.payload["method"]?.string == "dat_imu" }
            items.append(Item(kind: .outing, facts: facts, sources: sources(outings, extra: glasses ? ["evidence.src.glasses"] : []),
                              sharing: .numbers, practice: practice(outings), note: glasses ? T("evidence.outing.glasses") : nil))
        }
        let dials = of("obs.self_report")
        if !dials.isEmpty {
            items.append(Item(kind: .checkin, facts: [T("evidence.checkin.n", n: dials.count)], sources: sources(dials),
                              sharing: .numbers, practice: practice(dials)))
        }
        let tasks = of("obs.play_session", "obs.drum_session")
        if !tasks.isEmpty {
            items.append(Item(kind: .task, facts: [T("evidence.task.n", n: tasks.count)], sources: sources(tasks),
                              sharing: .numbers, practice: practice(tasks)))
        }
        if let seen = cameraTasks(events: events, sent: camera) {
            // Face signs as numbers; the note says what that means and what was never made.
            items.append(Item(kind: .camera, facts: [T("evidence.camera.n", n: seen.count)], sources: seen.sources,
                              sharing: .numbers, practice: seen.practice, note: T("evidence.camera.note")))
        }
        if talks > 0 {
            items.append(Item(kind: .talk, facts: [T("evidence.talk.n", n: talks)],
                              sources: [KaikuPlatform.isPhone ? "evidence.src.phone" : "evidence.src.laptop"],
                              sharing: transcriptsKept ? .wordsKept : .wordsNotKept, practice: false))
        }
        let health = of("obs.wearable_daily")
        if !health.isEmpty {
            let names = healthNames(health)
            items.append(Item(kind: .health,
                              facts: [names.isEmpty ? T("evidence.health.d") : T("evidence.health.read", ["list": names.joined(separator: ", ")])],
                              sources: sources(health), sharing: .numbers, practice: practice(health)))
        }
        let robot = of("obs.ritual", "obs.ritual_complete")
        if !robot.isEmpty {
            items.append(Item(kind: .robot, facts: [T("evidence.robot.d")], sources: sources(robot), sharing: .numbers,
                              practice: practice(robot)))
        }
        let mac = of("obs.screen_activity")
        if !mac.isEmpty {
            items.append(Item(kind: .mac, facts: [T("evidence.mac.d")], sources: sources(mac), sharing: .numbers,
                              practice: practice(mac)))
        }
        return DayEvidence(items: items)
    }
}

extension DayEvidence.Kind {
    var title: String { T("evidence.\(rawValue)") }
    var symbol: String {
        switch self {
        case .outing: return "figure.walk"
        case .checkin: return "dial.medium.fill"
        case .task: return "sparkles"
        case .camera: return "camera.fill"
        case .talk: return "bubble.left.and.bubble.right.fill"
        case .health: return "heart.fill"
        case .robot: return "circle.hexagongrid.fill"
        case .mac: return "laptopcomputer"
        }
    }
    var tone: KTone {
        switch self {
        case .outing, .health, .camera: return .sage
        case .checkin, .mac: return .sky
        case .task, .robot: return .honey
        case .talk: return .clay
        }
    }
}

/// The evidence list as one section (Your days, What Kaiku saw today).
struct EvidenceSection: View {
    @Environment(AppModel.self) private var app
    var showsDetailLink = false

    var evidence: DayEvidence {
        DayEvidence.build(events: app.todayEvents, talks: app.talksToday, transcriptsKept: app.consents[.transcripts] == true,
                          camera: app.cameraChoice.sentToday())
    }

    var body: some View {
        KSection(T("evidence.title"), subtitle: T("evidence.sub"), icon: "checklist", tone: .sage) {
            if evidence.items.isEmpty {
                Text(T(app.isPaired ? "evidence.empty" : "evidence.offline")).kText(.footnote)
                    .foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(KaikuTokens.Space.s4)
            } else {
                ForEach(Array(evidence.items.enumerated()), id: \.element.id) { i, item in
                    if i > 0 { KDivider() }
                    EvidenceRow(item: item)
                }
            }
            if showsDetailLink {
                KDivider()
                NavigationLink(value: KaikuRoute.saw) {
                    KRow(icon: "list.bullet.rectangle", tint: KaikuTokens.Colors.sage, title: T("evidence.more"))
                }
                .buttonStyle(.kPressRow())
            }
        }
        .task { await app.loadToday() }
    }
}

struct EvidenceRow: View {
    let item: DayEvidence.Item

    private var sharing: String {
        switch item.sharing {
        case .numbers: return T("evidence.shared")
        case .wordsKept: return T("evidence.shared.words.on")
        case .wordsNotKept: return T("evidence.shared.words.off")
        }
    }

    var body: some View {
        HStack(alignment: .top, spacing: KaikuTokens.Space.s3) {
            RowIcon(symbol: item.kind.symbol, tint: item.kind.tone.ink)
            VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
                Text(item.kind.title).kText(.body, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                Text(item.facts.joined(separator: " · ")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                if !item.sources.isEmpty {
                    Text(T("evidence.from", ["name": item.sources.map { T($0) }.joined(separator: ", ")]))
                        .kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                }
                if let note = item.note { Text(note).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps() }
                Text(item.practice ? T("common.simulated") : sharing).kText(.caption).foregroundStyle(KaikuTokens.Colors.muted).wraps()
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.horizontal, KaikuTokens.Space.s4)
        .padding(.vertical, KaikuTokens.Space.s3)
        .accessibilityElement(children: .combine)
    }
}

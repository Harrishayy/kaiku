import Foundation
import Observation

// Usage rhythm (D26, plan 02 §6): the Mac app samples the frontmost app's bundle id + the idle time every 30 s,
// turns the bundle id into a broad category on the spot (the id itself is never kept), aggregates locally and sends
// one obs.screen_activity per hour. Never window titles, URLs, keystrokes or screenshots. The pure parts (category
// table, aggregator, payload) live here so `swift test` covers them; the AppKit sampler lives in the Mac target.

/// Broad app categories (contracts: ScreenCategoryMinutes). Ids match the payload keys and copy keys `mac.cat.<id>`.
public enum MacAppCategory: String, Codable, CaseIterable, Sendable {
    case work, communication, social, video, news, games, other

    /// Bundled bundle-id → category table. Exact ids first, then prefixes (a vendor's apps share a category).
    /// Browsers count as `other`: what a browser shows is content, and content is exactly what we don't read.
    public static let table: [String: MacAppCategory] = [
        // work
        "com.apple.dt.Xcode": .work, "com.microsoft.VSCode": .work, "com.apple.Terminal": .work,
        "com.googlecode.iterm2": .work, "com.apple.iWork.Pages": .work, "com.apple.iWork.Numbers": .work,
        "com.apple.iWork.Keynote": .work, "com.microsoft.Word": .work, "com.microsoft.Excel": .work,
        "com.microsoft.Powerpoint": .work, "com.figma.Desktop": .work, "notion.id": .work,
        "com.apple.Notes": .work, "com.apple.finder": .work, "com.apple.Preview": .work,
        "com.jetbrains.intellij": .work, "com.jetbrains.pycharm": .work, "md.obsidian": .work,
        "com.todesktop.230313mzl4w4u92": .work, "com.anthropic.claudefordesktop": .work, "com.linear": .work,
        "com.apple.iCal": .work, "com.apple.reminders": .work,
        // communication
        "com.apple.mail": .communication, "com.apple.MobileSMS": .communication, "com.apple.FaceTime": .communication,
        "com.tinyspeck.slackmacgap": .communication, "com.microsoft.teams2": .communication,
        "com.microsoft.teams": .communication, "us.zoom.xos": .communication, "com.microsoft.Outlook": .communication,
        "net.whatsapp.WhatsApp": .communication, "org.whispersystems.signal-desktop": .communication,
        "ru.keepcoder.Telegram": .communication, "com.hnc.Discord": .communication, "com.cisco.webexmeetingsapp": .communication,
        // social
        "com.facebook.archon": .social, "com.burbn.instagram": .social, "com.atebits.Tweetie2": .social,
        "maccatalyst.com.atebits.Tweetie2": .social, "com.reddit.Reddit": .social, "com.bluesky.app": .social,
        // video
        "com.apple.TV": .video, "com.netflix.Netflix": .video, "com.colliderli.iina": .video, "org.videolan.vlc": .video,
        "com.apple.QuickTimePlayerX": .video, "com.google.ios.youtube": .video, "com.disney.disneyplus": .video,
        "com.spotify.client": .video, "com.apple.Music": .video, "com.apple.podcasts": .video,
        // news
        "com.apple.news": .news, "com.apple.stocks": .news, "com.reederapp.5.macOS": .news, "com.ranchero.NetNewsWire-Evergreen": .news,
        // games
        "com.valvesoftware.steam": .games, "com.apple.Chess": .games, "com.epicgames.EpicGamesLauncher": .games,
        "com.blizzard.worldofwarcraft": .games, "com.mojang.minecraftlauncher": .games,
    ]
    static let prefixes: [(String, MacAppCategory)] = [
        ("com.jetbrains.", .work), ("com.microsoft.Office", .work), ("com.valvesoftware.", .games),
        ("com.riotgames.", .games), ("com.blizzard.", .games), ("com.apple.dt.", .work),
    ]

    /// Category of a frontmost app. Unknown, missing or empty ids are `other` (nothing else is inferred).
    public static func of(bundleID: String?) -> MacAppCategory {
        guard let id = bundleID, !id.isEmpty else { return .other }
        if let c = table[id] { return c }
        if let p = prefixes.first(where: { id.hasPrefix($0.0) }) { return p.1 }
        return .other
    }
}

/// One 30 s sample, already reduced: a category (not the bundle id), seconds since the last input, how many
/// frontmost-app switches happened since the previous sample, and whether sensing was paused.
public struct MacUsageSample: Sendable, Equatable {
    public var at: Date
    public var category: MacAppCategory
    public var idleSeconds: Double
    public var switches: Int
    public var paused: Bool
    public init(at: Date, category: MacAppCategory, idleSeconds: Double, switches: Int = 0, paused: Bool = false) {
        self.at = at; self.category = category; self.idleSeconds = idleSeconds; self.switches = switches; self.paused = paused
    }
}

/// obs.screen_activity payload (contracts/schemas/obs/screen_activity.schema.json). Numbers + category keys only.
public struct ScreenActivity: Codable, Sendable, Equatable {
    public var period_min: Double
    public var active_min: Double
    public var late_night_min: Double
    public var category_min: [String: Double]
    public var switches_per_hour: Double
    public var longest_stretch_min: Double
    public var breaks: Int
    public var paused: Bool
}

/// Local aggregation of samples into hourly periods + a running "today" total for the receipt and the peek rules.
/// Codable so it survives restarts and sleep (`MacUsageStore` persists it; it holds no ids, titles or content).
public struct MacUsageAggregator: Codable, Sendable, Equatable {
    public static let sampleSeconds: Double = 30
    /// Input within this many seconds = active.
    public static let activeIdleLimit: Double = 60
    /// An idle gap at least this long is a break and ends the stretch (schema: breaks = idle gaps >= 5 min).
    public static let breakSeconds: Double = 300
    /// A gap between samples longer than this (lid closed, asleep) counts as idle time, not activity.
    public static let maxSampleGap: Double = 90

    public struct Bucket: Codable, Sendable, Equatable {
        public var start: Date
        public var active = 0.0, late = 0.0, longest = 0.0
        public var categories: [String: Double] = [:]
        public var switches = 0, breaks = 0
        public var paused = false
    }

    public struct Day: Codable, Sendable, Equatable {
        public var key: String
        public var active = 0.0, late = 0.0, longest = 0.0
        public var categories: [String: Double] = [:]
        public var breaks = 0
    }

    public var bucket: Bucket?
    public var today: Day?
    public var lastSampleAt: Date?
    public var lastActive = false
    /// Current unbroken active stretch (seconds) and the idle run since the last input.
    public var stretch = 0.0
    public var idleRun = 0.0

    public init() {}

    public var currentStretchMin: Double { stretch / 60 }

    /// Adds one sample. Returns the hourly payloads that closed because this sample is in a later hour.
    public mutating func ingest(_ s: MacUsageSample, calendar cal: Calendar = .current) -> [(start: Date, payload: ScreenActivity)] {
        var closed: [(Date, ScreenActivity)] = []
        let hourStart = cal.dateInterval(of: .hour, for: s.at)?.start ?? s.at
        if let b = bucket, b.start != hourStart {
            if hourStart > b.start { closed.append((b.start, Self.payload(b))) }
            bucket = nil
        }
        if bucket == nil { bucket = Bucket(start: hourStart) }
        let dayKey = macDayKey(s.at)
        if today?.key != dayKey { today = Day(key: dayKey) }

        let gap = lastSampleAt.map { s.at.timeIntervalSince($0) } ?? Self.sampleSeconds
        lastSampleAt = s.at
        guard gap > 0 else { return closed }
        if s.paused {
            bucket!.paused = true
            lastActive = false
            return closed
        }
        // A long gap (asleep, lid closed) is idle time: it can end a stretch and be a break.
        var dt = gap
        if gap > Self.maxSampleGap {
            addIdle(gap - Self.sampleSeconds, seenIdle: 0)
            dt = Self.sampleSeconds
        }
        let active = s.idleSeconds < Self.activeIdleLimit
        if active {
            idleRun = 0
            stretch += dt
            bucket!.active += dt
            bucket!.categories[s.category.rawValue, default: 0] += dt
            today!.active += dt
            today!.categories[s.category.rawValue, default: 0] += dt
            if (0..<5).contains(cal.component(.hour, from: s.at)) { bucket!.late += dt; today!.late += dt }
            bucket!.switches += s.switches
            bucket!.longest = max(bucket!.longest, min(stretch, 3600))
            today!.longest = max(today!.longest, stretch)
        } else {
            addIdle(dt, seenIdle: s.idleSeconds)
        }
        lastActive = active
        return closed
    }

    /// Idle time grows the idle run (the system's own idle counter wins when it is longer); crossing 5 min counts
    /// one break and ends the stretch.
    private mutating func addIdle(_ seconds: Double, seenIdle: Double) {
        let before = idleRun
        idleRun = max(idleRun + seconds, seenIdle)
        if before < Self.breakSeconds && idleRun >= Self.breakSeconds {
            stretch = 0
            bucket?.breaks += 1
            today?.breaks += 1
        }
    }

    /// Closes the current hour now (e.g. the simulated evening, or quitting); nil when nothing was sampled.
    public mutating func closeCurrent() -> (start: Date, payload: ScreenActivity)? {
        guard let b = bucket else { return nil }
        bucket = nil
        return (b.start, Self.payload(b))
    }

    static func round1(_ x: Double) -> Double { (x * 10).rounded() / 10 }

    public static func payload(_ b: Bucket) -> ScreenActivity {
        let activeMin = min(60, round1(b.active / 60))
        var cats: [String: Double] = [:]
        for c in MacAppCategory.allCases { cats[c.rawValue] = round1((b.categories[c.rawValue] ?? 0) / 60) }
        // Keep the category sum within the period (rounding can add a few tenths).
        let sum = cats.values.reduce(0, +)
        if sum > 60 { for (k, v) in cats { cats[k] = (v * 60 / sum * 10).rounded(.down) / 10 } }
        let perHour = activeMin >= 1 ? min(3600, round1(Double(b.switches) / (activeMin / 60))) : 0
        return ScreenActivity(period_min: 60, active_min: activeMin, late_night_min: min(60, round1(b.late / 60)),
                              category_min: cats, switches_per_hour: perHour,
                              longest_stretch_min: min(60, round1(b.longest / 60)), breaks: b.breaks, paused: b.paused)
    }

    /// Today's totals in whole minutes for "What Kaiku saw today" (same local aggregate as the hourly payloads).
    public func todayMinutes(now: Date = Date()) -> (active: Int, late: Int, categories: [(MacAppCategory, Int)])? {
        guard let d = today, d.key == macDayKey(now) else { return nil }
        let cats = MacAppCategory.allCases.compactMap { c -> (MacAppCategory, Int)? in
            let m = Int(((d.categories[c.rawValue] ?? 0) / 60).rounded())
            return m > 0 ? (c, m) : nil
        }.sorted { $0.1 > $1.1 }
        return (Int((d.active / 60).rounded()), Int((d.late / 60).rounded()), cats)
    }
}

/// The shared local aggregate (Application Support/Kaiku/mac_usage.json). The sampler writes it, the receipt and
/// the menu bar read it. Holds only numbers and category keys.
@Observable @MainActor
public final class MacUsageStore {
    public static let shared = MacUsageStore()
    public var aggregator: MacUsageAggregator
    @ObservationIgnored private let url: URL

    public init(url: URL = KaikuPaths.support.appendingPathComponent("mac_usage.json")) {
        self.url = url
        if let d = try? Data(contentsOf: url), let a = try? JSONDecoder().decode(MacUsageAggregator.self, from: d) {
            aggregator = a
        } else {
            aggregator = MacUsageAggregator()
        }
    }

    public func save() {
        if let d = try? JSONEncoder().encode(aggregator) { try? d.write(to: url, options: .atomic) }
    }

    /// Receipt lines (mono): active minutes, after-midnight minutes, minutes by app type.
    public func receiptLines(now: Date = Date()) -> [String] {
        guard let t = aggregator.todayMinutes(now: now), t.active > 0 else { return [T("saw.mac.none")] }
        var out = [T("saw.mac.n", n: t.active)]
        if t.late > 0 { out.append(T("saw.mac.late.n", n: t.late)) }
        let cats = t.categories.prefix(4).map { T("mac.cat.\($0.0.rawValue)", n: $0.1) }
        if !cats.isEmpty { out.append(cats.joined(separator: " · ")) }
        return out
    }
}

extension AppModel {
    /// One hourly obs.screen_activity, only with the Mac signal allowed (consent on). Paused hours still go out with
    /// `paused: true` so the cloud reads a gap as the person's choice. Always through the offline queue.
    public func recordScreenActivity(_ p: ScreenActivity, at: Date = Date(), sim: Bool = false) async {
        guard consents[.mac] == true, let pr = pairing else { return }
        let env = Envelope(ts: at, home_id: pr.homeID, source: KaikuPlatform.source, type: "obs.screen_activity",
                           payload: p, sim: sim)
        guard let any = try? AnyEnvelope(env) else { return }
        await queue.enqueue(any, server: pr.baseURL)
        await flush()
    }
}

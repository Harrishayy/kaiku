import SwiftUI

// History: the person's own numbers from every device, as a health app shows them. One card per measure, grouped
// (robot first), each with the latest value, where it came from and the last seven days; a card opens the
// measure's page. By the lead's decision this is the one place in the apps where numbers are shown (D48).
// They are shown plainly: no colour for good or bad, no arrow, no "better" or "worse", no state word, no streak.

/// Which measure a page shows: the group's key and the measure's key, as the service names them.
public struct HistoryRef: Hashable, Identifiable, Sendable {
    public let group: String
    public let measure: String
    public var id: String { "\(group)/\(measure)" }
    public init(group: String, measure: String) { self.group = group; self.measure = measure }
}

extension HistoryGroup {
    var symbol: String {
        switch key {
        case "robot": return "circle.hexagongrid.fill"
        case "games": return "sparkles"
        case "walks": return "figure.walk"
        case "checkins": return "dial.medium.fill"
        case "sleep_body": return "bed.double.fill"
        case "mac": return "laptopcomputer"
        case "camera": return "camera.fill"       // her own face-sign numbers ("Camera during activities")
        default: return "chart.bar.fill"          // a group this build does not know yet: a neutral chart
        }
    }

    /// A tone per group tells the groups apart; it says nothing about the numbers.
    var tone: KTone {
        switch key {
        case "robot": return .honey
        case "games": return .clay
        case "walks": return .sage
        case "checkins": return .sky
        case "sleep_body": return .clay
        case "camera": return .sage               // the tint of the camera chip and of a choice that is on
        default: return .ink
        }
    }
}

enum HistoryDevice {
    /// The device's name on screen; nil for a word this build does not know (it is then left out, not shown raw).
    static func name(_ raw: String) -> String? {
        switch raw {
        case "robot": return T("source.robot")
        case "phone": return T("source.phone")
        case "mac": return T("source.laptop")
        case "glasses": return T("source.glasses")
        case "watch": return T("source.wearable")
        case "web": return T("history.device.web")
        default: return nil
        }
    }

    static func names(_ raw: [String]) -> String { raw.compactMap(name).joined(separator: ", ") }
}

/// The History tab's root.
public struct HistoryView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.scenePhase) private var phase
    @State private var model = HistoryModel.shared
    @State private var open: HistoryRef?
    public init() {}

    public var body: some View {
        KScreen(T("tab.history"), subtitle: T("history.sub"), maxWidth: KaikuTokens.Size.paneMax) {
            HistoryDaysCard()
            HistorySummary(model: model) { open = $0 }
        }
        .navigationDestination(item: $open) { HistoryMeasureView(ref: $0, model: model) }
        .task(id: app.pairingRevision) {
            await model.load(app: app)
            #if DEBUG
            if open == nil, let ref = HistoryDebug.launchRef(model) { open = ref }
            #endif
            // "Watch" is on and this build reads kinds of Apple Health data iOS has not asked her about yet: it
            // asks here, in front of her own numbers (never at launch, never in front of a task).
            if await HealthAccess.review(app: app) { await model.load(app: app) }
        }
        .onChange(of: phase) { _, p in if p == .active { Task { await model.load(app: app) } } }
        .refreshable { await model.load(app: app) }
    }
}

/// History's first block: this week, day by day (tap a day to mark it good or hard), and the way to Your days
/// (the garden, today so far, little moments). Your days was a tab until History took its place.
struct HistoryDaysCard: View {
    var body: some View {
        KSection(T("tab.days"), subtitle: T("days.mark"), icon: "leaf.fill", tone: .sage) {
            WeekMarks()
                .padding(.horizontal, KaikuTokens.Space.s2)
                .padding(.top, KaikuTokens.Space.s3)
                .padding(.bottom, KaikuTokens.Space.s2)
                .frame(maxWidth: 520)
                .frame(maxWidth: .infinity)
            HistoryRule()
            NavigationLink(value: KaikuRoute.days) {
                KRow(icon: nil, title: T("history.days.more"))
            }
            .buttonStyle(.kPressRow())
            .accessibilityIdentifier("history.days")
        }
    }
}

/// The browse list: groups of measure cards, or one calm line while there is nothing to show.
struct HistorySummary: View {
    let model: HistoryModel
    let open: (HistoryRef) -> Void
    @Environment(AppModel.self) private var app

    var body: some View {
        if model.groups.isEmpty {
            if model.loading && model.history == nil {
                LoadingState()
            } else {
                HistoryEmpty(text: T(app.isPaired ? "history.empty" : "history.empty.unpaired"))
            }
        } else if let history = model.history {
            let today = HistoryDayKey.local(Date(), zone: history.zone)
            // An earlier copy says so before the numbers; a fresh answer notes its time quietly after them.
            if model.stale { HistoryFetchedLine(model: model) }
            ForEach(model.groups) { group in
                VStack(alignment: .leading, spacing: KaikuTokens.Space.s3) {
                    SectionHeader(group.title, icon: group.symbol, tone: group.tone)
                    HistoryGrid(items: group.measures) { m, fills in
                        Button { open(HistoryRef(group: group.key, measure: m.key)) } label: {
                            HistoryCard(measure: m, tone: group.tone, today: today, fills: fills)
                        }
                        .buttonStyle(.kPress)
                        .accessibilityIdentifier("history.card.\(m.key)")
                    }
                }
            }
            if !model.stale { HistoryFetchedLine(model: model) }
        }
    }
}

/// One calm line with Kaiku: what will appear here, and from which devices.
struct HistoryEmpty: View {
    let text: String
    var body: some View {
        KCard {
            HStack(alignment: .center, spacing: KaikuTokens.Space.s3) {
                MascotView(state: .cozy, size: KaikuTokens.Size.mascotS, tappable: false)
                Text(text).kText(.body).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .accessibilityIdentifier("history.empty")
    }
}

/// When what is on screen was fetched; says so plainly when the service could not be reached just now.
struct HistoryFetchedLine: View {
    let model: HistoryModel
    var body: some View {
        if let at = model.fetched {
            // On this device's own clock: it is about when this device asked.
            Text(T(model.stale ? "history.fetched.stale" : "history.fetched", ["when": HistoryFormat.moment(at, zone: .current)]))
                .kText(model.stale ? .footnote : .caption)
                .foregroundStyle(model.stale ? KaikuTokens.Colors.ink2 : KaikuTokens.Colors.muted).wraps()
                .frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityIdentifier("history.fetched")
        }
    }
}

/// One column on a phone, two when the pane is wide (the Mac window). In two columns the cards of a row are the
/// same height (`fills` tells a card to take its row's height).
struct HistoryGrid<Item: Identifiable, Cell: View>: View {
    let items: [Item]
    @ViewBuilder let cell: (Item, Bool) -> Cell
    @Environment(\.kaikuPaneWidth) private var width
    @Environment(\.dynamicTypeSize) private var dts

    var body: some View {
        if KAdaptiveColumns<EmptyView, EmptyView>.isWide(width, dts) {
            Grid(alignment: .topLeading, horizontalSpacing: KaikuTokens.Space.s3, verticalSpacing: KaikuTokens.Space.s3) {
                ForEach(Array(stride(from: 0, to: items.count, by: 2)), id: \.self) { i in
                    GridRow {
                        cell(items[i], true)
                        if i + 1 < items.count { cell(items[i + 1], true) } else { Color.clear.gridCellUnsizedAxes([.horizontal, .vertical]) }
                    }
                }
            }
            .fixedSize(horizontal: false, vertical: true)
        } else {
            VStack(spacing: KaikuTokens.Space.s3) { ForEach(items) { cell($0, false) } }
        }
    }
}

/// A measure on the browse list: its name, where it came from, the latest value with its day, the last seven days.
struct HistoryCard: View {
    let measure: HistoryMeasure
    let tone: KTone
    let today: String
    /// Take the height the row offers (two-column grid), so neighbours end on one line.
    var fills = false
    @Environment(\.dynamicTypeSize) private var dts

    private var latest: HistoryDay? { HistoryMath.latest(measure.days) }
    private var week: [HistoryPoint] { HistoryMath.points(measure.days, in: .ending(today, .week)) }

    /// "Robot · Today so far". Without a counted day yet (a game's practice rounds only): where the rounds came
    /// from, and that the first counted one will show here.
    private var line: String {
        var parts = [HistoryDevice.names(latest == nil ? Self.devices(of: measure.sessions) : measure.devices)]
        if let d = latest { parts.append(HistoryFormat.day(d.date, today: today, soFar: true)) }
        if latest == nil { parts.append(T(HistoryFormat.emptyKey(measure, card: true))) }
        return parts.filter { !$0.isEmpty }.joined(separator: " · ")
    }

    /// The devices a list of sessions came from, most first.
    static func devices(of sessions: [HistorySession]) -> [String] {
        Dictionary(grouping: sessions, by: \.device).sorted { ($0.value.count, $1.key) > ($1.value.count, $0.key) }.map(\.key)
    }

    var body: some View {
        Group {
            if dts.isAccessibilitySize {
                VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
                    words
                    if latest != nil { HStack(alignment: .bottom) { value; Spacer(minLength: KaikuTokens.Space.s3); spark } }
                }
            } else {
                HStack(alignment: .center, spacing: KaikuTokens.Space.s3) {
                    words.frame(maxWidth: .infinity, alignment: .leading).layoutPriority(1)
                    if latest != nil { VStack(alignment: .trailing, spacing: KaikuTokens.Space.s2) { value; spark } }
                    KChevron()
                }
            }
        }
        .padding(KaikuTokens.Space.s4)
        .frame(maxWidth: .infinity, minHeight: KaikuTokens.Size.rowMin, maxHeight: fills ? .infinity : nil, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).fill(KaikuTokens.Colors.surface)
                .kaikuShadow(KaikuTokens.Elevation.card)
        )
        .overlay(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).strokeBorder(KaikuTokens.Colors.line, lineWidth: 1))
        .contentShape(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(measure.title)
        .accessibilityValue([latest.map { HistoryFormat.value($0.value, of: measure) } ?? "", line]
            .filter { !$0.isEmpty }.joined(separator: ", "))
        .accessibilityAddTraits(.isButton)
    }

    private var words: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
            Text(measure.title).kText(.body, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
            Text(line).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps()
        }
    }

    @ViewBuilder private var value: some View {
        if let d = latest {
            Text(HistoryFormat.value(d.value, of: measure))
                .kText(.callout, weight: .semibold).monospacedDigit()
                .foregroundStyle(KaikuTokens.Colors.ink)
                .lineLimit(1).fixedSize()
        }
    }

    private var spark: some View {
        HistorySparkline(points: week, tone: tone, dots: !HistoryMath.standsOnZero(measure),
                         domain: HistoryMath.domain(week.compactMap(\.value), measure: measure))
            .frame(width: 84, height: 28)
            .accessibilityHidden(true)
    }
}

/// The last seven days, drawn as the measure's page draws them: bars standing on zero for an amount, dots at
/// their height for a level. A day with nothing recorded is a short grey tick, not a zero.
struct HistorySparkline: View {
    let points: [HistoryPoint]
    let tone: KTone
    var dots = false
    var domain: ClosedRange<Double> = 0...1

    var body: some View {
        GeometryReader { g in
            let low = domain.lowerBound, high = domain.upperBound
            HStack(alignment: .bottom, spacing: 3) {
                ForEach(points) { p in
                    ZStack(alignment: .bottom) {
                        Color.clear
                        if let v = p.value {
                            let fill = tone.ink
                            let f = high > low ? Swift.min(1, Swift.max(0, (v - low) / (high - low))) : 0.5
                            if dots {
                                Circle().fill(fill).frame(width: 6, height: 6).offset(y: -CGFloat(f) * (g.size.height - 6))
                            } else {
                                RoundedRectangle(cornerRadius: 2, style: .continuous).fill(fill)
                                    .frame(height: Swift.max(3, g.size.height * CGFloat(f)))
                            }
                        } else {
                            RoundedRectangle(cornerRadius: 1, style: .continuous).fill(KaikuTokens.Colors.line).frame(height: 2)
                        }
                    }
                    .frame(maxWidth: .infinity)
                }
            }
        }
    }
}

#if DEBUG
/// Screenshots: `-kaikuHistoryMeasure <key>` opens that measure's page once History has loaded;
/// `-kaikuHistoryRange day|week|month` picks its range.
@MainActor
enum HistoryDebug {
    static func launchRef(_ model: HistoryModel) -> HistoryRef? {
        guard let key = UserDefaults.standard.string(forKey: "kaikuHistoryMeasure"), let found = model.measure(key: key) else { return nil }
        return HistoryRef(group: found.group.key, measure: found.measure.key)
    }

    static var launchRange: HistoryRange? {
        UserDefaults.standard.string(forKey: "kaikuHistoryRange").flatMap(HistoryRange.init(rawValue:))
    }
}
#endif

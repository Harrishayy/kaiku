import SwiftUI

// An activity agreed in one place shows up everywhere at once (D50). The person said yes to something in a
// conversation with Kaiku (on the robot, on a walk, on the phone or the Mac): the cloud keeps it for the day
// (`AgreedActivity`, read with the invitation: `GET /v1/me/invitation`), the home stream says the moment it
// appears or changes, and Today shows it above the daily invitation: its sentence, where it was agreed, and one
// clear action. This file is what an item means on this device, which item gets the card, and the views; the
// list itself lives in `InvitationModel`.

// MARK: what an item is on this device

extension AgreedActivity {
    /// The screen "Start" opens on this device. Nil: there is none here (the robot's drum, a walk on the Mac, a
    /// kind this build does not know).
    func route(isPhone: Bool = KaikuPlatform.isPhone) -> KaikuRoute? {
        kind == "light_hunt" ? (isPhone ? .walk : nil) : ActivityCard.route(kind, phone: isPhone)
    }

    /// "Start" is offered: it is still open, the cloud says this device opens it, and this build has the screen.
    func startsHere(isPhone: Bool = KaikuPlatform.isPhone) -> Bool {
        state == .open && opens_here == true && route(isPhone: isPhone) != nil
    }

    /// The `kaiku://` link a notification's Start follows (the same screen as the card's button).
    func link(isPhone: Bool = KaikuPlatform.isPhone) -> String? {
        guard let route = route(isPhone: isPhone) else { return nil }
        return route == .walk ? "kaiku://walk" : "kaiku://play/\(route.rawValue)"
    }

    var icon: String {
        switch kind {
        case "drum": return "music.note"
        case "light_hunt": return "figure.walk"
        default: return ActivityCard(kind: kind, phone: true)?.icon ?? "sparkles"
        }
    }

    var tone: KTone { kind == "light_hunt" ? .sage : ActivityCard(kind: kind, phone: true)?.tone ?? .sky }

    /// The name with a capital first letter, for a row or a notification title ("a walk" → "A walk").
    var title: String { name.prefix(1).uppercased() + name.dropFirst() }

    /// Belongs to the local day `today` (a list read before midnight is not shown the day after).
    func isFor(day today: String) -> Bool { day == today }

    /// Where it was agreed, with the time: "On a walk · 14:05".
    func whereLine(timeZone: TimeZone = .current, locale: Locale = .current) -> String {
        let place = T(["robot", "glasses", "iphone", "mac", "web"].contains(surface) ? "agreed.where.\(surface)" : "agreed.where.other")
        guard let time = Self.clock(at, timeZone: timeZone, locale: locale) else { return place }
        return T("agreed.at", ["where": place, "time": time])
    }

    /// In place of the button when it cannot be started on this device: "You can start it on your iPhone."
    func elsewhereLine(here: CompanionSurface = KaikuPlatform.surface) -> String {
        // A walk through the glasses is started in the iPhone app; the web is the care team's.
        var places: [String] = []
        for word in on ?? [] {
            let screen = word == "glasses" ? "iphone" : word
            guard ["robot", "iphone", "mac"].contains(screen), screen != here.rawValue else { continue }
            let name = T("agreed.on.\(screen)")
            if !places.contains(name) { places.append(name) }
        }
        switch places.count {
        case 0: return T("agreed.else.none")
        case 1: return T("agreed.else", ["where": places[0]])
        default:
            let list = T("agreed.or", ["a": places.dropLast().joined(separator: ", "), "b": places[places.count - 1]])
            return T("agreed.else", ["where": list])
        }
    }

    /// A started or done item in calm words: "Started", "Done · 14:20". An open one: "Ready when you are".
    func stateLine(timeZone: TimeZone = .current, locale: Locale = .current) -> String {
        switch state {
        case .open: return T("agreed.state.open")
        case .started: return T("agreed.state.started")
        case .put_aside: return T("agreed.state.aside")
        case .done:
            guard let time = Self.clock(state_at, timeZone: timeZone, locale: locale) else { return T("agreed.state.done.plain") }
            return T("agreed.state.done", ["time": time])
        }
    }

    /// The local clock time of a service timestamp ("14:20").
    static func clock(_ iso: String?, timeZone: TimeZone = .current, locale: Locale = .current) -> String? {
        guard let iso, let date = KaikuTime.parse(iso) else { return nil }
        let f = DateFormatter()
        f.locale = locale; f.timeZone = timeZone
        f.dateStyle = .none; f.timeStyle = .short
        return f.string(from: date)
    }
}

// MARK: which item gets the card (pure)

/// Today's agreed items laid out: one card with its sentence and buttons, the rest as single lines, so the
/// day's path stays on screen however many there are. Put-aside items are not shown.
struct AgreedBoard: Equatable {
    /// The oldest open item this device can start, else the oldest open one.
    var card: AgreedActivity?
    /// Other open items, started and done ones, in the service's order (oldest first).
    var rows: [AgreedActivity] = []
    /// Lines left out to keep the stack short (done ones go first, the oldest first).
    var more = 0

    static let maxRows = 3

    static func make(_ items: [AgreedActivity], today: String, isPhone: Bool = KaikuPlatform.isPhone, maxRows: Int = maxRows) -> AgreedBoard {
        let shown = items.filter { $0.state != .put_aside && $0.isFor(day: today) }
        let open = shown.filter { $0.state == .open }
        let card = open.first { $0.startsHere(isPhone: isPhone) } ?? open.first
        var rows = shown.filter { $0.id != card?.id }
        var more = 0
        for state in [AgreedActivity.State.done, .started, .open] {
            while rows.count > maxRows, let i = rows.firstIndex(where: { $0.state == state }) {
                rows.remove(at: i); more += 1
            }
        }
        return AgreedBoard(card: card, rows: rows, more: more)
    }

    var isEmpty: Bool { card == nil && rows.isEmpty }
    /// Changes whenever something the stack shows changes (drives the small motion).
    var key: [String] { ([card].compactMap { $0 } + rows).map { "\($0.id):\($0.state.rawValue)" } + ["+\(more)"] }

    /// Items that turned done since the last read and were still to do then: the completion moment plays for
    /// them once, also when they were done on another device. An item first seen already done plays nothing.
    static func finished(before: [AgreedActivity], after: [AgreedActivity]) -> [String] {
        let was = Dictionary(before.map { ($0.id, $0.state) }, uniquingKeysWith: { a, _ in a })
        return after.filter { $0.state == .done && (was[$0.id] == .open || was[$0.id] == .started) }.map(\.id)
    }
}

// MARK: views

/// The agreed item's card: Kaiku's sentence, where it was agreed, and one clear action. Same look as the
/// invitation card it stands above. `start` nil: this device cannot open it, so a line says where it can be.
struct AgreedCard: View {
    let item: AgreedActivity
    var showsMascot = true
    var waiting = false
    let hear: () -> Void
    let start: (() -> Void)?
    let notNow: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s3) {
            HStack(alignment: .top, spacing: KaikuTokens.Space.s3) {
                if showsMascot {
                    MascotView(state: .happy, size: KaikuTokens.Size.mascotS, tappable: false)
                        .accessibilityHidden(true)
                }
                VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
                    Text(item.text).kText(.callout, weight: .medium).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                    Label {
                        Text(item.whereLine()).kText(.caption).wraps()
                    } icon: {
                        Image(systemName: item.icon).kText(.caption, weight: .semibold)
                    }
                    .foregroundStyle(KaikuTokens.Colors.ink2)
                    if start == nil {
                        Text(item.elsewhereLine()).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                            .accessibilityIdentifier("today.agreed.elsewhere")
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            HStack(spacing: KaikuTokens.Space.s2) {
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: KaikuTokens.Space.s2) { answers }
                    VStack(spacing: KaikuTokens.Space.s1) { answers }
                }
                .disabled(waiting)
                IconButton("speaker.wave.2", label: T("invite.hear"), action: hear)
            }
        }
        .padding(KaikuTokens.Space.s4)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).fill(KaikuTokens.Colors.honeySoft))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("today.agreed")
    }

    @ViewBuilder private var answers: some View {
        if let start {
            Button(T("agreed.start"), action: start).buttonStyle(.kPrimary).accessibilityIdentifier("today.agreed.start")
            Button(T("invite.notnow"), action: notNow).buttonStyle(.kGhost).accessibilityIdentifier("today.agreed.notnow")
        } else {
            Button(T("invite.notnow"), action: notNow).buttonStyle(.kSecondary).accessibilityIdentifier("today.agreed.notnow")
        }
    }
}

/// One agreed item as a single line: what it is and how it stands ("Lantern · Done · 14:20"). An open one that
/// can be started here carries a small "Start".
struct AgreedRow: View {
    let item: AgreedActivity
    let start: (() -> Void)?

    var body: some View {
        HStack(spacing: KaikuTokens.Space.s2) {
            Image(systemName: item.state == .done ? "checkmark.circle.fill" : item.icon)
                .kText(.footnote, weight: .semibold)
                .foregroundStyle(item.state == .done ? KaikuTokens.Colors.sage : item.tone.ink)
                .frame(width: KaikuTokens.Space.s5)
                .accessibilityHidden(true)
            Text(item.title).kText(.footnote, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).lineLimit(1)
            if start == nil {   // with "Start" beside it the line needs no "Ready when you are"; the name gets the room
                Text(item.stateLine()).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).lineLimit(1)
                    .layoutPriority(1)
            }
            Spacer(minLength: KaikuTokens.Space.s1)
            if let start {
                Button(T("agreed.start"), action: start)
                    .buttonStyle(KRowActionStyle())
                    .accessibilityIdentifier("today.agreed.row.start")
            }
        }
        .padding(.leading, KaikuTokens.Space.s3)
        .padding(.trailing, start == nil ? KaikuTokens.Space.s3 : KaikuTokens.Space.s1)
        .frame(minHeight: KaikuTokens.Size.tapMin)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.md, style: .continuous).fill(KaikuTokens.Colors.surface2))
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("today.agreed.row.\(item.state.rawValue)")
    }
}

/// The small "Start" at the end of a single line: one line that never wraps or shrinks,
/// a full-height touch target, and a light pill so it reads as a button on the row's tint.
struct KRowActionStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .kText(.footnote, weight: .semibold)
            .foregroundStyle(KaikuTokens.Colors.clay)
            .lineLimit(1)
            .fixedSize()
            .padding(.horizontal, KaikuTokens.Space.s3)
            .frame(minHeight: KaikuTokens.Space.s6)
            .background(Capsule().fill(KaikuTokens.Colors.surface.opacity(configuration.isPressed ? 0.6 : 1)))
            .padding(.horizontal, KaikuTokens.Space.s1)
            .frame(minHeight: KaikuTokens.Size.tapMin)
            .contentShape(Rectangle())
            .kPointer()
    }
}

/// The card and the lines under it. Arrives and leaves with a small motion; nothing else on Today moves more
/// than the room it takes.
struct AgreedStack: View {
    let board: AgreedBoard
    var showsMascot = true
    var waiting: Set<String> = []
    let hear: (AgreedActivity) -> Void
    let start: (AgreedActivity) -> Void
    let notNow: (AgreedActivity) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
            if let item = board.card {
                AgreedCard(item: item, showsMascot: showsMascot, waiting: waiting.contains(item.id),
                           hear: { hear(item) },
                           start: item.startsHere() ? { start(item) } : nil,
                           notNow: { notNow(item) })
                    .transition(.opacity.combined(with: .scale(scale: 0.97, anchor: .top)))
                    .id(item.id)
            }
            ForEach(board.rows) { item in
                AgreedRow(item: item, start: item.startsHere() && !waiting.contains(item.id) ? { start(item) } : nil)
                    .transition(.opacity)
            }
            if board.more > 0 {
                Text(T("agreed.more", n: board.more)).kText(.caption).foregroundStyle(KaikuTokens.Colors.muted)
                    .padding(.leading, KaikuTokens.Space.s3)
            }
        }
    }
}

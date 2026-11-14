#if os(macOS)
import SwiftUI

/// What the person can do on the quick-talk surface.
public enum QuickTalkCommand: Sendable {
    /// The pill's two buttons at rest (start speaking, open Kaiku), and its two while a conversation is on.
    case start, openKaiku, show, end
    /// The popup.
    case microphone, voice, collapse, close, continueInKaiku, help, openActivity, putActivityAside
}

public extension QuickTalkModel {
    func perform(_ command: QuickTalkCommand) {
        switch command {
        case .start, .show: start()
        case .openKaiku: hovering = false; openMain(nil)
        case .end: end()
        case .microphone: toggleMicrophone()
        case .voice: toggleVoice()
        case .collapse: collapse()
        case .close: close()
        case .continueInKaiku: continueInKaiku()
        case .help: help()
        case .openActivity: openActivity()
        case .putActivityAside: putActivityAside()
        }
    }
}

/// The surface is one shape that grows (like the notch island; never a second window appearing): the bar swells
/// into the pill quickly under the pointer, and into the popup on the tokens' gentle spring. Reduce Motion gets a
/// crossfade. Reactions pop in with `overshoot` (design/motion.md: pop-ins).
enum QuickTalkMotion {
    static let grow = KaikuTokens.Spring.gentle
    static let hover = KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast)
    static let fade = Animation.easeInOut(duration: KaikuTokens.Duration.crossfade)
    static let resize = KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast)
    static let pop = KaikuTokens.Easing.overshoot(KaikuTokens.Duration.base)

    static func animation(to stage: QuickTalkStage, reduceMotion: Bool) -> Animation {
        reduceMotion ? fade : stage == .popup ? grow : hover
    }
}

/// The whole quick-talk surface, drawn from plain values (so every stage can be rendered on its own): a thin
/// Kaiku-coloured bar at rest; a pill with exactly two buttons under the pointer; the popup card. While a
/// conversation is on and the popup is put away, the bar is a little wider and carries the voice meter.
public struct QuickTalkSurface: View {
    let stage: QuickTalkStage
    let display: QuickTalkDisplay
    /// A conversation is on.
    let live: Bool
    /// The meter's reading when it is drawn from a value (snapshots); the model's own otherwise.
    var meter: QuickTalkMeter?
    var model: QuickTalkModel?
    var loopStart: Date?
    let perform: (QuickTalkCommand) -> Void
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    public init(stage: QuickTalkStage, display: QuickTalkDisplay, live: Bool = false, meter: QuickTalkMeter? = nil,
                model: QuickTalkModel? = nil, loopStart: Date? = nil, perform: @escaping (QuickTalkCommand) -> Void) {
        self.stage = stage; self.display = display; self.live = live; self.meter = meter
        self.model = model; self.loopStart = loopStart; self.perform = perform
    }

    public var body: some View {
        ZStack(alignment: .leading) {
            // Reduce Motion: nothing grows or moves, one stage fades into the next.
            if reduceMotion { shape.id(stage).transition(.opacity) } else { shape }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        .animation(QuickTalkMotion.animation(to: stage, reduceMotion: reduceMotion), value: stage)
        .animation(reduceMotion ? nil : QuickTalkMotion.resize, value: display.cardSize)
        .animation(reduceMotion ? QuickTalkMotion.fade : QuickTalkMotion.hover, value: live)
        .tint(KaikuTokens.Colors.clay)
    }

    private var shape: some View {
        let card = display.cardSize
        let size = QuickTalkLayout.size(stage, live: live, card: card)
        let outline = RoundedRectangle(cornerRadius: QuickTalkLayout.radius(stage, size: size), style: .continuous)
        let popup = stage == .popup
        let shadow = popup ? KaikuTokens.Elevation.raised
            : stage == .pill ? KaikuTokens.Elevation.card : KaikuShadow(radius: 0, y: 0, opacity: 0)
        return ZStack(alignment: .leading) {
            if popup {
                QuickTalkCard(display: display, chrome: false, loopStart: loopStart, perform: perform)
                    .frame(width: card.width, height: card.height)
                    .transition(.opacity)
            } else if stage == .pill {
                pill.frame(width: QuickTalkLayout.pill.width, height: QuickTalkLayout.pill.height).transition(.opacity)
            } else if stage == .bar, live {
                Group {
                    if let model { QuickTalkMeterLive(model: model) } else { QuickTalkMeterView(meter: meter ?? QuickTalkMeter(), at: loopStart) }
                }
                .frame(width: QuickTalkLayout.barLive.width, height: QuickTalkLayout.barLive.height)
                .transition(.opacity)
            }
        }
        .frame(width: size.width, height: size.height, alignment: .leading)
        .clipShape(outline)
        .background(outline.fill(popup ? KaikuTokens.Colors.surface : KaikuTokens.Colors.clay).kaikuShadow(shadow))
        .overlay(outline.strokeBorder(KaikuTokens.Colors.line.opacity(popup ? 1 : 0), lineWidth: 1))
        .opacity(stage == .hidden ? 0 : 1)
        .padding(.leading, QuickTalkLayout.inset(stage))
        .accessibilityElement(children: .contain)
        .accessibilityLabel(T(live && !popup ? "quick.live" : "quick.title"))
    }

    /// Exactly two buttons. At rest: start speaking, open Kaiku. While a conversation is on: show it, end it.
    private var pill: some View {
        VStack(spacing: KaikuTokens.Space.s2) {
            if live {
                pillButton("text.bubble.fill", T("quick.show"), primary: true) { perform(.show) }
                pillButton("phone.down.fill", T("call.end"), primary: false) { perform(.end) }
            } else {
                pillButton("mic.fill", T("quick.start"), primary: true) { perform(.start) }
                pillButton("macwindow", T("mac.open"), primary: false) { perform(.openKaiku) }
            }
        }
    }

    private func pillButton(_ symbol: String, _ label: String, primary: Bool, _ action: @escaping () -> Void) -> some View {
        let s = QuickTalkLayout.pillButton
        return Button(action: action) {
            Image(systemName: symbol).kText(.footnote, weight: .semibold)
                .foregroundStyle(primary ? KaikuTokens.Colors.clay : KaikuTokens.Colors.clayInk)
                .frame(width: s, height: s)
                .background(Circle().fill(KaikuTokens.Colors.clayInk.opacity(primary ? 1 : 0.2)))
                .contentShape(Circle())
        }
        .buttonStyle(.kPress)
        .help(label)
        .accessibilityLabel(label)
    }
}

/// The voice in the bar: five soft dashes that widen with the person's voice and breathe while Kaiku speaks.
/// Still, and dimmer, while the microphone is muted and Kaiku is quiet. Reduce Motion: no wobble.
struct QuickTalkMeterView: View {
    let meter: QuickTalkMeter
    /// Snapshots pin the wobble.
    var at: Date?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let quiet = !meter.micOpen && !meter.kaikuSpeaking
        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: reduceMotion || quiet || at != nil)) { tl in
            let t = (at ?? tl.date).timeIntervalSinceReferenceDate
            let still = reduceMotion || quiet
            let voice = meter.kaikuSpeaking ? max(meter.level, 0.6) : meter.level
            VStack(spacing: 5) {
                ForEach(0..<5, id: \.self) { i in
                    let wave = still ? 0.5 : 0.5 + 0.5 * sin(t * 6.5 + Double(i) * 1.3)
                    Capsule().fill(KaikuTokens.Colors.clayInk)
                        .frame(width: 3 + 5 * voice * (0.45 + 0.55 * wave), height: 3)
                }
            }
            .opacity(quiet ? 0.5 : 1)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityHidden(true)
    }
}

/// The meter on the model's own reading (only this small view follows the level as it changes).
private struct QuickTalkMeterLive: View {
    let model: QuickTalkModel
    var body: some View { QuickTalkMeterView(meter: model.meter) }
}

/// The popup card: Kaiku on the left (its face follows the call and shows a moment when something happens; a
/// ring while the microphone is open; a small reaction pops up beside it), and beside it the call's one short
/// state, the captions (the person's words as they are transcribed, Kaiku's line as it speaks) and small
/// controls: mute me, mute Kaiku, put the popup away (the conversation goes on), end, and a quiet "Continue in
/// Kaiku". With captions off Kaiku stands alone. When Kaiku cannot listen the card says why in one line and
/// offers the one thing that helps. Draws a `QuickTalkDisplay`, nothing else.
public struct QuickTalkCard: View {
    let display: QuickTalkDisplay
    /// False inside the surface, which draws the one growing shape itself.
    var chrome = true
    /// Layout snapshots pin Kaiku's loop.
    var loopStart: Date?
    let perform: (QuickTalkCommand) -> Void
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    public init(display: QuickTalkDisplay, chrome: Bool = true, loopStart: Date? = nil, perform: @escaping (QuickTalkCommand) -> Void) {
        self.display = display
        self.chrome = chrome
        self.loopStart = loopStart
        self.perform = perform
    }

    private var compact: Bool { display.cardSize == QuickTalkLayout.compact }

    public var body: some View {
        let size = display.cardSize
        let shape = RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous)
        Group {
            if compact {
                VStack(spacing: KaikuTokens.Space.s1) {
                    kaiku
                    status.padding(.bottom, KaikuTokens.Space.s1)
                    HStack(spacing: KaikuTokens.Space.s2) { microphone; voice; collapse; end }
                    continueLink
                }
            } else {
                HStack(alignment: .top, spacing: KaikuTokens.Space.s3) {
                    kaiku.frame(maxHeight: .infinity, alignment: .center)
                    VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
                        HStack(spacing: KaikuTokens.Space.s2) {
                            status
                            Spacer(minLength: KaikuTokens.Space.s1)
                            if display.conversational { continueLink }
                        }
                        words.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                        if let card = display.activity, display.conversational { activity(card) }
                        controls
                    }
                }
            }
        }
        .padding(QuickTalkLayout.padding)
        .frame(width: size.width, height: size.height)
        .background { if chrome { shape.fill(KaikuTokens.Colors.surface).kaikuShadow(KaikuTokens.Elevation.raised) } }
        .overlay { if chrome { shape.strokeBorder(KaikuTokens.Colors.line, lineWidth: 1) } }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(T("quick.title"))
    }

    // MARK: Kaiku, its reaction, and the call's one short state

    private var kaiku: some View {
        let m = QuickTalkLayout.mascot
        return ZStack {
            if display.micLive { QuickTalkRing(size: m + KaikuTokens.Space.s2, active: display.state == .hearing) }
            MascotView(state: display.mascot, size: m, tappable: false, cycleStart: loopStart)
        }
        .frame(width: m + KaikuTokens.Space.s3, height: m + KaikuTokens.Space.s3)
        .overlay(alignment: .topTrailing) {
            ZStack {
                if let reaction = display.reaction {
                    QuickTalkReactionGlyph(reaction: reaction)
                        .transition(reduceMotion ? .opacity : .scale(scale: 0.3, anchor: .bottomLeading).combined(with: .opacity))
                        .id(reaction)
                } else if display.state == .thinking {
                    QuickTalkThinkingDots(at: loopStart).transition(.opacity)
                }
            }
            .frame(width: 22, height: 22)
            .offset(x: 4, y: -2)
            .animation(reduceMotion ? QuickTalkMotion.fade : QuickTalkMotion.pop, value: display.reaction)
            .animation(QuickTalkMotion.fade, value: display.state)
        }
        .accessibilityHidden(true)
    }

    /// A sage dot = the microphone is open (the call bar's colour for it); no dot, muted words = it is not.
    private var status: some View {
        HStack(spacing: KaikuTokens.Space.s1 + 2) {
            if display.micLive {
                Circle().fill(KaikuTokens.Colors.sage).frame(width: 7, height: 7)
            }
            Text(T(display.statusKey)).kText(.micro)
                .foregroundStyle(display.micLive ? KaikuTokens.Colors.ink : KaikuTokens.Colors.muted)
                .lineLimit(1).fixedSize()
        }
        .frame(minHeight: 18)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(T(display.statusKey) + ". " + T(display.micLive ? "quick.mic.on" : "quick.mic.off"))
    }

    // MARK: captions, or the one line that says why not

    @ViewBuilder private var words: some View {
        if let key = display.lineKey {
            Text(T(key)).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink).wraps()
        } else if !display.conversational {
            EmptyView()
        } else if !display.captions {
            EmptyView()   // only with an activity card: Kaiku, the card and the controls
        } else if display.person == nil && display.kaiku == nil {
            Text(T(display.micLive ? "quick.hint" : "quick.hint.muted")).kText(.footnote)
                .foregroundStyle(KaikuTokens.Colors.muted).wraps()
        } else {
            VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
                // The newest words of each (a long line keeps its end); VoiceOver gets the whole line.
                if let person = display.person {
                    let alone = display.kaiku == nil
                    Text(QuickTalkCaptions.tail(person, limit: alone ? QuickTalkCaptions.personAlone : QuickTalkCaptions.personWithReply))
                        .kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2)
                        .lineLimit(alone ? 4 : 1).truncationMode(.head)
                        .accessibilityLabel(T("quick.a11y.you", ["text": person]))
                }
                if let line = display.kaiku {
                    Text(QuickTalkCaptions.tail(line, limit: QuickTalkCaptions.kaikuLimit))
                        .kText(.footnote, weight: .medium).foregroundStyle(KaikuTokens.Colors.ink)
                        .lineLimit(3).truncationMode(.head)
                        .accessibilityLabel(T("quick.a11y.kaiku", ["text": line]))
                }
            }
            .animation(nil, value: display)
        }
    }

    // MARK: the one activity Kaiku suggests (the call's card, small)

    private func activity(_ card: ActivityCard) -> some View {
        HStack(spacing: KaikuTokens.Space.s2) {
            Image(systemName: card.icon).kText(.caption, weight: .semibold).foregroundStyle(card.tone.ink)
                .frame(width: QuickTalkLayout.control, height: QuickTalkLayout.control)
                .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.sm, style: .continuous).fill(card.tone.soft))
                .accessibilityHidden(true)
            Text(T(card.titleKey)).kText(.caption).foregroundStyle(KaikuTokens.Colors.ink)
                .lineLimit(1).minimumScaleFactor(0.85)
            Spacer(minLength: KaikuTokens.Space.s1)
            pill(T("card.open")) { perform(.openActivity) }
            Button { perform(.putActivityAside) } label: {
                Image(systemName: "xmark").kText(.micro, weight: .bold).foregroundStyle(KaikuTokens.Colors.muted)
                    .frame(width: 22, height: QuickTalkLayout.control).contentShape(Rectangle())
            }
            .buttonStyle(.kPress)
            .help(T("card.aside"))
            .accessibilityLabel(T("card.aside"))
        }
        .padding(.horizontal, KaikuTokens.Space.s2)
        .frame(height: QuickTalkLayout.activityRow - KaikuTokens.Space.s2)
        .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.md, style: .continuous).fill(KaikuTokens.Colors.bg))
        .overlay(RoundedRectangle(cornerRadius: KaikuTokens.Radius.md, style: .continuous).strokeBorder(KaikuTokens.Colors.line, lineWidth: 1))
        .accessibilityElement(children: .contain)
    }

    // MARK: controls

    @ViewBuilder private var controls: some View {
        HStack(spacing: KaikuTokens.Space.s2) {
            if display.conversational {
                microphone
                voice
                Spacer(minLength: KaikuTokens.Space.s1)
                collapse
                end
            } else {
                if let key = display.helpKey { pill(T(key)) { perform(.help) } }
                Spacer(minLength: KaikuTokens.Space.s1)
                round("xmark", T("quick.close")) { perform(.close) }
            }
        }
    }

    /// The call bar's convention: a control is filled while it is muting.
    private var microphone: some View {
        round(display.micLive ? "mic.fill" : "mic.slash.fill", T(display.micLive ? "call.mute.me" : "call.unmute.me"),
              filled: !display.micLive) { perform(.microphone) }
    }

    private var voice: some View {
        round(display.voiceMuted ? "speaker.slash.fill" : "speaker.wave.2.fill",
              T(display.voiceMuted ? "call.unmute.kaiku" : "call.mute.kaiku"), filled: display.voiceMuted) { perform(.voice) }
    }

    /// Back to the bar: the conversation goes on.
    private var collapse: some View { round("chevron.left", T("quick.collapse")) { perform(.collapse) } }

    /// End call (the call bar's ink button).
    private var end: some View {
        Button { perform(.end) } label: {
            Image(systemName: "phone.down.fill").kText(.caption, weight: .semibold)
                .foregroundStyle(KaikuTokens.Colors.bg)
                .frame(width: QuickTalkLayout.control, height: QuickTalkLayout.control)
                .background(Circle().fill(KaikuTokens.Colors.ink))
                .contentShape(Circle())
        }
        .buttonStyle(.kPress)
        .help(T("call.end"))
        .accessibilityLabel(T("call.end"))
    }

    private var continueLink: some View {
        Button { perform(.continueInKaiku) } label: {
            Text(T("quick.continue")).kText(.micro)
                .foregroundStyle(KaikuTokens.Colors.clay)
                .lineLimit(1).fixedSize()
                .frame(minHeight: 18)
                .contentShape(Rectangle())
        }
        .buttonStyle(.kPress)
    }

    private func pill(_ text: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(text).kText(.caption, weight: .semibold)
                .foregroundStyle(KaikuTokens.Colors.clayInk)
                .lineLimit(1).fixedSize()
                .padding(.horizontal, KaikuTokens.Space.s3)
                .frame(height: QuickTalkLayout.control)
                .background(Capsule().fill(KaikuTokens.Colors.clay))
                .contentShape(Capsule())
        }
        .buttonStyle(.kPress)
    }

    private func round(_ symbol: String, _ label: String, filled: Bool = false, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol).kText(.caption, weight: .semibold)
                .foregroundStyle(filled ? KaikuTokens.Colors.clayInk : KaikuTokens.Colors.ink)
                .frame(width: QuickTalkLayout.control, height: QuickTalkLayout.control)
                .background(Circle().fill(filled ? KaikuTokens.Colors.clay : KaikuTokens.Colors.surface2))
                .contentShape(Circle())
        }
        .buttonStyle(.kPress)
        .help(label)
        .accessibilityLabel(label)
    }
}

/// A thin ring around Kaiku while the microphone is open; it breathes while the person is talking.
private struct QuickTalkRing: View {
    let size: CGFloat
    let active: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: reduceMotion || !active)) { tl in
            let pulse = reduceMotion || !active ? 0.5 : 0.5 + 0.5 * sin(tl.date.timeIntervalSinceReferenceDate * 2.4)
            Circle()
                .strokeBorder(KaikuTokens.Colors.clay.opacity(0.35 + 0.4 * pulse), lineWidth: 2)
                .frame(width: size, height: size)
                .scaleEffect(1 + 0.04 * pulse)
        }
        .accessibilityHidden(true)
    }
}

/// The small reaction beside Kaiku: a drawn glyph in the mascot's own colours (its sparkle gold, its scarf, honey).
/// Never a system emoji.
public struct QuickTalkReactionGlyph: View {
    let reaction: QuickTalkReaction
    public init(reaction: QuickTalkReaction) { self.reaction = reaction }
    public var body: some View {
        Group {
            switch reaction {
            case .sparkle: SparkleShape().fill(KaikuTokens.Colors.mascotSparkle)
            case .heart: HeartShape().fill(KaikuTokens.Colors.mascotScarf)
            case .curious:
                CuriousShape().stroke(KaikuTokens.Colors.honey, style: StrokeStyle(lineWidth: 2.6, lineCap: .round, lineJoin: .round))
            }
        }
        .frame(width: 18, height: 18)
        .accessibilityHidden(true)
    }

    /// A four-point sparkle with soft waists, like the ones Kaiku throws when it is happy.
    struct SparkleShape: Shape {
        func path(in r: CGRect) -> Path {
            let c = CGPoint(x: r.midX, y: r.midY), w = r.width / 2, h = r.height / 2, k: CGFloat = 0.22
            var p = Path()
            p.move(to: CGPoint(x: c.x, y: c.y - h))
            p.addQuadCurve(to: CGPoint(x: c.x + w, y: c.y), control: CGPoint(x: c.x + w * k, y: c.y - h * k))
            p.addQuadCurve(to: CGPoint(x: c.x, y: c.y + h), control: CGPoint(x: c.x + w * k, y: c.y + h * k))
            p.addQuadCurve(to: CGPoint(x: c.x - w, y: c.y), control: CGPoint(x: c.x - w * k, y: c.y + h * k))
            p.addQuadCurve(to: CGPoint(x: c.x, y: c.y - h), control: CGPoint(x: c.x - w * k, y: c.y - h * k))
            p.closeSubpath()
            return p
        }
    }

    struct HeartShape: Shape {
        func path(in r: CGRect) -> Path {
            let w = r.width, h = r.height
            func pt(_ x: CGFloat, _ y: CGFloat) -> CGPoint { CGPoint(x: r.minX + w * x, y: r.minY + h * y) }
            var p = Path()
            p.move(to: pt(0.5, 0.94))
            p.addCurve(to: pt(0.04, 0.36), control1: pt(0.30, 0.80), control2: pt(0.04, 0.60))
            p.addCurve(to: pt(0.5, 0.26), control1: pt(0.04, 0.04), control2: pt(0.42, 0.02))
            p.addCurve(to: pt(0.96, 0.36), control1: pt(0.58, 0.02), control2: pt(0.96, 0.04))
            p.addCurve(to: pt(0.5, 0.94), control1: pt(0.96, 0.60), control2: pt(0.70, 0.80))
            p.closeSubpath()
            return p
        }
    }

    /// A small question hook and its dot: Kaiku is curious.
    struct CuriousShape: Shape {
        func path(in r: CGRect) -> Path {
            let w = r.width, h = r.height
            func pt(_ x: CGFloat, _ y: CGFloat) -> CGPoint { CGPoint(x: r.minX + w * x, y: r.minY + h * y) }
            var p = Path()
            p.move(to: pt(0.28, 0.30))
            p.addCurve(to: pt(0.50, 0.62), control1: pt(0.30, -0.06), control2: pt(0.96, 0.20))
            p.move(to: pt(0.50, 0.90))
            p.addLine(to: pt(0.50, 0.91))
            return p
        }
    }
}

/// Three small dots beside Kaiku while it thinks.
private struct QuickTalkThinkingDots: View {
    var at: Date?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 20, paused: reduceMotion || at != nil)) { tl in
            let t = (at ?? tl.date).timeIntervalSinceReferenceDate
            HStack(spacing: 3) {
                ForEach(0..<3, id: \.self) { i in
                    Circle().fill(KaikuTokens.Colors.muted).frame(width: 4, height: 4)
                        .opacity(reduceMotion ? 0.7 : 0.35 + 0.65 * (0.5 + 0.5 * sin(t * 4 - Double(i) * 0.8)))
                }
            }
        }
        .accessibilityHidden(true)
    }
}

/// The content of the quick-talk window: the one surface, on the model.
public struct QuickTalkPanelHost: View {
    let model: QuickTalkModel
    public init(model: QuickTalkModel) { self.model = model }
    public var body: some View {
        QuickTalkSurface(stage: model.stage, display: model.display, live: model.isLive, model: model) { model.perform($0) }
    }
}

/// You → Quick talk (Mac only): a small card in the page's own pattern (a switch, and a row that opens the rest).
/// On/off with the key combination; then the bar at the screen edge, the double tap and captions. Stored by
/// `QuickTalkModel` in UserDefaults.
struct QuickTalkSettingsSection: View {
    private let model = QuickTalkModel.shared
    @State private var showMore = false

    var body: some View {
        @Bindable var model = model
        KSection {
            KToggleRow(icon: "waveform", tint: KaikuTokens.Colors.clay, title: T("quick.title"),
                       detail: T("quick.set.on.d", ["keys": T("quick.keys")]), isOn: $model.enabled)
            if model.enabled {
                KDivider()
                Button {
                    withAnimation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast)) { showMore.toggle() }
                } label: {
                    KRow(icon: "slider.horizontal.3", tint: KaikuTokens.Colors.clay,
                         title: T(showMore ? "quick.set.less" : "quick.set.more"), accessory: showMore ? .none : .chevron)
                }
                .buttonStyle(.kPressRow())
                if showMore {
                    KDivider()
                    KToggleRow(title: T("quick.set.bar"), detail: T("quick.set.bar.d"), isOn: $model.showBar)
                    KDivider()
                    VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
                        Text(T("quick.set.double")).kText(.body, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                        Text(T("quick.set.double.d")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps()
                        KSegmented([(QuickTalkDoubleTapKey.off, T("quick.set.double.off")),
                                    (.option, T("quick.set.double.option")),
                                    (.control, T("quick.set.double.control"))], selection: $model.doubleTap)
                    }
                    .padding(.horizontal, KaikuTokens.Space.s4)
                    .padding(.vertical, KaikuTokens.Space.s3)
                    KDivider()
                    KToggleRow(title: T("quick.set.captions"), detail: T("quick.set.captions.d"), isOn: $model.captions)
                }
            }
        }
    }
}
#endif

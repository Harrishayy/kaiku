import SwiftUI

/// Kaiku's states (mascot.spec.json → states). The view draws the spec geometry with Canvas and evaluates the
/// state's pose + tracks, the blink schedule, events (yawn), the tap ear flick, the dial ear and the look offset.
public enum MascotState: String, CaseIterable, Sendable {
    case idle, listening, thinking, happy, cheering, breathing, sleepy, walking, cozy, speaking, peek

    /// GET /v1/me → mascot.mood. `crisis` has no mascot (the crisis screen replaces everything).
    public init(mood: MascotMood?) {
        switch mood {
        case .happy: self = .happy
        case .cozy: self = .cozy
        default: self = .idle
        }
    }
}

/// Per-view animation bookkeeping (a reference, so writing to it while drawing doesn't re-render).
final class MascotClock {
    var stateStart = Date()
    var state: MascotState?
    var nextBlink = Date().addingTimeInterval(Double.random(in: 2...4))
    var blinkStart: Date?
    var secondBlink: Date?
    var nextEvent: Date?
    var eventStart: Date?
    var tapStart: Date?
}

public struct MascotView: View {
    public var state: MascotState
    public var size: CGFloat
    /// Weather check: dial value 1..5 drives the ear (direct manipulation, follows even with Reduce Motion).
    public var dial: Double?
    /// Eyes look offset in −1..1 (cursor on Mac, tilt on iPhone).
    public var look: CGSize
    public var tappable: Bool
    /// Loop anchor: the cycle starts here (breath guide sync so phone, Mac and robot breathe together).
    public var cycleStart: Date?

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.kaikuMascotOnDark) private var onDark
    @State private var clock = MascotClock()
    @State private var animatedDial: Double = 0
    @State private var hoverLook: CGSize = .zero

    public init(state: MascotState, size: CGFloat = KaikuTokens.Size.mascotL, dial: Double? = nil,
                look: CGSize = .zero, tappable: Bool = true, cycleStart: Date? = nil) {
        self.state = state
        self.size = size
        self.dial = dial
        self.look = look
        self.tappable = tappable
        self.cycleStart = cycleStart
    }

    private let spec = MascotSpec.shared

    public var body: some View {
        TimelineView(.animation(minimumInterval: reduceMotion ? 0.1 : 1.0 / 60, paused: false)) { tl in
            Canvas(rendersAsynchronously: false) { ctx, sz in
                draw(ctx: ctx, size: sz, now: tl.date)
            }
        }
        .frame(width: size, height: size)
        .contentShape(Circle().inset(by: size * 0.12))
        .onTapGesture { if tappable { tap() } }
        #if os(macOS)
        .onContinuousHover { phase in
            switch phase {
            case .active(let p):
                hoverLook = CGSize(width: (p.x / size - 0.5) * 2, height: (p.y / size - 0.5) * 2)
            case .ended: hoverLook = .zero
            }
        }
        #endif
        .onChange(of: dial) { _, new in
            guard let new else { return }
            if reduceMotion { animatedDial = new } else { withAnimation(KaikuTokens.Spring.gentle) { animatedDial = new } }
        }
        .onAppear { animatedDial = dial ?? 3 }
        .accessibilityElement()
        .accessibilityLabel(T("a11y.mascot"))
        .accessibilityAddTraits(tappable ? .isButton : [])
        .accessibilityAction { if tappable { tap() } }
    }

    private func tap() {
        let now = Date()
        if let t = clock.tapStart, now.timeIntervalSince(t) < spec.tapDuration { return }
        clock.tapStart = now
        Haptics.tapKaiku()
    }

    // MARK: evaluation

    private struct Xf {
        var translate = CGSize.zero
        var rotate = 0.0
        var scale = CGSize(width: 1, height: 1)
        var opacity: Double?
    }

    private func value(of track: MascotSpec.Track, at phase: Double, pose: MascotSpec.Value?) -> MascotSpec.Value? {
        let keys = track.keys
        guard let first = keys.first else { return nil }
        let resolve: (MascotSpec.Value?) -> MascotSpec.Value = { $0 ?? pose ?? .scalar(0) }
        if phase <= first.0 { return resolve(first.1) }
        for i in 1..<keys.count where phase <= keys[i].0 {
            let (t0, v0) = keys[i - 1], (t1, v1) = keys[i]
            let span = max(1e-6, t1 - t0)
            let e = KaikuCurve.ease(track.easing, (phase - t0) / span)
            return .lerp(resolve(v0), resolve(v1), e)
        }
        return resolve(keys.last!.1)
    }

    private func apply(_ v: MascotSpec.Value, _ prop: MascotSpec.Prop, to x: inout Xf) {
        switch prop {
        case .translate: x.translate = CGSize(width: v.a, height: v.b)
        case .rotate: x.rotate = v.a
        case .scale: x.scale = CGSize(width: v.a, height: v.b)
        case .opacity: x.opacity = v.a
        }
    }

    private func poseValue(_ s: MascotSpec.State, _ part: String, _ prop: MascotSpec.Prop) -> MascotSpec.Value? {
        s.pose[part]?[prop]
    }

    private func transforms(now: Date) -> [String: Xf] {
        var effective = state
        if clock.state != state { clock.state = state; clock.stateStart = now; clock.nextEvent = nil; clock.eventStart = nil }
        var t = now.timeIntervalSince(clock.stateStart)
        // cheering plays two cycles, then settles into happy.
        if state == .cheering, let s = spec.states["cheering"], t > s.duration * 2 { effective = .happy; t -= s.duration * 2 }
        guard let s = spec.states[effective.rawValue] else { return [:] }
        var out: [String: Xf] = [:]
        for (part, props) in s.pose { for (p, v) in props { apply(v, p, to: &out[part, default: Xf()]) } }

        let motion = !reduceMotion
        if motion {
            var phase: Double
            if let c = cycleStart, s.loop {   // shared loop start (breath sync; island snapshots)
                phase = now.timeIntervalSince(c).truncatingRemainder(dividingBy: s.duration) / s.duration
                if phase < 0 { phase += 1 }
            } else {
                phase = s.loop ? (t.truncatingRemainder(dividingBy: s.duration) / s.duration) : min(1, t / s.duration)
            }
            for tr in s.tracks {
                if let v = value(of: tr, at: phase, pose: poseValue(s, tr.part, tr.prop)) { apply(v, tr.prop, to: &out[tr.part, default: Xf()]) }
            }
            // events (sleepy yawn)
            for (_, ev) in s.events {
                if clock.nextEvent == nil { clock.nextEvent = now.addingTimeInterval(Double.random(in: ev.interval)) }
                if clock.eventStart == nil, let n = clock.nextEvent, now >= n { clock.eventStart = now }
                if let es = clock.eventStart {
                    let et = now.timeIntervalSince(es) / ev.duration
                    if et >= 1 {
                        clock.eventStart = nil
                        clock.nextEvent = now.addingTimeInterval(Double.random(in: ev.interval))
                    } else {
                        for tr in ev.tracks {
                            if let v = value(of: tr, at: et, pose: poseValue(s, tr.part, tr.prop)) { apply(v, tr.prop, to: &out[tr.part, default: Xf()]) }
                        }
                    }
                }
            }
            // blink
            if let mode = spec.blinkModes[s.blink] {
                if clock.blinkStart == nil, now >= clock.nextBlink {
                    clock.blinkStart = now
                    if mode.doubleChance > 0, Double.random(in: 0...1) < mode.doubleChance {
                        clock.secondBlink = now.addingTimeInterval(mode.duration + mode.doubleGap)
                    }
                }
                if clock.blinkStart == nil, let sb = clock.secondBlink, now >= sb { clock.blinkStart = now; clock.secondBlink = nil }
                if let bs = clock.blinkStart {
                    let bt = now.timeIntervalSince(bs) / mode.duration
                    if bt >= 1 {
                        clock.blinkStart = nil
                        if clock.secondBlink == nil { clock.nextBlink = now.addingTimeInterval(Double.random(in: mode.interval)) }
                    } else {
                        for part in spec.blinkParts {
                            let pose = out[part]?.translate ?? .zero
                            let open = MascotSpec.Value.pair(pose.width, pose.height)
                            let e = KaikuCurve.ease(spec.blinkEasing, bt < 0.5 ? bt * 2 : (1 - bt) * 2)
                            apply(.lerp(open, spec.blinkClosed, e), .translate, to: &out[part, default: Xf()])
                        }
                    }
                }
            }
            // tap ear flick (relative)
            if let ts = clock.tapStart {
                let ft = now.timeIntervalSince(ts) / spec.tapDuration
                if ft < 1, let v = value(of: spec.tap, at: ft, pose: .scalar(0)) { out[spec.tap.part, default: Xf()].rotate += v.a }
            }
            // look
            let l = look == .zero ? hoverLook : look
            if l != .zero {
                for eye in ["eye-l", "eye-r"] {
                    out[eye, default: Xf()].translate.width += max(-1, min(1, l.width)) * spec.lookMax.width
                    out[eye, default: Xf()].translate.height += max(-1, min(1, l.height)) * spec.lookMax.height
                }
            }
        } else if effective == .breathing {
            // Reduce Motion breath guide: Kaiku still; the glow cross-fades 0.55 ↔ 1.0 every 5 s.
            let c = cycleStart ?? clock.stateStart
            let ph = now.timeIntervalSince(c).truncatingRemainder(dividingBy: s.duration)
            let half = s.duration / 2
            let fade = KaikuTokens.Duration.crossfade
            let inhale = ph < half
            let into = inhale ? ph : ph - half
            let k = min(1, into / fade)
            let target = inhale ? 1.0 : 0.55, from = inhale ? 0.55 : 1.0
            out["glow", default: Xf()].opacity = from + (target - from) * k
        }
        if dial != nil {
            out["ear", default: Xf()].rotate = spec.earAngle(forDial: reduceMotion ? (dial ?? 3) : animatedDial)
        }
        return out
    }

    // MARK: drawing

    private func draw(ctx: GraphicsContext, size: CGSize, now: Date) {
        let xf = transforms(now: now)
        var c = ctx
        let k = min(size.width, size.height) / spec.viewBox.width
        c.scaleBy(x: k, y: k)
        c.translateBy(x: -spec.viewBox.minX, y: -spec.viewBox.minY)
        let glow = GlowClock.current(now)
        drawPart(spec.root, ctx: c, xf: xf, glow: glow)
    }

    private func drawPart(_ part: MascotSpec.Part, ctx: GraphicsContext, xf: [String: Xf], glow: (Color, Double)) {
        var c = ctx
        if let clip = part.clip, let rect = spec.clips[clip] { c.clip(to: Path(ellipseIn: rect)) }
        let x = xf[part.id] ?? Xf()
        let opacity = x.opacity ?? part.defaultOpacity
        if opacity <= 0.001 { return }
        c.opacity *= opacity
        c.translateBy(x: x.translate.width, y: x.translate.height)
        c.translateBy(x: part.pivot.x, y: part.pivot.y)
        if x.rotate != 0 { c.rotate(by: .degrees(x.rotate)) }
        if x.scale != CGSize(width: 1, height: 1) { c.scaleBy(x: x.scale.width, y: x.scale.height) }
        c.translateBy(x: -part.pivot.x, y: -part.pivot.y)
        if part.id == "glow" { c.opacity *= glow.1 }
        // On a black surface (the Mac notch island) the floating z's are drawn light and larger so they read.
        let lightInk = onDark && part.id == "z"
        if lightInk {
            c.translateBy(x: part.pivot.x, y: part.pivot.y)
            c.scaleBy(x: MacIslandLayout.onDarkZScale, y: MacIslandLayout.onDarkZScale)
            c.translateBy(x: -part.pivot.x, y: -part.pivot.y)
        }

        for shape in part.shapes {
            let path: Path
            var bounds: CGRect
            switch shape.kind {
            case .ellipse(let r): path = Path(ellipseIn: r); bounds = r
            case .path(let p): path = p; bounds = p.boundingRect
            }
            var sc = c
            sc.opacity *= shape.opacity
            if let fill = shape.fill {
                if fill == "glow" {
                    if shape.radial {
                        let center = CGPoint(x: bounds.midX, y: bounds.midY)
                        let r = max(bounds.width, bounds.height) / 2
                        // Stretch to the ellipse: scale y about the centre.
                        var gc = sc
                        gc.translateBy(x: center.x, y: center.y)
                        gc.scaleBy(x: 1, y: bounds.height / max(1, bounds.width))
                        gc.translateBy(x: -center.x, y: -center.y)
                        bounds = CGRect(x: center.x - r, y: center.y - r, width: r * 2, height: r * 2)
                        gc.fill(Path(ellipseIn: bounds),
                                with: .radialGradient(Gradient(colors: [glow.0, glow.0.opacity(0)]), center: center,
                                                      startRadius: 0, endRadius: r))
                    } else {
                        sc.fill(path, with: .color(glow.0))
                    }
                } else {
                    sc.fill(path, with: .color(MascotPalette.color(fill)))
                }
            }
            if let stroke = shape.stroke, shape.strokeWidth > 0 {
                sc.stroke(path, with: .color(lightInk ? KaikuTokens.Colors.mascotBody : MascotPalette.color(stroke)),
                          style: StrokeStyle(lineWidth: shape.strokeWidth, lineCap: shape.lineCap, lineJoin: shape.lineJoin))
            }
        }
        for child in part.children { drawPart(child, ctx: c, xf: xf, glow: glow) }
    }
}

private struct MascotOnDarkKey: EnvironmentKey { static let defaultValue = false }
public extension EnvironmentValues {
    /// The mascot sits on a black surface (Mac notch island): parts drawn outside the body (the sleepy z's) use a
    /// light ink and draw larger.
    var kaikuMascotOnDark: Bool {
        get { self[MascotOnDarkKey.self] }
        set { self[MascotOnDarkKey.self] = newValue }
    }
}

enum MascotPalette {
    static func color(_ token: String) -> Color {
        switch token {
        case "mascot-body": return KaikuTokens.Colors.mascotBody
        case "mascot-shade": return KaikuTokens.Colors.mascotShade
        case "mascot-eye": return KaikuTokens.Colors.mascotEye
        case "mascot-shine": return KaikuTokens.Colors.mascotShine
        case "mascot-ear-inner": return KaikuTokens.Colors.mascotEarInner
        case "mascot-blush": return KaikuTokens.Colors.mascotBlush
        case "mascot-scarf": return KaikuTokens.Colors.mascotScarf
        case "mascot-scarf-stripe": return KaikuTokens.Colors.mascotScarfStripe
        case "mascot-outline": return KaikuTokens.Colors.mascotOutline
        case "mascot-sparkle": return KaikuTokens.Colors.mascotSparkle
        default: return KaikuTokens.Colors.ink
        }
    }
}

/// Chest glow colour + intensity by local hour (tokens.json → glow.stops, linear, wraps at 24).
public enum GlowClock {
    public static func at(hour h: Double) -> (Color, Double) {
        let stops = KaikuTokens.glowStops
        guard !stops.isEmpty else { return (KaikuTokens.Colors.honey, 0.8) }
        var lo = stops.last!, hi = stops.first!
        var loH = lo.hour - 24, hiH = hi.hour
        for i in 0..<stops.count {
            let a = stops[i], b = i + 1 < stops.count ? stops[i + 1] : stops[0]
            let bh = i + 1 < stops.count ? b.hour : b.hour + 24
            if h >= a.hour && h < bh { lo = a; hi = b; loH = a.hour; hiH = bh; break }
        }
        let t = hiH > loH ? (h - loH) / (hiH - loH) : 0
        func ch(_ c: UInt32, _ s: UInt32) -> Double { Double((c >> s) & 0xFF) / 255 }
        let r = ch(lo.color, 16) + (ch(hi.color, 16) - ch(lo.color, 16)) * t
        let g = ch(lo.color, 8) + (ch(hi.color, 8) - ch(lo.color, 8)) * t
        let b = ch(lo.color, 0) + (ch(hi.color, 0) - ch(lo.color, 0)) * t
        return (Color(.sRGB, red: r, green: g, blue: b, opacity: 1), lo.intensity + (hi.intensity - lo.intensity) * t)
    }

    /// Pins the hour (app icon render: the icon must not depend on when it was built). nil = the real clock.
    nonisolated(unsafe) public static var fixedHour: Double?

    public static func current(_ now: Date = Date()) -> (Color, Double) {
        if let h = fixedHour { return at(hour: h) }
        let c = Calendar.current.dateComponents([.hour, .minute], from: now)
        return at(hour: Double(c.hour ?? 12) + Double(c.minute ?? 0) / 60)
    }
}

#Preview("All states") {
    ScrollView {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 120))]) {
            ForEach(MascotState.allCases, id: \.self) { s in
                VStack { MascotView(state: s, size: 110); Text(s.rawValue).font(.caption) }
            }
        }.padding()
    }
    .background(KaikuTokens.Colors.bg)
}

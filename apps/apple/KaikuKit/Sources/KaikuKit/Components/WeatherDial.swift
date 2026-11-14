import SwiftUI

/// The weather dial card: title + the current value (a honey chip) on one row, a five-stop track under it. Drag
/// the big knob (it has grip lines, an open hand on Mac), tap a stop, or use ←/→ when focused. It snaps to whole
/// steps with a tick sound + haptic per step; Kaiku's ear follows. The active dial gets a honey outline.
/// VoiceOver: adjustable. On a touch screen the track takes sideways drags and taps only: a drag up or down that
/// starts on it scrolls the page it sits in.
public struct WeatherDial: View {
    let item: DialItem
    @Binding var value: Int
    var active: Bool
    var disabled: Bool
    var onFocus: (() -> Void)?
    @State private var dragging = false
    @State private var hover = false
    @FocusState private var focused: Bool
    @Environment(\.accessibilityReduceMotion) private var rm

    public init(item: DialItem, value: Binding<Int>, active: Bool = false, disabled: Bool = false, onFocus: (() -> Void)? = nil) {
        self.item = item
        _value = value
        self.active = active
        self.disabled = disabled
        self.onFocus = onFocus
    }

    var symbol: (String, String) {
        switch item {
        case .mood: return ("cloud.fill", "sun.max.fill")
        case .energy: return ("battery.25percent", "battery.100percent")
        case .sleep: return ("moon.zzz", "moon.stars.fill")
        }
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
            ViewThatFits(in: .horizontal) {
                HStack(spacing: KaikuTokens.Space.s2) { title; Spacer(minLength: KaikuTokens.Space.s2); chip }
                VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) { title; chip }
            }
            HStack(spacing: KaikuTokens.Space.s2) {
                Image(systemName: symbol.0).kText(.footnote, weight: .semibold)
                    .foregroundStyle(KaikuTokens.Colors.muted).frame(width: 22).accessibilityHidden(true)
                track
                Image(systemName: symbol.1).kText(.footnote, weight: .semibold)
                    .foregroundStyle(KaikuTokens.Colors.honey).frame(width: 22).accessibilityHidden(true)
            }
        }
        .padding(.horizontal, KaikuTokens.Space.s4)
        .padding(.vertical, KaikuTokens.Space.s3)
        .background(
            RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).fill(KaikuTokens.Colors.surface)
                .kaikuShadow(KaikuTokens.Elevation.card)
        )
        .overlay(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous)
            .strokeBorder(focused ? KaikuTokens.Colors.focus : active ? KaikuTokens.Colors.honey.opacity(0.7) : KaikuTokens.Colors.line,
                          lineWidth: focused || active ? 1.5 : 1))
        .animation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast), value: active)
        .opacity(disabled ? 0.5 : 1)
        .focusable(!disabled)
        .focused($focused)
        .focusEffectDisabled()
        .onChange(of: focused) { _, f in if f { onFocus?() } }
        .onKeyPress(.leftArrow) { set(max(1, value - 1)); return .handled }
        .onKeyPress(.rightArrow) { set(min(5, value + 1)); return .handled }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(T("wx.\(item.rawValue)"))
        .accessibilityValue(T("wx.\(item.rawValue).\(value)"))
        .accessibilityAdjustableAction { dir in
            switch dir {
            case .increment: set(min(5, value + 1))
            case .decrement: set(max(1, value - 1))
            @unknown default: break
            }
        }
    }

    private var title: some View {
        Text(T("wx.\(item.rawValue)")).kText(.body, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
    }

    private var chip: some View {
        Text(T("wx.\(item.rawValue).\(value)"))
            .kText(.footnote, weight: .semibold)
            .foregroundStyle(KaikuTokens.Colors.ink)   // ink on honey-soft: AA at footnote size
            .padding(.horizontal, KaikuTokens.Space.s3).padding(.vertical, KaikuTokens.Space.s1)
            .background(Capsule().fill(KaikuTokens.Colors.honeySoft))
            .contentTransition(.opacity)
            .animation(.easeOut(duration: KaikuTokens.Feedback.hover), value: value)
            .wraps()
    }

    private var track: some View {
        GeometryReader { geo in
            let inset: CGFloat = 18
            let step = (geo.size.width - inset * 2) / 4
            let x = inset + CGFloat(value - 1) * step
            let mid = geo.size.height / 2
            ZStack(alignment: .topLeading) {
                Capsule().fill(KaikuTokens.Colors.surface2)
                    .frame(width: geo.size.width - inset * 2 + 12, height: 12)
                    .position(x: geo.size.width / 2, y: mid)
                Capsule().fill(LinearGradient(colors: [KaikuTokens.Colors.honeySoft, KaikuTokens.Colors.honey.opacity(0.75)],
                                              startPoint: .leading, endPoint: .trailing))
                    .frame(width: x - inset + 12, height: 12)
                    .position(x: inset - 6 + (x - inset + 12) / 2, y: mid)
                ForEach(1...5, id: \.self) { i in
                    Capsule().fill(i <= value ? KaikuTokens.Colors.surface.opacity(0.9) : KaikuTokens.Colors.pebbleEdge)
                        .frame(width: 3, height: i == 3 ? 9 : 7)
                        .position(x: inset + CGFloat(i - 1) * step, y: mid)
                }
                knob.position(x: x, y: mid)
                    .animation(rm ? nil : KaikuTokens.Spring.gentle, value: value)
            }
            .contentShape(Rectangle())
            .modifier(TrackTouch(moved: { x in
                guard !disabled else { return }
                if !dragging { dragging = true; onFocus?() }
                let v = Int(((x - inset) / step).rounded()) + 1
                set(min(5, max(1, v)))
            }, ended: { dragging = false }))
            .kPointer(!disabled, cursor: .openHand)
            .onHover { hover = $0 }
        }
        .frame(height: KaikuTokens.Size.tapMin)
    }

    private var knob: some View {
        ZStack {
            Circle().fill(KaikuTokens.Colors.surface)
            Circle().strokeBorder(KaikuTokens.Colors.honey, lineWidth: dragging ? 4 : 3)
            HStack(spacing: 2.5) {
                ForEach(0..<3, id: \.self) { _ in Capsule().fill(KaikuTokens.Colors.honey.opacity(0.7)).frame(width: 2, height: 10) }
            }
        }
        .frame(width: 34, height: 34)
        .kaikuShadow(dragging ? KaikuTokens.Elevation.raised : KaikuTokens.Elevation.card)
        .scaleEffect(dragging && !rm ? 1.14 : (hover && !rm ? 1.05 : 1))
        .animation(.easeOut(duration: KaikuTokens.Feedback.hover), value: dragging)
        .animation(.easeOut(duration: KaikuTokens.Feedback.hover), value: hover)
    }

    private func set(_ v: Int) {
        guard v != value, !disabled else { return }
        value = v
        Haptics.dialStep()
        KSound.play(.tick)
    }
}

/// How the track is touched. With a pointer (Mac): press and drag anywhere on it. On a touch screen the track
/// sits in a page that scrolls, so it claims a tap and a sideways drag and nothing else: a drag that starts up
/// or down is the page's (a drag gesture that claimed every touch made the page impossible to scroll with a
/// thumb that landed on a dial).
private struct TrackTouch: ViewModifier {
    let moved: (CGFloat) -> Void
    let ended: () -> Void

    func body(content: Content) -> some View {
        #if os(iOS)
        if #available(iOS 18.0, *) {
            content
                .onTapGesture(coordinateSpace: .local) { p in moved(p.x); ended() }
                .gesture(SidewaysPan(moved: moved, ended: ended))
        } else {
            content
                .onTapGesture(coordinateSpace: .local) { p in moved(p.x); ended() }
                // Before iOS 18: a drag beside the page's own scrolling that acts only while it runs sideways.
                .simultaneousGesture(DragGesture(minimumDistance: 10)
                    .onChanged { g in
                        if DragAxis(dx: g.translation.width, dy: g.translation.height) == .sideways { moved(g.location.x) }
                    }
                    .onEnded { _ in ended() })
        }
        #else
        content.gesture(DragGesture(minimumDistance: 0).onChanged { moved($0.location.x) }.onEnded { _ in ended() })
        #endif
    }
}

/// Which way a drag is going, decided by its first movement (pure; tested).
enum DragAxis: Equatable {
    case sideways, upDown
    init(dx: CGFloat, dy: CGFloat) { self = abs(dx) > abs(dy) ? .sideways : .upDown }
}

#if os(iOS)
/// A pan that begins only when the finger moves sideways; anything else is left to the page.
@available(iOS 18.0, *)
private struct SidewaysPan: UIGestureRecognizerRepresentable {
    let moved: (CGFloat) -> Void
    let ended: () -> Void

    func makeCoordinator(converter: CoordinateSpaceConverter) -> Coordinator { Coordinator() }

    func makeUIGestureRecognizer(context: Context) -> UIPanGestureRecognizer {
        let pan = UIPanGestureRecognizer()
        pan.delegate = context.coordinator
        return pan
    }

    func handleUIGestureRecognizerAction(_ pan: UIPanGestureRecognizer, context: Context) {
        switch pan.state {
        case .began, .changed: moved(context.converter.localLocation.x)
        case .ended, .cancelled, .failed: ended()
        default: break
        }
    }

    final class Coordinator: NSObject, UIGestureRecognizerDelegate {
        func gestureRecognizerShouldBegin(_ g: UIGestureRecognizer) -> Bool {
            guard let pan = g as? UIPanGestureRecognizer else { return true }
            let v = pan.velocity(in: pan.view)
            return DragAxis(dx: v.x, dy: v.y) == .sideways
        }
    }
}

#endif

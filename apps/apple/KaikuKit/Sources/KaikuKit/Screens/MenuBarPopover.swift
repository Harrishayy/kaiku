import SwiftUI

/// Mac menu bar popover (design/ia.md → Mac extras): greeting + suggestion, three quick actions, usage-rhythm
/// switch, "pause for 1 hour", "What Kaiku saw today", "I'm not OK". `open` brings the window to a route.
public struct MenuBarPopover: View {
    @Environment(AppModel.self) private var app
    let open: (KaikuTab, KaikuRoute?) -> Void

    public init(open: @escaping (KaikuTab, KaikuRoute?) -> Void) { self.open = open }

    public var body: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s3) {
            HStack(alignment: .center, spacing: KaikuTokens.Space.s3) {
                MascotView(state: app.ambientState, size: 64)
                VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
                    Text(app.greeting).kText(.callout).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                    if let arm = app.nudge?.arm {
                        Text(T("today.suggest.\(arm.rawValue)")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            HStack(spacing: KaikuTokens.Space.s2) {
                quick("cloud.sun.fill", "today.card.weather.t") { open(.today, .weather) }
                quick("wind", "game.breathe.t") { open(.play, .breathe) }
                quick("bubble.left.fill", "tab.talk") { open(.talk, nil) }
            }
            Divider()
            Toggle(isOn: Binding(get: { app.consents[.mac] ?? false }, set: { app.consents[.mac] = $0 })) {
                VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
                    Text(T("sig.mac.t")).kText(.footnote, weight: .semibold).wraps()
                    Text(T("sig.mac.d")).kText(.caption, weight: .regular).foregroundStyle(KaikuTokens.Colors.muted).wraps()
                }
            }
            .toggleStyle(.switch)
            .tint(KaikuTokens.Colors.sage)
            Button {
                app.pausedUntil = app.isPaused ? nil : Date().addingTimeInterval(3600)
            } label: {
                VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
                    Text(T("mac.pause1h")).kText(.footnote, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                    Text(T("mac.pause1h.d")).kText(.caption, weight: .regular).foregroundStyle(KaikuTokens.Colors.muted).wraps()
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .overlay(alignment: .trailing) { if app.pausedUntil.map({ $0 > Date() }) == true { Image(systemName: "checkmark").foregroundStyle(KaikuTokens.Colors.sage) } }
            Button { open(.you, .saw) } label: {
                Text(T("you.saw")).kText(.footnote, weight: .semibold).foregroundStyle(KaikuTokens.Colors.clay)
                    .frame(maxWidth: .infinity, minHeight: KaikuTokens.Size.tapMin, alignment: .leading).contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            Divider()
            HStack {
                NotOKPill()
                Spacer()
                Button(T("mac.open")) { open(app.selectedTab, nil) }.buttonStyle(KButtonStyle(.ghost, fullWidth: false))
            }
        }
        .padding(KaikuTokens.Space.s4)
        .frame(width: 340)
        .background(KaikuTokens.Colors.bg)
    }

    private func quick(_ icon: String, _ key: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: KaikuTokens.Space.s2) {
                Image(systemName: icon).kText(.body, weight: .semibold).foregroundStyle(KaikuTokens.Colors.clay)
                Text(T(key)).kText(.caption).foregroundStyle(KaikuTokens.Colors.ink).multilineTextAlignment(.center).wraps()
            }
            .frame(maxWidth: .infinity, minHeight: KaikuTokens.Size.rowMin)
            .padding(.vertical, KaikuTokens.Space.s2)
            .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.md, style: .continuous).fill(KaikuTokens.Colors.surface))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

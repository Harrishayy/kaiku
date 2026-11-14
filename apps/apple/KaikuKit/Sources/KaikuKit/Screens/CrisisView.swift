import SwiftUI

/// Crisis: plain surface, title, the pre-written script (config/safety_phrases.toml [script], verbatim, never
/// generated), three call buttons, "your care team has been told". No mascot, no motion, no glow, no haptics.
/// Deterministic: opened by "I'm not OK", a crisis phrase on this device, or mood `crisis` from the cloud.
public struct CrisisView: View {
    @Environment(AppModel.self) private var app
    public init() {}

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: KaikuTokens.Space.s5) {
                Text(T("crisis.title"))
                    .kText(.title1)
                    .foregroundStyle(KaikuTokens.Colors.ink)
                    .wraps()
                    .accessibilityAddTraits(.isHeader)
                Text(SafetyGate.shared.script(app.language.rawValue))
                    .kText(.body)
                    .foregroundStyle(KaikuTokens.Colors.ink)
                    .wraps()
                VStack(spacing: KaikuTokens.Space.s3) {
                    CallButtons(style: .crisis)
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text(T("crisis.team")).kText(.callout).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                    Text(T("crisis.team.d")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                }
                .padding(KaikuTokens.Space.s4)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.md, style: .continuous).fill(KaikuTokens.Colors.crisisSoft))
                Button(T("common.back")) { app.showCrisis = false }
                    .buttonStyle(KButtonStyle(.secondary))
            }
            .padding(.horizontal, KaikuPlatform.sidePadding)
            .padding(.vertical, KaikuTokens.Space.s6)
            .frame(maxWidth: 640, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .background(KaikuTokens.Colors.surface.ignoresSafeArea())
        .transaction { $0.disablesAnimations = true }
    }
}

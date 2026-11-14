import SwiftUI

/// Offline banner (sky): the app keeps working and queues what it records.
public struct OfflineBanner: View {
    let text: String
    public init(_ text: String = T("today.offline")) { self.text = text }
    public var body: some View {
        HStack(alignment: .top, spacing: KaikuTokens.Space.s3) {
            Image(systemName: "icloud.slash").foregroundStyle(KaikuTokens.Colors.sky).accessibilityHidden(true)
            Text(text).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(KaikuTokens.Space.s4)
        .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.md, style: .continuous).fill(KaikuTokens.Colors.skySoft))
        .accessibilityElement(children: .combine)
    }
}

/// Loading: Kaiku thinking + "One moment…".
public struct LoadingState: View {
    public init() {}
    public var body: some View {
        VStack(spacing: KaikuTokens.Space.s3) {
            MascotView(state: .thinking, size: KaikuTokens.Size.mascotM, tappable: false)
            Text(T("common.loading")).kText(.body).foregroundStyle(KaikuTokens.Colors.muted).wraps()
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, KaikuTokens.Space.s5)
    }
}

/// Empty: cozy Kaiku + one sentence (+ optional action).
public struct EmptyState: View {
    let text: String
    let action: (String, () -> Void)?
    public init(_ text: String, action: (String, () -> Void)? = nil) { self.text = text; self.action = action }
    public var body: some View {
        VStack(spacing: KaikuTokens.Space.s3) {
            MascotView(state: .cozy, size: KaikuTokens.Size.mascotM, tappable: false)
            Text(text).kText(.body).foregroundStyle(KaikuTokens.Colors.ink2).multilineTextAlignment(.center).wraps()
            if let action { Button(action.0, action: action.1).buttonStyle(KButtonStyle(.secondary, fullWidth: false)) }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, KaikuTokens.Space.s5)
    }
}

/// Error: "I can't reach the cloud" + body + Try again.
public struct ErrorState: View {
    let retry: () -> Void
    public init(retry: @escaping () -> Void) { self.retry = retry }
    public var body: some View {
        KCard {
            Text(T("err.title")).kText(.title3).foregroundStyle(KaikuTokens.Colors.ink).wraps()
            Text(T("err.body")).kText(.body).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            Button(T("err.retry"), action: retry).buttonStyle(KButtonStyle(.secondary))
        }
    }
}

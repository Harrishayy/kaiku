import SwiftUI

/// Weather check: three 1–5 dials (mood, energy, last night's sleep). Kaiku's ear follows the dial being turned.
/// "That's it" → three obs.self_report (channel phone|mac) through the offline queue → happy + thanks.
/// One viewport: Kaiku beside the dials on the Mac window, a compact stack on iPhone.
public struct WeatherCheckView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss
    @State private var values: [DialItem: Int] = [.mood: 3, .energy: 3, .sleep: 3]
    @State private var active: DialItem = .mood
    @State private var done = false

    public init() {}

    var bubble: String { done ? T("wx.thanks") : T("wx.\(active.rawValue).\(values[active] ?? 3)") }
    var dial: Double? { done ? nil : Double(values[active] ?? 3) }

    public var body: some View {
        KScreen(T("wx.title"), back: { dismiss() }, maxWidth: 980, spacing: KaikuTokens.Space.s4) {
            KAdaptiveColumns(minWidth: 600, leadingFraction: 0.4) {
                WideAware { wide in
                    if wide {
                        VStack(spacing: KaikuTokens.Space.s4) {
                            GlowingMascot(state: done ? .happy : .listening, size: 180, dial: dial)
                            Bubble(bubble, big: true, centered: true)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.top, KaikuTokens.Space.s5)
                    } else {
                        MascotWithBubble(state: done ? .happy : .listening, text: bubble, size: 100, dial: dial, big: true)
                    }
                }
            } trailing: {
                VStack(spacing: KaikuTokens.Space.s3) {
                    ForEach(DialItem.allCases) { item in
                        WeatherDial(item: item, value: binding(item), active: active == item && !done, disabled: done) { active = item }
                    }
                }
                Button(T("wx.done")) {
                    guard !done else { return }
                    Haptics.finished()
                    KSound.play(.done)
                    withAnimation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.base)) { done = true }
                    let v = values
                    Task {
                        await app.recordWeather(v)
                        try? await Task.sleep(nanoseconds: 1_800_000_000)
                        dismiss()
                    }
                }
                .buttonStyle(.kPrimary)
                .keyboardShortcut(.defaultAction)
                .disabled(done)
            }
        }
        .onAppear { KSound.warmUp([.tick]) }
    }

    private func binding(_ item: DialItem) -> Binding<Int> {
        Binding(get: { values[item] ?? 3 }, set: { values[item] = $0; active = item })
    }
}

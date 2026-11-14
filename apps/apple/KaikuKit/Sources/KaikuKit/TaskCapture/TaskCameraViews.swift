import SwiftUI
#if os(macOS)
import AppKit
#endif

/// What the person sees of the task camera, on the task's own screen: while it samples, a chip that says so and
/// turns it off with one tap (for this task; the numbers of the task so far are thrown away); after that tap, a
/// quiet "off" and a way to switch the choice itself off (the same switch as in You); when the camera cannot be
/// used, one calm line, and the task goes on. Nothing while the choice is off. No motion of its own, so there is
/// nothing to reduce.
struct TaskCameraChip: View {
    let camera: TaskCamera
    /// The colour of the chip's small action words (a night scene needs its own ink).
    var action: Color = KaikuTokens.Colors.clay
    /// A game keeps the chip's row in place for the whole round, so nothing on the field moves when the camera
    /// starts, stops or is turned off in the middle of it.
    var holdsPlace = false
    @Environment(AppModel.self) private var app

    private var shows: Bool { camera.state == .capturing || camera.state == .stopped || camera.state == .unavailable }

    var body: some View {
        if shows {
            content.frame(maxWidth: .infinity, minHeight: KaikuTokens.Size.tapMin)
        } else if holdsPlace {
            Color.clear.frame(height: KaikuTokens.Size.tapMin).accessibilityHidden(true)
        }
    }

    @ViewBuilder private var content: some View {
        switch camera.state {
        case .capturing:
            Button { camera.stopForThisTask() } label: {
                HStack(spacing: KaikuTokens.Space.s2) {
                    ViewThatFits(in: .horizontal) {
                        KChip(T("task.camera.active"), tone: .sage, icon: "camera.fill")
                        KChip(T("task.camera.active.short"), tone: .sage, icon: "camera.fill")
                    }
                    Text(T("task.camera.off")).kText(.caption, weight: .semibold).foregroundStyle(action)
                }
                .frame(minHeight: KaikuTokens.Size.tapMin)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .kPointer()
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(T("task.camera.active.a11y"))
            .accessibilityHint(T("task.camera.off.hint"))
            .accessibilityAddTraits(.isButton)
            .accessibilityIdentifier("task.camera.on")
        case .stopped:
            HStack(spacing: KaikuTokens.Space.s2) {
                KChip(T("task.camera.stopped"), tone: .ink, icon: "camera")
                    .accessibilityIdentifier("task.camera.stopped")
                Button {
                    app.consents[.camera] = false
                    app.showToast(T("task.camera.keptoff"))
                } label: {
                    Text(T("task.camera.keepoff")).kText(.caption, weight: .semibold).foregroundStyle(action)
                        .frame(minHeight: KaikuTokens.Size.tapMin)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .kPointer()
                .accessibilityHint(T("task.camera.keepoff.hint"))
                .accessibilityIdentifier("task.camera.keepoff")
            }
        case .unavailable:
            KChip(T("task.camera.unavailable"), tone: .ink, icon: "camera")
                .accessibilityIdentifier("task.camera.unavailable")
        case .off, .requesting, .suspended:
            EmptyView()
        }
    }
}

/// Asked once of someone who turned "Camera during activities" on under its older wording: the camera now
/// notices more than that wording said, so the choice is put to her again with the whole new text. Until she
/// answers the camera stays off; the task itself is never held up by the question.
struct CameraConfirmCard: View {
    @Environment(AppModel.self) private var app

    var body: some View {
        if app.cameraNeedsConfirm && !app.isPaused {
            KCard(tone: .sage) {
                Text(T("camera.confirm.t")).kText(.callout, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                    .accessibilityAddTraits(.isHeader)
                Text(T("sig.camera.d")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: KaikuTokens.Space.s2) { buttons }
                    VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) { buttons }
                }
            }
            .accessibilityElement(children: .contain)   // the card is a group: its words and buttons keep their own names
            .accessibilityIdentifier("camera.confirm")
        }
    }

    @ViewBuilder private var buttons: some View {
        Button(T("camera.confirm.keep")) { app.confirmCamera(keep: true) }
            .buttonStyle(KButtonStyle(.secondary, fullWidth: false))
            .accessibilityIdentifier("camera.confirm.keep")
        Button(T("camera.confirm.off")) { app.confirmCamera(keep: false) }
            .buttonStyle(KButtonStyle(.ghost, fullWidth: false))
            .accessibilityIdentifier("camera.confirm.off")
    }
}

/// Keeps a task's camera to the time its screen is in front. The app not being active (another app, the app
/// switcher, Control Centre, a locked screen), a sleeping display or another user's session closes the camera at
/// once; it comes back with the screen, and goes on from the numbers it had. A camera is never left open behind a
/// lock screen: iOS also takes it away from a background app by itself.
private struct CameraInFront: ViewModifier {
    let camera: TaskCamera
    @Environment(\.scenePhase) private var phase

    func body(content: Content) -> some View {
        content
            .onChange(of: phase) { _, now in
                if now == .active { Task { await camera.resume() } } else { camera.suspend() }
            }
            #if os(macOS)
            .onReceive(NotificationCenter.default.publisher(for: NSApplication.didResignActiveNotification)) { _ in camera.suspend() }
            .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in Task { await camera.resume() } }
            .onReceive(NSWorkspace.shared.notificationCenter.publisher(for: NSWorkspace.screensDidSleepNotification)) { _ in camera.suspend() }
            .onReceive(NSWorkspace.shared.notificationCenter.publisher(for: NSWorkspace.sessionDidResignActiveNotification)) { _ in camera.suspend() }
            .onReceive(NSWorkspace.shared.notificationCenter.publisher(for: NSWorkspace.screensDidWakeNotification)) { _ in
                if NSApp?.isActive == true { Task { await camera.resume() } }
            }
            #endif
    }
}

extension View {
    func keepsCameraInFront(_ camera: TaskCamera) -> some View { modifier(CameraInFront(camera: camera)) }
}

extension TaskCamera {
    /// A walk, or a voice call that is not this task, has Kaiku's attention: no task camera beside it.
    /// `own` is the task's own call (the check-in's), which does not count.
    static func busyElsewhere(own: TalkModel? = nil) -> Bool {
        if WalkModel.shared.active { return true }
        if let call = TalkModel.active, call !== own, call.hasLive { return true }
        return false
    }
}

import Observation
import SwiftUI

// Today's invitation: one thing Kaiku would like to bring up or offer now ("do you want to talk about …?", "do
// you want to play this now?"). The cloud chooses it by code from what the person did and said on any device
// (`GET /v1/me/invitation`, at most one a day); the device shows the sentence with two answers and goes where a
// yes leads. No invitation, no card. It is never spoken by itself: the small speaker on the card says it in
// Kaiku's voice (`POST /v1/voice/say`), silent when the service has no voice.

// MARK: where a yes leads

public extension Invitation {
    enum Destination: Equatable, Sendable { case talk, route(KaikuRoute) }

    /// Where a yes goes on this device. Nil = there is no screen for it here (the robot's drum, a walk on the
    /// Mac, a kind this build does not know): such an invitation is not shown.
    func destination(isPhone: Bool = KaikuPlatform.isPhone) -> Destination? {
        switch kind {
        case .talk_about: return .talk
        case .activity:
            switch activity {
            case "breathe": return .route(.breathe)
            case "tell": return .route(.tell)
            case "lantern": return .route(.lantern)
            case "seeds": return .route(.seeds)
            case "watering": return .route(.watering)
            case "pebbles": return .route(.pebbles)
            case "firefly": return .route(.firefly)
            case "walk", "light_hunt": return isPhone ? .route(.walk) : nil
            default: return nil
            }
        }
    }

    /// The yes button's words, fitting what a yes starts.
    var yesKey: String {
        switch destination(isPhone: true) {
        case .talk: return "invite.yes.talk"
        case .route(.breathe): return "invite.yes.breathe"
        case .route(.walk): return "invite.yes.walk"
        case .route(.lantern), .route(.seeds), .route(.watering), .route(.pebbles), .route(.firefly): return "invite.yes.play"
        default: return "invite.yes.other"
        }
    }
}

// MARK: service

extension APIClient {
    /// `GET /v1/me/invitation?home_id=&surface=`. Nil: not connected, offline, or a service without the route.
    func invitation(surface: CompanionSurface) async -> InvitationResponse? {
        guard let home = pairing?.homeID,
              var req = try? request("GET", "/v1/me/invitation", query: ["home_id": home, "surface": surface.rawValue])
        else { return nil }
        req.timeoutInterval = 6
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              (resp as? HTTPURLResponse)?.statusCode == 200 else { return nil }
        return try? JSONDecoder().decode(InvitationResponse.self, from: data)
    }

    /// `POST /v1/me/invitation/answer?home_id=` `{id, answer}`. True when the service took it, or said it never
    /// will (404: that invitation is no longer today's): either way there is nothing to send again.
    func answerInvitation(_ answer: InvitationAnswer) async -> Bool {
        guard let home = pairing?.homeID,
              var req = try? request("POST", "/v1/me/invitation/answer", query: ["home_id": home]) else { return false }
        req.httpBody = try? JSONEncoder().encode(answer)
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.timeoutInterval = 4
        guard let (_, resp) = try? await URLSession.shared.data(for: req),
              let code = (resp as? HTTPURLResponse)?.statusCode else { return false }
        return (200..<300).contains(code) || ((400..<500).contains(code) && code != 408 && code != 429)
    }
}

/// The two calls the card needs (the service in the app, closures in tests).
struct InvitationService: Sendable {
    var fetch: @Sendable (CompanionSurface) async -> InvitationResponse?
    var answer: @Sendable (InvitationAnswer) async -> Bool

    static func live(_ api: APIClient) -> InvitationService {
        InvitationService(fetch: { await api.invitation(surface: $0) }, answer: { await api.answerInvitation($0) })
    }
}

// MARK: model

/// Holds the invitation Today shows. An answer takes the card away at once; when it did not reach the service it
/// is sent again before the next load, and that invitation does not come back on this device meanwhile.
@Observable @MainActor
final class InvitationModel {
    private(set) var invitation: Invitation?
    /// A yes is on its way (the card's buttons wait, so it is not answered twice).
    private(set) var sending = false

    @ObservationIgnored private var answered = Set<String>()
    @ObservationIgnored private var unsent: [InvitationAnswer] = []
    @ObservationIgnored private var loadedFor: Pairing?
    @ObservationIgnored private let service: InvitationService?
    @ObservationIgnored private let isPhone: Bool

    init(service: InvitationService? = nil, isPhone: Bool = KaikuPlatform.isPhone) {
        self.service = service
        self.isPhone = isPhone
    }

    private func calls(_ app: AppModel) -> InvitationService { service ?? .live(app.api) }

    func load(app: AppModel) async {
        guard let pairing = app.pairing else { forget(); loadedFor = nil; return }
        if pairing != loadedFor { forget(); loadedFor = pairing }   // another home never sees this one's card
        let service = calls(app)
        await resend(service, pairing: pairing, app: app)
        let response = await service.fetch(isPhone ? .iphone : .mac)
        guard app.pairing == pairing else { return }
        guard let response, response.home_id == pairing.homeID else { return }   // unreachable: keep what is shown
        let next = response.invitation.flatMap { shows($0) ? $0 : nil }
        if next != invitation { invitation = next }
    }

    /// Posts the answer and takes the card away. Returns where a yes leads (nil for a not-now).
    @discardableResult
    func answer(_ answer: InvitationAnswer.Answer, app: AppModel) async -> Invitation.Destination? {
        guard let inv = invitation, !sending, let pairing = app.pairing else { return nil }
        let reply = InvitationAnswer(id: inv.id, answer: answer)
        answered.insert(inv.id)
        // A yes reaches the service before the screen it opens asks for anything (Talk's context card carries
        // the thread); a not-now leaves at once.
        if answer == .not_now { invitation = nil } else { sending = true }
        let ok = await calls(app).answer(reply)
        sending = false
        guard app.pairing == pairing else { return nil }
        if !ok { unsent.append(reply) }
        invitation = nil
        return answer == .yes ? inv.destination(isPhone: isPhone) : nil
    }

    private func shows(_ inv: Invitation) -> Bool {
        !answered.contains(inv.id) && inv.destination(isPhone: isPhone) != nil
            && !inv.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func resend(_ service: InvitationService, pairing: Pairing, app: AppModel) async {
        let waiting = unsent
        unsent = []
        for reply in waiting {
            let ok = await service.answer(reply)
            guard app.pairing == pairing else { return }
            if !ok { unsent.append(reply) }
        }
    }

    private func forget() { invitation = nil; answered = []; unsent = []; sending = false }
}

// MARK: card

/// Kaiku's invitation on Today: its sentence, a small "hear it", and two answers. On the phone it stands where
/// Kaiku's usual line is (with a small Kaiku), so the day's path barely moves; in the wide layout it sits under
/// the large Kaiku in place of the bubble.
struct InvitationCard: View {
    let invitation: Invitation
    var showsMascot = true
    var waiting = false
    let hear: () -> Void
    let yes: () -> Void
    let notNow: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s3) {
            HStack(alignment: .top, spacing: KaikuTokens.Space.s3) {
                if showsMascot {
                    MascotView(state: .idle, size: KaikuTokens.Size.mascotS, tappable: false)
                        .accessibilityHidden(true)
                }
                Text(invitation.text).kText(.callout, weight: .medium).foregroundStyle(KaikuTokens.Colors.ink).wraps()
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
        .accessibilityIdentifier("today.invitation")
    }

    @ViewBuilder private var answers: some View {
        Button(T(invitation.yesKey), action: yes).buttonStyle(.kPrimary)
        Button(T("invite.notnow"), action: notNow).buttonStyle(.kGhost)
    }
}

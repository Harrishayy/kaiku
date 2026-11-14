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

    /// `POST /v1/me/agreed/answer?home_id=&surface=` `{id, answer}` → the list as it now stands.
    func answerAgreed(_ answer: AgreedAnswer, surface: CompanionSurface) async -> AgreedReply {
        guard let home = pairing?.homeID,
              var req = try? request("POST", "/v1/me/agreed/answer", query: ["home_id": home, "surface": surface.rawValue])
        else { return .failed }
        req.httpBody = try? JSONEncoder().encode(answer)
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.timeoutInterval = 4
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              let code = (resp as? HTTPURLResponse)?.statusCode else { return .failed }
        if (200..<300).contains(code) { return .taken(try? JSONDecoder().decode(InvitationResponse.self, from: data)) }
        return (400..<500).contains(code) && code != 408 && code != 429 ? .gone : .failed
    }
}

/// What the service said to an answer about an agreed item.
enum AgreedReply: Equatable, Sendable {
    /// Taken, with the list as it now stands (nil when the answer could not be read: the next load brings it).
    case taken(InvitationResponse?)
    /// It never will be (404: not one of today's): nothing to send again.
    case gone
    /// It did not arrive: sent again before the next load.
    case failed
}

/// The calls the cards need (the service in the app, closures in tests).
struct InvitationService: Sendable {
    var fetch: @Sendable (CompanionSurface) async -> InvitationResponse?
    var answer: @Sendable (InvitationAnswer) async -> Bool
    var settle: @Sendable (AgreedAnswer, CompanionSurface) async -> AgreedReply = { _, _ in .failed }

    static func live(_ api: APIClient) -> InvitationService {
        InvitationService(fetch: { await api.invitation(surface: $0) }, answer: { await api.answerInvitation($0) },
                          settle: { await api.answerAgreed($0, surface: $1) })
    }
}

// MARK: model

/// Holds what Today shows from the one read (`GET /v1/me/invitation`): the invitation, and what the person said
/// yes to today in a conversation on any device (`agreed`, D50). An answer takes effect on screen at once; when
/// it did not reach the service it is sent again before the next read, and what was answered does not come back
/// on this device meanwhile. Reads run one after another, so an event that arrives during a read gets its own.
@Observable @MainActor
final class InvitationModel {
    /// The one the app shows: Today reads it, the home stream refreshes it (`HomeUpdates`), and the notification
    /// rules follow it (`Notifier.agreed`).
    static let shared = InvitationModel(announce: { items, app in
        guard !AppPresence.pictureRun else { return }
        _ = await Notifier.shared.agreed(items, app: app)
    })

    private(set) var invitation: Invitation?
    /// A yes is on its way (the card's buttons wait, so it is not answered twice).
    private(set) var sending = false
    /// What the person said yes to today, as the service last had it: oldest first, every state.
    private(set) var agreed: [AgreedActivity] = []
    /// Agreed items with an answer on its way (their buttons wait).
    private(set) var settling: Set<String> = []

    @ObservationIgnored private var answered = Set<String>()
    @ObservationIgnored private var unsent: [InvitationAnswer] = []
    @ObservationIgnored private var unsettled: [AgreedAnswer] = []
    @ObservationIgnored private var celebrated = Set<String>()
    @ObservationIgnored private var loadedFor: Pairing?
    @ObservationIgnored private var reads: Task<Bool, Never>?
    @ObservationIgnored private let service: InvitationService?
    @ObservationIgnored private let isPhone: Bool
    /// Told the agreed list after every read and every answer (the notification rules in the app).
    @ObservationIgnored private let announce: (@MainActor ([AgreedActivity], AppModel) async -> Void)?

    init(service: InvitationService? = nil, isPhone: Bool = KaikuPlatform.isPhone,
         announce: (@MainActor ([AgreedActivity], AppModel) async -> Void)? = nil) {
        self.service = service
        self.isPhone = isPhone
        self.announce = announce
    }

    private func calls(_ app: AppModel) -> InvitationService { service ?? .live(app.api) }
    private var surface: CompanionSurface { isPhone ? .iphone : .mac }

    /// Reads the invitation and the agreed list. False: the service did not answer (what is shown stays).
    @discardableResult
    func load(app: AppModel) async -> Bool {
        let earlier = reads
        let read = Task { @MainActor [weak self] () -> Bool in
            _ = await earlier?.value
            return await self?.read(app: app) ?? false
        }
        reads = read
        return await read.value
    }

    private func read(app: AppModel) async -> Bool {
        guard let pairing = app.pairing else {
            forget(); loadedFor = nil
            await announce?([], app)
            return false
        }
        if pairing != loadedFor { forget(); loadedFor = pairing }   // another home never sees this one's cards
        let service = calls(app)
        await resend(service, pairing: pairing, app: app)
        let response = await service.fetch(surface)
        guard app.pairing == pairing else { return false }
        guard let response, response.home_id == pairing.homeID else { return false }   // unreachable: keep what is shown
        take(response, app: app)
        await announce?(agreed, app)
        return true
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

    // MARK: agreed items

    /// Start or Not now on an agreed item (its card, a line, or its notification). The screen changes at once:
    /// an opened item reads "Started", one put aside leaves. The answer goes to the service, which hands back
    /// the list as it now stands; an answer that did not arrive is sent again before the next read.
    func settle(_ id: String, _ answer: AgreedAnswer.Answer, app: AppModel) async {
        guard let pairing = app.pairing, !settling.contains(id) else { return }
        // Nothing to open on this device: nothing to report as opened.
        if answer == .opened, let item = agreed.first(where: { $0.id == id }), item.route(isPhone: isPhone) == nil { return }
        mark(id, answer)
        settling.insert(id)
        let reply = AgreedAnswer(id: id, answer: answer)
        let result = await calls(app).settle(reply, surface)
        settling.remove(id)
        guard app.pairing == pairing else { return }
        switch result {
        case .taken(let response?) where response.home_id == pairing.homeID: take(response, app: app)
        case .taken: break
        case .gone:                                        // no longer one of today's: the list is read again
            agreed.removeAll { $0.id == id }
            await announce?(agreed, app)
            await load(app: app)
            return
        case .failed: unsettled.append(reply)
        }
        await announce?(agreed, app)
    }

    /// The stream said this item is gone: its card leaves before the next read confirms it.
    func drop(agreed id: String, app: AppModel) async {
        guard agreed.contains(where: { $0.id == id }) else { return }
        agreed.removeAll { $0.id == id }
        await announce?(agreed, app)
    }

    /// The stream said today's invitation was answered on some device: its card leaves.
    func drop(invitation id: String) {
        answered.insert(id)
        if invitation?.id == id { invitation = nil }
    }

    /// A new home or service: nothing of the previous one stays on screen (`AppModel.updatePairing`).
    func clearForPairingChange() { forget(); loadedFor = nil }

    private func take(_ response: InvitationResponse, app: AppModel) {
        let next = response.invitation.flatMap { shows($0) ? $0 : nil }
        if next != invitation { invitation = next }
        var items = response.agreed ?? []
        // An answer that has not reached the service yet still counts on this screen.
        for reply in unsettled {
            guard let i = items.firstIndex(where: { $0.id == reply.id }) else { continue }
            items[i].state = Self.state(items[i].state, after: reply.answer)
        }
        // The completion moment, once per item, also when it was done on another device. One that just played
        // here (this device finished the activity itself) is not played twice.
        let finished = AgreedBoard.finished(before: agreed, after: items).filter { celebrated.insert($0).inserted }
        if items != agreed { agreed = items }
        if !finished.isEmpty, !app.celebratedJustNow { app.celebrate() }
    }

    private func mark(_ id: String, _ answer: AgreedAnswer.Answer) {
        guard let i = agreed.firstIndex(where: { $0.id == id }) else { return }
        agreed[i].state = Self.state(agreed[i].state, after: answer)
    }

    /// What an answer makes of an item on this screen before the service confirms it.
    nonisolated static func state(_ state: AgreedActivity.State, after answer: AgreedAnswer.Answer) -> AgreedActivity.State {
        switch (state, answer) {
        case (.open, .opened): return .started
        case (.open, .put_aside), (.started, .put_aside): return .put_aside
        default: return state       // done stays done; an item put aside stays put aside
        }
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
        let held = unsettled
        unsettled = []
        for reply in held {
            let result = await service.settle(reply, surface)
            guard app.pairing == pairing else { return }
            if result == .failed { unsettled.append(reply) }
        }
    }

    private func forget() {
        invitation = nil; answered = []; unsent = []; sending = false
        agreed = []; settling = []; unsettled = []; celebrated = []
    }
}

extension AppModel {
    /// A completion moment played on this device in the last half minute (`celebrate()` keeps Kaiku happy for
    /// six seconds from it).
    var celebratedJustNow: Bool { celebrateUntil.map { $0.addingTimeInterval(24) > Date() } ?? false }
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

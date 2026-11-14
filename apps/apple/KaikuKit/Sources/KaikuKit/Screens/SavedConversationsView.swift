import SwiftUI

/// The person's retained words, separate from the care team's numeric record.
struct SavedConversationsView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss
    @State private var confirmDelete = false

    var body: some View {
        KScreen(T("conv.read"), back: { dismiss() }) {
            Text(T("conv.private")).kText(.body).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            if app.conversationsLoading { LoadingState() }
            if app.conversationsFailed {
                ErrorState { Task { await app.loadConversations() } }
            } else if !app.conversationsLoading && app.savedConversations.isEmpty {
                EmptyState(T("conv.empty"))
            }
            ForEach(app.savedConversations, id: \.episode_id) { conversation in
                KCard {
                    DisclosureGroup {
                        ForEach(Array(conversation.turns.enumerated()), id: \.offset) { _, turn in
                            VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
                                Text(T(turn.role == .person ? "conv.you" : "conv.kaiku"))
                                    .kText(.footnote, weight: .semibold)
                                Text(turn.text).kText(.body).wraps().textSelection(.enabled)
                                if turn.complete == false {
                                    Text(T("conv.incomplete")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                                }
                            }.frame(maxWidth: .infinity, alignment: .leading)
                                .padding(.vertical, KaikuTokens.Space.s2)
                        }
                    } label: {
                        VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
                            if let date = KaikuTime.parse(conversation.start) {
                                Text(date, style: .date).kText(.title3)
                                Text(date, style: .time).kText(.footnote)
                            }
                            Text(T("conv.turns", n: conversation.turns.count)).kText(.footnote)
                        }
                    }
                }
            }
            if !app.savedConversations.isEmpty {
                Button(T("conv.forgetall")) { confirmDelete = true }.buttonStyle(.kSecondary)
            }
        }
        .task { await app.loadConversations() }
        .confirmationDialog(T("conv.forgetall.confirm"), isPresented: $confirmDelete, titleVisibility: .visible) {
            Button(T("conv.forgetall"), role: .destructive) { Task { await app.forgetConversations() } }
            Button(T("common.back"), role: .cancel) {}
        }
    }
}

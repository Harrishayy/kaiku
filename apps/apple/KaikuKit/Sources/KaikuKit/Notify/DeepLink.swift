import Foundation

/// `kaiku://` links used by notifications, widgets, Live Activities and App Intents (plan 05 §1). Pairing links
/// (`kaiku://pair?home=…` or any link carrying `?home=`) are handled by `Pairing`, not here.
public enum DeepLink: Equatable, Sendable {
    case tab(KaikuTab)
    case route(KaikuRoute)
    /// PHQ-9 lives on the web (`/phq9/`); the app opens it in the browser.
    case phq9

    public static func parse(_ url: URL) -> DeepLink? {
        guard url.scheme == "kaiku" else { return nil }
        let host = url.host ?? ""
        let rest = url.pathComponents.filter { $0 != "/" }
        switch host {
        case "today": return .tab(.today)
        case "talk": return .tab(.talk)
        case "bot", "robot": return .tab(.bot)          // iPhone: the screen under You (PhoneTabs)
        case "days": return .route(.days)          // Your days: a screen under History
        case "history":
            // kaiku://history · kaiku://history/days
            return rest.first == "days" ? .route(.days) : .tab(.history)
        case "you":
            // kaiku://you/memories · /saw · /voice · /quiet · /devices · /help (demo recordings, Mac links)
            if let r = rest.first.flatMap(KaikuRoute.init(rawValue:)), r.tab == .you { return .route(r) }
            return .tab(.you)
        case "checkin", "weather": return .route(.weather)
        case "walk": return .route(.walk)
        case "breathe": return .route(.breathe)
        case "phq9": return .phq9
        case "play":
            guard let g = rest.first else { return .tab(.play) }
            switch g {
            case "firefly": return .route(.firefly)
            case "pebbles": return .route(.pebbles)
            case "lantern": return .route(.lantern)
            case "seeds": return .route(.seeds)
            case "watering": return .route(.watering)
            case "breathe": return .route(.breathe)
            case "tell": return .route(.tell)
            case "lighthunt", "walk": return .route(.walk)
            default: return .tab(.play)
            }
        default: return nil
        }
    }
}

extension AppModel {
    /// Follows a `kaiku://` link: switches tab / pushes the screen. Returns false for links it doesn't know.
    @discardableResult
    public func open(_ url: URL) -> Bool {
        guard let link = DeepLink.parse(url) else { return false }
        switch link {
        case .tab(let t): selectedTab = t
        case .route(let r): deepLink = r
        case .phq9: phq9Requested = true
        }
        return true
    }

    /// The web PHQ-9 page for this home (opened in the browser).
    public var phq9URL: URL? {
        guard let p = pairing, var c = URLComponents(url: p.baseURL, resolvingAgainstBaseURL: false) else { return nil }
        c.path = "/phq9/"
        c.queryItems = [URLQueryItem(name: "home", value: p.homeID)]
        if let token = p.token {
            var fragment = URLComponents(); fragment.queryItems = [URLQueryItem(name: "t", value: token)]
            c.percentEncodedFragment = fragment.percentEncodedQuery
        }
        return c.url
    }
}

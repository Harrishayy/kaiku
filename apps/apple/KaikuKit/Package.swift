// swift-tools-version: 5.10
// KaikuKit — everything both Apple apps share: contracts, API client, offline queue, pairing, safety gate,
// mascot, components, screens and games. The iOS and Mac targets are thin shells around `KaikuRootView`.
import PackageDescription

let package = Package(
    name: "KaikuKit",
    defaultLocalization: "en",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [.library(name: "KaikuKit", targets: ["KaikuKit"])],
    targets: [
        .target(
            name: "KaikuKit",
            resources: [.process("Resources")]
        ),
        .testTarget(name: "KaikuKitTests", dependencies: ["KaikuKit"]),
    ]
)

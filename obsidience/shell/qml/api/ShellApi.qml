import QtQml

QtObject {
    readonly property int version: 1
    readonly property ShellTheme theme: ShellTheme {}
    readonly property SurfaceLayout surfaceLayout: SurfaceLayout {}
    readonly property RealtimeState realtime: RealtimeState {}

    // surface-layout.json is the one Surface identity map; "" for other screens.
    function surfaceIdForScreen(screen) {
        return surfaceLayout.surfaceIdForOutput(screen ? screen.name : "")
    }
}

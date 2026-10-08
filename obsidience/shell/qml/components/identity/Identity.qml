import QtQuick
import QtQuick.Effects

Text {
    id: identity

    // Opt-in Stage presentation only; the secure lock keeps its static identity.
    property bool oledEnabled: false
    property bool motionActive: false
    property int driftDistance: 32
    property int travelSeconds: 3600
    property real driftX: 0
    property real driftY: 0
    property real glowOpacity: 0.8

    opacity: oledEnabled ? glowOpacity : 1
    transform: Translate {
        x: identity.oledEnabled ? identity.driftX : 0
        y: identity.oledEnabled ? identity.driftY : 0
    }

    SequentialAnimation on driftX {
        id: horizontalDrift
        running: identity.oledEnabled
        paused: horizontalDrift.running && !identity.motionActive
        loops: Animation.Infinite
        NumberAnimation { from: 0; to: identity.driftDistance; duration: identity.travelSeconds * 1000 }
        NumberAnimation { from: identity.driftDistance; to: 0; duration: identity.travelSeconds * 1000 }
    }
    SequentialAnimation on driftY {
        id: verticalDrift
        running: identity.oledEnabled
        paused: verticalDrift.running && !identity.motionActive
        loops: Animation.Infinite
        NumberAnimation { from: 0; to: identity.driftDistance; duration: identity.travelSeconds * 1130 }
        NumberAnimation { from: identity.driftDistance; to: 0; duration: identity.travelSeconds * 1130 }
    }
    SequentialAnimation on glowOpacity {
        id: glowCycle
        running: identity.oledEnabled
        paused: glowCycle.running && !identity.motionActive
        loops: Animation.Infinite
        NumberAnimation { from: 0.8; to: 0.35; duration: 12000; easing.type: Easing.InOutSine }
        NumberAnimation { from: 0.35; to: 0.8; duration: 12000; easing.type: Easing.InOutSine }
    }

    text: "OBSIDIENCE"
    color: "#e6a5f3fc"
    font.family: "JetBrains Mono"
    font.pixelSize: 13
    font.capitalization: Font.AllUppercase
    font.letterSpacing: 5.2

    layer.enabled: true
    layer.effect: MultiEffect {
        blurMax: 12
        shadowEnabled: true
        shadowColor: "#7322d3ee"
        shadowBlur: 1.0
    }
}

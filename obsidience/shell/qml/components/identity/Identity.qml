import QtQuick
import QtQuick.Effects

Text {
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

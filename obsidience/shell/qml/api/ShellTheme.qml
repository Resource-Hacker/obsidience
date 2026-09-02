pragma ComponentBehavior: Bound

import QtQml
import QtQuick
import Quickshell
import Quickshell.Io

QtObject {
    id: root

    readonly property string schema: "obsidience.shell-theme.v1"
    readonly property string palettePath: String(
        Quickshell.env("OBSIDIENCE_THEME_PATH")
        ?? "/home/wissenschafter/Projects/obsidience/obsidience/shell/theme/palette.json"
    )

    property color surface: "#eb030a10"
    property color inactiveSurface: "#f002080e"
    property color accent: "#4067e8f9"
    property color strongAccent: "#6667e8f9"
    property color inactiveBorder: "#294b54"
    property color separator: "#2667e8f9"
    property color hover: "#1a67e8f9"
    property color text: "#cffafe"
    property color muted: "#9967e8f9"
    property color inactiveText: "#7dd3fc"
    property color selection: "#102a36"
    property color shadow: "#22d3ee"

    property int borderWidth: 1
    property int cornerRadius: 12
    property int titleHeight: 32
    property string titleFont: "JetBrains Mono"
    property int titleFontSize: 10
    property real titleLetterSpacing: 2.2

    function colorToken(value) {
        return typeof value === "string"
            && /^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/.test(value)
    }

    function positiveInteger(value) {
        return Number.isInteger(value) && value > 0
    }

    function applyRecord(record) {
        if (!record || record.schema !== schema || record.name !== "Obsidience") {
            return false
        }
        const colors = record.colors
        const metrics = record.metrics
        const colorKeys = [
            "surface", "inactive_surface", "accent", "strong_accent",
            "inactive_border",
            "separator", "hover", "text", "muted", "inactive_text",
            "selection", "shadow"
        ]
        if (!colors || !metrics || colorKeys.some(key => !colorToken(colors[key]))) {
            return false
        }
        if (!positiveInteger(metrics.border_width)
                || !positiveInteger(metrics.corner_radius)
                || !positiveInteger(metrics.title_height)
                || !positiveInteger(metrics.title_font_size)
                || typeof metrics.title_font !== "string"
                || !metrics.title_font.length
                || typeof metrics.title_letter_spacing !== "number"
                || metrics.title_letter_spacing < 0) {
            return false
        }

        surface = colors.surface
        inactiveSurface = colors.inactive_surface
        accent = colors.accent
        strongAccent = colors.strong_accent
        inactiveBorder = colors.inactive_border
        separator = colors.separator
        hover = colors.hover
        text = colors.text
        muted = colors.muted
        inactiveText = colors.inactive_text
        selection = colors.selection
        shadow = colors.shadow
        borderWidth = metrics.border_width
        cornerRadius = metrics.corner_radius
        titleHeight = metrics.title_height
        titleFont = metrics.title_font
        titleFontSize = metrics.title_font_size
        titleLetterSpacing = metrics.title_letter_spacing
        return true
    }

    function reloadPalette() {
        const content = paletteFile.text()
        if (!content) {
            return
        }
        try {
            if (!applyRecord(JSON.parse(content))) {
                console.warn("Ignored invalid Obsidience shell theme")
            }
        } catch (error) {
            console.warn("Ignored invalid Obsidience shell theme:", error)
        }
    }

    property FileView paletteFile: FileView {
        id: paletteFile

        path: root.palettePath
        preload: true
        blockLoading: true
        watchChanges: true

        onLoaded: root.reloadPalette()
        onTextChanged: root.reloadPalette()
        onFileChanged: paletteFile.reload()
    }

    Component.onCompleted: reloadPalette()
}

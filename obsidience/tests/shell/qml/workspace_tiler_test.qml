import QtQml
import "../../../shell/qml/api"

QtObject {
    id: root

    readonly property WorkspaceTiler tiler: WorkspaceTiler { gap: 5 }

    function fail(message) {
        console.error("workspace tiler test failed:", message)
        Qt.exit(1)
    }

    function expect(condition, message) {
        if (!condition) fail(message)
    }

    function expectBounds(actual, expected, message) {
        expect(tiler.sameBounds(actual, expected), message)
    }

    function expectRect(actual, x, y, width, height, message) {
        expect(!!actual
            && actual.x === x && actual.y === y
            && actual.width === width && actual.height === height,
            message + ": " + JSON.stringify(actual))
    }

    Component.onCompleted: {
        const leftColumn = tiler.initialBounds("samsung", 8, 2, "left")
        expectBounds(
            leftColumn,
            tiler.makeBounds("samsung", 8, 2, 0, 0, 1, 2),
            "Meta+Left establishes the full left column"
        )
        const topLeft = tiler.resizeBounds(leftColumn, "top")
        expectBounds(
            topLeft,
            tiler.makeBounds("samsung", 8, 2, 0, 0, 1, 1),
            "Meta+Up collapses the full left column to top-left"
        )
        const twoTop = tiler.resizeBounds(topLeft, "right")
        expectBounds(
            twoTop,
            tiler.makeBounds("samsung", 8, 2, 0, 0, 2, 1),
            "Meta+Right expands one top-row column"
        )
        expectBounds(
            tiler.resizeBounds(twoTop, "bottom"),
            tiler.makeBounds("samsung", 8, 2, 0, 0, 2, 2),
            "Meta+Down expands the two top cells into four cells"
        )
        expectBounds(
            tiler.translateBounds(topLeft, "right"),
            tiler.makeBounds("samsung", 8, 2, 1, 0, 2, 1),
            "Ctrl+Meta+Right translates one cell"
        )
        expectBounds(
            tiler.translateBounds(topLeft, "left"),
            topLeft,
            "translation at a Surface edge is a no-op"
        )
        const dpFirstBounds = tiler.makeBounds("dp-4", 4, 1, 0, 0, 1, 1)
        expectBounds(
            tiler.resizeBounds(dpFirstBounds, "top"),
            dpFirstBounds,
            "DP-4 has no local tile above its only row"
        )
        const samsungBottomLeft = tiler.makeBounds(
            "samsung", 8, 2, 0, 1, 1, 2
        )
        expectBounds(
            tiler.resizeBounds(samsungBottomLeft, "bottom"),
            samsungBottomLeft,
            "Meta+Down at Samsung's bottom edge is a local no-op"
        )
        const samsungEntry = tiler.entryBounds(
            "samsung", 8, 2, "bottom", 242 / 5119
        )
        expectBounds(
            samsungEntry,
            tiler.makeBounds("samsung", 8, 2, 0, 1, 1, 2),
            "DP-4 upper-edge handoff enters Samsung bottom-left"
        )
        expectRect(
            tiler.rectForBounds(5120, 1440, 0, samsungEntry),
            5, 723, 634, 712,
            "Samsung bottom-left entry retains exact gaps"
        )
        expectBounds(
            tiler.entryBounds("usb-c", 3, 2, "left", 0.75),
            tiler.makeBounds("usb-c", 3, 2, 0, 1, 1, 2),
            "horizontal handoff maps to the matching destination row"
        )

        expectRect(
            tiler.rectForBounds(5120, 1440, 0, leftColumn),
            5, 5, 634, 1430,
            "Samsung left column uses exact outer gaps"
        )
        expectRect(
            tiler.rectForBounds(5120, 1440, 0, topLeft),
            5, 5, 634, 713,
            "Samsung top-left cell uses exact outer gaps"
        )
        const samsungSecond = tiler.rectForBounds(
            5120, 1440, 0,
            tiler.makeBounds("samsung", 8, 2, 1, 0, 2, 1)
        )
        expectRect(
            samsungSecond, 644, 5, 635, 713,
            "Samsung distributes remainder pixels deterministically"
        )
        expect(
            samsungSecond.x - (5 + 634) === 5,
            "separate Samsung cells retain an exact 5 px gap"
        )

        const usbFirst = tiler.rectForBounds(
            1920, 1200, 0,
            tiler.makeBounds("usb-c", 3, 2, 0, 0, 1, 1)
        )
        const usbSecond = tiler.rectForBounds(
            1920, 1200, 0,
            tiler.makeBounds("usb-c", 3, 2, 1, 0, 2, 1)
        )
        expectRect(usbFirst, 5, 5, 633, 593, "USB-C first cell")
        expectRect(usbSecond, 643, 5, 634, 593, "USB-C second cell")
        expect(usbSecond.x - (usbFirst.x + usbFirst.width) === 5,
               "USB-C cells retain an exact 5 px gap")

        const dpFirst = tiler.rectForBounds(
            1920, 550, 0,
            tiler.makeBounds("dp-4", 4, 1, 0, 0, 1, 1)
        )
        const dpThird = tiler.rectForBounds(
            1920, 550, 0,
            tiler.makeBounds("dp-4", 4, 1, 2, 0, 3, 1)
        )
        expectRect(dpFirst, 5, 5, 474, 540, "DP-4 first cell")
        expectRect(dpThird, 963, 5, 473, 540, "DP-4 third cell")

        Qt.exit(0)
    }
}

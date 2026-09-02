pragma ComponentBehavior: Bound

import QtQuick
import QtWebEngine
import org.kde.plasma.plasmoid

WallpaperItem {
    id: root

    Rectangle {
        anchors.fill: parent
        color: "#02060c"
    }

    WebEngineView {
        anchors.fill: parent
        url: "http://127.0.0.1:8765/shell/knowledge/?surface=knowledge&surface_id=samsung&lock=1"
        backgroundColor: "#02060c"
    }
}

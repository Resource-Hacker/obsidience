pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Widgets
import "../../components/visual"

Item {
    id: root

    readonly property string apiBase: "http://127.0.0.1:8765"
    property string mode: "installed"
    property var applications: []
    property var results: []
    property var backend: ({"available": false, "name": "PackageKit"})
    property bool loading: false
    property string actionPackage: ""
    property string confirmPackage: ""
    property string message: ""
    property string errorMessage: ""

    readonly property bool busy: loading || actionPackage !== ""
    readonly property var visibleRows: {
        const rows = mode === "installed" ? applications : results
        const needle = searchField.text.trim().toLowerCase()
        if (mode !== "installed" || needle === "") {
            return rows
        }
        return rows.filter(row => [
            row.label,
            row.package,
            row.description,
            row.desktop_id
        ].join(" ").toLowerCase().indexOf(needle) >= 0)
    }

    function responseError(request, fallback) {
        const raw = request.responseText || ""
        try {
            const parsed = JSON.parse(raw)
            if (parsed && typeof parsed.detail === "string" && parsed.detail) {
                return parsed.detail
            }
        } catch (error) {
            // Plain text is already useful.
        }
        return raw || fallback + " (" + request.status + ")"
    }

    function request(method, path, body, onSuccess, onFailure) {
        const xhr = new XMLHttpRequest()
        xhr.open(method, apiBase + path)
        if (body !== null) {
            xhr.setRequestHeader("content-type", "application/json")
        }
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE) {
                return
            }
            if (xhr.status < 200 || xhr.status >= 300) {
                onFailure(responseError(xhr, "Software request failed"))
                return
            }
            try {
                onSuccess(JSON.parse(xhr.responseText))
            } catch (error) {
                onFailure("Obsidience returned invalid software data.")
            }
        }
        xhr.send(body === null ? null : JSON.stringify(body))
    }

    function refresh() {
        if (actionPackage !== "") {
            return
        }
        loading = true
        errorMessage = ""
        request("GET", "/api/applications", null, function(payload) {
            root.applications = payload && Array.isArray(payload.applications)
                ? payload.applications : []
            root.backend = payload && payload.backend ? payload.backend : ({})
            root.loading = false
        }, function(error) {
            root.errorMessage = error
            root.loading = false
        })
    }

    function findSoftware() {
        const query = searchField.text.trim()
        if (query.length < 2 || busy) {
            errorMessage = query.length < 2
                ? "Enter at least two characters to find software." : ""
            return
        }
        loading = true
        confirmPackage = ""
        message = ""
        errorMessage = ""
        request(
            "GET",
            "/api/applications/search?q=" + encodeURIComponent(query),
            null,
            function(payload) {
                root.results = payload && Array.isArray(payload.results)
                    ? payload.results : []
                root.backend = payload && payload.backend ? payload.backend : root.backend
                root.loading = false
                root.message = root.results.length
                    ? "" : "No software matched “" + query + "”."
            },
            function(error) {
                root.errorMessage = error
                root.loading = false
            }
        )
    }

    function install(row) {
        if (!row || row.installed === true || busy) {
            return
        }
        runAction("install", row.package)
    }

    function remove(row) {
        if (!row || row.manageable !== true || busy) {
            return
        }
        if (confirmPackage !== row.package) {
            confirmPackage = row.package
            message = "Click UNINSTALL again to remove " + row.package + "."
            return
        }
        runAction("remove", row.package)
    }

    function runAction(action, packageName) {
        actionPackage = packageName
        confirmPackage = ""
        message = action === "install"
            ? "Installing " + packageName + "…"
            : "Removing " + packageName + "…"
        errorMessage = ""
        request(
            "POST",
            "/api/applications/" + action,
            {"package": packageName},
            function(payload) {
                root.actionPackage = ""
                root.message = payload && payload.message ? payload.message : "Complete."
                if (action === "install") {
                    root.mode = "installed"
                    searchField.text = ""
                    root.results = []
                }
                root.refresh()
            },
            function(error) {
                root.actionPackage = ""
                root.errorMessage = error
            }
        )
    }

    function selectMode(nextMode) {
        if (mode === nextMode || busy) {
            return
        }
        mode = nextMode
        searchField.text = ""
        confirmPackage = ""
        message = ""
        errorMessage = ""
        if (nextMode === "installed") {
            refresh()
        } else {
            results = []
            searchField.forceActiveFocus()
        }
    }

    Component.onCompleted: refresh()
    onVisibleChanged: if (visible) refresh()

    Timer {
        interval: 2000
        repeat: true
        running: root.visible && root.errorMessage !== ""
            && root.actionPackage === ""
        onTriggered: root.refresh()
    }

    Column {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 10

        Rectangle {
            width: parent.width
            height: heading.implicitHeight + 20
            radius: 8
            color: "#17071119"
            border.width: 1
            border.color: "#2467e8f9"

            Row {
                id: heading

                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 10
                spacing: 10

                ShellIcon {
                    anchors.verticalCenter: parent.verticalCenter
                    width: 30
                    height: 30
                    glyph: "applications"
                    iconColor: "#67e8f9"
                    iconOpacity: 0.88
                }

                Column {
                    width: Math.max(160, parent.width - 126)
                    spacing: 3

                    Text {
                        width: parent.width
                        text: "APPLICATIONS"
                        color: "#e6faff"
                        font.family: "JetBrains Mono"
                        font.pixelSize: 11
                        font.letterSpacing: 1.8
                    }

                    Text {
                        width: parent.width
                        text: root.backend.available === true
                            ? "INSTALLED SOFTWARE · PACKAGEKIT / "
                                + String(root.backend.backend || "SYSTEM").toUpperCase()
                            : String(root.backend.message || "SOFTWARE MANAGER UNAVAILABLE")
                        color: root.backend.available === true ? "#8067e8f9" : "#bffca5a5"
                        elide: Text.ElideRight
                        font.family: "JetBrains Mono"
                        font.pixelSize: 8
                        font.capitalization: Font.AllUppercase
                        font.letterSpacing: 1.2
                    }
                }

                GlowButton {
                    width: 72
                    height: 26
                    text: root.loading ? "LOADING" : "REFRESH"
                    accent: "#67e8f9"
                    foreground: "#cffafe"
                    enabled: !root.busy
                    onClicked: root.mode === "installed"
                        ? root.refresh() : root.findSoftware()
                }
            }
        }

        Row {
            width: parent.width
            spacing: 8

            Repeater {
                model: [
                    {"id": "installed", "label": "INSTALLED"},
                    {"id": "find", "label": "FIND SOFTWARE"}
                ]

                delegate: GlowButton {
                    id: modeButton

                    required property var modelData
                    width: modelData.id === "installed" ? 100 : 130
                    height: 28
                    text: modelData.label
                    selected: root.mode === modelData.id
                    accent: "#67e8f9"
                    foreground: "#cffafe"
                    onClicked: root.selectMode(modelData.id)
                }
            }

            Rectangle {
                width: Math.max(160, parent.width - 246)
                height: 28
                radius: 5
                color: "#d908131e"
                border.width: 1
                border.color: searchField.activeFocus ? "#8067e8f9" : "#3367e8f9"

                TextField {
                    id: searchField

                    anchors.fill: parent
                    leftPadding: 10
                    rightPadding: 10
                    placeholderText: root.mode === "installed"
                        ? "Filter installed applications…" : "Search software packages…"
                    color: "#e6faff"
                    placeholderTextColor: "#5967e8f9"
                    selectionColor: "#4067e8f9"
                    selectedTextColor: "#effcff"
                    background: null
                    font.family: "JetBrains Mono"
                    font.pixelSize: 9
                    onAccepted: if (root.mode === "find") root.findSoftware()
                    onTextChanged: {
                        root.confirmPackage = ""
                        root.message = ""
                    }
                }
            }

            GlowButton {
                visible: root.mode === "find"
                width: visible ? 64 : 0
                height: 28
                text: "SEARCH"
                accent: "#67e8f9"
                foreground: "#cffafe"
                enabled: !root.busy && searchField.text.trim().length >= 2
                onClicked: root.findSoftware()
            }
        }

        Rectangle {
            width: parent.width
            height: Math.max(80, parent.height - 142)
            radius: 8
            color: "#a3061018"
            border.width: 1
            border.color: "#2467e8f9"
            clip: true

            ListView {
                id: applicationList

                anchors.fill: parent
                anchors.margins: 6
                model: root.visibleRows
                spacing: 4
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar {}

                delegate: Rectangle {
                    id: applicationRow

                    required property var modelData
                    width: applicationList.width
                    height: 62
                    radius: 6
                    color: rowMouse.containsMouse ? "#1a67e8f9" : "#78071119"
                    border.width: 1
                    border.color: rowMouse.containsMouse ? "#5967e8f9" : "#1867e8f9"

                    MouseArea {
                        id: rowMouse

                        anchors.fill: parent
                        hoverEnabled: true
                        acceptedButtons: Qt.NoButton
                    }

                    IconImage {
                        anchors.left: parent.left
                        anchors.leftMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        width: 34
                        height: 34
                        source: Quickshell.iconPath(
                            String(applicationRow.modelData.icon || ""),
                            "application-x-executable"
                        )
                        asynchronous: true
                        mipmap: true
                    }

                    Column {
                        anchors.left: parent.left
                        anchors.leftMargin: 54
                        anchors.right: actionButton.left
                        anchors.rightMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 2

                        Text {
                            width: parent.width
                            text: String(applicationRow.modelData.label || "Application")
                            color: "#e6faff"
                            elide: Text.ElideRight
                            font.family: "JetBrains Mono"
                            font.pixelSize: 10
                            font.weight: Font.Medium
                        }

                        Text {
                            width: parent.width
                            text: String(applicationRow.modelData.description || "")
                            color: "#9967e8f9"
                            elide: Text.ElideRight
                            visible: text !== ""
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                        }

                        Text {
                            width: parent.width
                            text: [
                                applicationRow.modelData.package || "LOCAL DESKTOP ENTRY",
                                applicationRow.modelData.version || "",
                                applicationRow.modelData.repository || ""
                            ].filter(value => String(value) !== "").join(" · ")
                            color: "#666ee7b7"
                            elide: Text.ElideRight
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                            font.capitalization: Font.AllUppercase
                            font.letterSpacing: 0.6
                        }
                    }

                    GlowButton {
                        id: actionButton

                        anchors.right: parent.right
                        anchors.rightMargin: 9
                        anchors.verticalCenter: parent.verticalCenter
                        width: 104
                        height: 28
                        readonly property bool installedView: root.mode === "installed"
                        readonly property bool removable: installedView
                            && applicationRow.modelData.manageable === true
                        readonly property bool alreadyInstalled: !installedView
                            && applicationRow.modelData.installed === true
                        text: root.actionPackage !== ""
                            && root.actionPackage === applicationRow.modelData.package
                            ? (installedView ? "REMOVING…" : "INSTALLING…")
                            : removable
                                ? root.confirmPackage === applicationRow.modelData.package
                                    ? "CONFIRM" : "UNINSTALL"
                                : alreadyInstalled ? "INSTALLED"
                                    : installedView ? "LOCAL" : "INSTALL"
                        accent: removable ? "#f87171" : "#6ee7b7"
                        foreground: removable ? "#fecaca" : "#d1fae5"
                        enabled: !root.busy && root.backend.available === true
                            && (removable || (!installedView && !alreadyInstalled))
                        onClicked: installedView
                            ? root.remove(applicationRow.modelData)
                            : root.install(applicationRow.modelData)
                    }
                }

                Text {
                    anchors.centerIn: parent
                    width: Math.max(180, parent.width - 48)
                    visible: !root.loading && applicationList.count === 0
                    text: root.mode === "find" && searchField.text.trim() === ""
                        ? "SEARCH FOR SOFTWARE TO INSTALL"
                        : root.message !== "" ? root.message : "NO APPLICATIONS FOUND"
                    color: "#7367e8f9"
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    font.family: "JetBrains Mono"
                    font.pixelSize: 9
                    font.capitalization: Font.AllUppercase
                    font.letterSpacing: 1.2
                }
            }
        }

        Text {
            width: parent.width
            height: 18
            text: root.errorMessage !== "" ? root.errorMessage
                : root.message !== "" ? root.message
                    : root.mode === "installed"
                        ? root.visibleRows.length + " INSTALLED APPLICATIONS"
                        : root.results.length + " SOFTWARE RESULTS"
            color: root.errorMessage !== "" ? "#fca5a5" : "#8067e8f9"
            elide: Text.ElideRight
            horizontalAlignment: Text.AlignHCenter
            font.family: "JetBrains Mono"
            font.pixelSize: 8
            font.capitalization: Font.AllUppercase
            font.letterSpacing: 1.0
        }
    }
}

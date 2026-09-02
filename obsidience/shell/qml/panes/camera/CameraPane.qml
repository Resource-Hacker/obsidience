pragma ComponentBehavior: Bound

import QtQuick
import QtMultimedia

Rectangle {
    id: root

    readonly property string apiBase: "http://127.0.0.1:8765"
    property string phase: "waiting"
    property string errorMessage: ""
    property string selectedId: ""
    property string selectedLabel: "Selected physical camera"
    property var selectedDevice: null
    property bool captureRequested: false
    property bool initialized: false
    property int activationGeneration: 0
    property int deviceMatchAttempts: 0

    color: "#020609"
    clip: true

    function responseError(request, fallback) {
        const raw = request.responseText || ""
        try {
            const parsed = JSON.parse(raw)
            if (parsed && typeof parsed.detail === "string" && parsed.detail) {
                return parsed.detail
            }
        } catch (error) {
            // Plain-text failures are already useful.
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
                onFailure(responseError(xhr, "Camera request failed"))
                return
            }
            try {
                onSuccess(JSON.parse(xhr.responseText))
            } catch (error) {
                onFailure("Obsidience returned invalid camera state.")
            }
        }
        xhr.send(body === null ? null : JSON.stringify(body))
    }

    function normalizeLabel(value) {
        return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "")
    }

    function deviceId(device) {
        if (!device) {
            return ""
        }
        try {
            return String(device.id)
        } catch (error) {
            return ""
        }
    }

    function selectedHardwareCamera(payload) {
        const interfaces = payload && Array.isArray(payload.interfaces)
            ? payload.interfaces : []
        const cameraSlot = interfaces.find(slot => slot && slot.id === "camera")
        if (!cameraSlot) {
            return null
        }
        const options = Array.isArray(cameraSlot.options) ? cameraSlot.options : []
        const option = options.find(candidate => candidate
            && candidate.id === cameraSlot.selected)
        return cameraSlot.selected !== "none" && option && option.available === true
            ? option : null
    }

    function matchingDevice() {
        const devices = mediaDevices.videoInputs || []
        const selectedPath = selectedId.indexOf("v4l2:") === 0
            ? selectedId.slice(5) : selectedId
        for (const device of devices) {
            const id = deviceId(device)
            if (id === selectedPath || id === selectedId
                    || (selectedPath && id.indexOf(selectedPath) >= 0)) {
                return device
            }
        }

        const expected = normalizeLabel(selectedLabel)
        const aliases = selectedLabel.split(":")
            .map(value => normalizeLabel(value))
            .filter(value => value.length >= 5)
        const matched = []
        for (const device of devices) {
            const actual = normalizeLabel(device.description)
            if (actual && expected && (actual === expected
                    || actual.indexOf(expected) >= 0
                    || expected.indexOf(actual) >= 0
                    || aliases.some(alias => actual.indexOf(alias) >= 0
                        || alias.indexOf(actual) >= 0))) {
                matched.push(device)
            }
        }
        if (matched.length === 1) {
            return matched[0]
        }
        return devices.length === 1 ? devices[0] : null
    }

    function preferredFormat(device) {
        const formats = device && device.videoFormats ? device.videoFormats : []
        let fallback = formats.length ? formats[0] : null
        let preferred = null
        for (const format of formats) {
            const resolution = format.resolution
            const width = resolution ? Number(resolution.width) : 0
            const height = resolution ? Number(resolution.height) : 0
            if (width === 640 && height === 480) {
                return format
            }
            if (width > 0 && height > 0 && width <= 1280 && height <= 720) {
                preferred = preferred || format
            }
        }
        return preferred || fallback
    }

    function resolveVideoDevice(generation) {
        if (generation !== activationGeneration || phase !== "starting") {
            return
        }
        const device = matchingDevice()
        if (device) {
            selectedDevice = device
            const format = preferredFormat(device)
            if (format) {
                camera.cameraFormat = format
            }
            captureRequested = true
            return
        }
        deviceMatchAttempts += 1
        if (deviceMatchAttempts >= 20) {
            fail("The Hardware camera could not be matched to one native video device.")
            return
        }
        deviceRetry.restart()
    }

    function ensurePower(generation) {
        request("GET", "/api/hardware/camera", null, function(state) {
            if (generation !== root.activationGeneration) {
                return
            }
            if (state && state.active === true) {
                root.resolveVideoDevice(generation)
                return
            }
            root.request("POST", "/api/hardware/camera", {"active": true}, function() {
                root.resolveVideoDevice(generation)
            }, function(message) {
                if (generation === root.activationGeneration) {
                    root.fail(message)
                }
            })
        }, function(message) {
            if (generation === root.activationGeneration) {
                root.fail(message)
            }
        })
    }

    function activatePane() {
        activationGeneration += 1
        const generation = activationGeneration
        phase = "starting"
        errorMessage = ""
        captureRequested = false
        selectedDevice = null
        selectedId = ""
        selectedLabel = "Selected physical camera"
        deviceMatchAttempts = 0

        request("GET", "/api/hardware", null, function(payload) {
            if (generation !== root.activationGeneration) {
                return
            }
            const selected = root.selectedHardwareCamera(payload)
            if (!selected) {
                root.fail("Select an available physical camera in Hardware first.")
                return
            }
            root.selectedId = String(selected.id)
            root.selectedLabel = String(selected.label || selected.detail || selected.id)
            root.ensurePower(generation)
        }, function(message) {
            if (generation === root.activationGeneration) {
                root.fail(message)
            }
        })
    }

    function releasePane() {
        activationGeneration += 1
        deviceRetry.stop()
        captureRequested = false
        selectedDevice = null
        phase = "waiting"
        errorMessage = ""
        request("POST", "/api/hardware/camera", {"active": false}, function() {
            // The pane owns only its view; a successful close needs no UI update.
        }, function() {
            // Realtime may own the camera and correctly reject power-off with 409.
        })
    }

    function fail(message) {
        captureRequested = false
        selectedDevice = null
        errorMessage = String(message || "The camera video could not be opened.").slice(0, 240)
        phase = "error"
    }

    Component.onCompleted: {
        initialized = true
        if (visible) {
            activatePane()
        }
    }

    Component.onDestruction: {
        captureRequested = false
        request("POST", "/api/hardware/camera", {"active": false}, function() {}, function() {})
    }

    onVisibleChanged: {
        if (!initialized) {
            return
        }
        if (visible) {
            activatePane()
        } else {
            releasePane()
        }
    }

    MediaDevices {
        id: mediaDevices

        onVideoInputsChanged: {
            if (root.phase === "starting") {
                root.resolveVideoDevice(root.activationGeneration)
            }
        }
    }

    Timer {
        id: deviceRetry

        interval: 250
        repeat: false
        onTriggered: root.resolveVideoDevice(root.activationGeneration)
    }

    Camera {
        id: camera

        cameraDevice: root.selectedDevice || mediaDevices.defaultVideoInput
        active: root.captureRequested && root.selectedDevice !== null

        onActiveChanged: active => {
            if (active && root.captureRequested) {
                root.phase = "live"
                root.errorMessage = ""
            } else if (root.captureRequested && root.phase !== "error") {
                root.phase = "starting"
            }
        }
        onErrorOccurred: (error, errorString) => {
            if (root.captureRequested) {
                root.fail(errorString || "The selected camera is busy or unavailable.")
            }
        }
    }

    CaptureSession {
        camera: camera
        videoOutput: videoOutput
    }

    Item {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: footer.top
        clip: true

        VideoOutput {
            id: videoOutput

            anchors.fill: parent
            visible: root.phase === "live"
            fillMode: VideoOutput.PreserveAspectFit
        }

        Item {
            anchors.fill: parent
            visible: root.phase !== "live"

            Column {
                anchors.centerIn: parent
                width: Math.max(160, Math.min(420, parent.width - 48))
                spacing: 12

                Text {
                    width: parent.width
                    text: root.phase === "error" ? "△"
                        : root.phase === "starting" ? "◌" : "◇"
                    color: root.phase === "error" ? "#fda4af" : "#7367e8f9"
                    horizontalAlignment: Text.AlignHCenter
                    font.family: "JetBrains Mono"
                    font.pixelSize: 26

                    RotationAnimator on rotation {
                        from: 0
                        to: 360
                        duration: 1100
                        loops: Animation.Infinite
                        running: root.phase === "starting"
                    }
                }

                Text {
                    width: parent.width
                    text: root.phase === "error" ? root.errorMessage
                        : root.phase === "starting" ? "OPENING VIDEO-ONLY CAMERA…"
                            : "WAKING PHYSICAL CAMERA…"
                    color: root.phase === "error" ? "#fecdd3" : "#807dd3fc"
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    font.family: "JetBrains Mono"
                    font.pixelSize: 10
                    font.letterSpacing: 0.7
                    lineHeight: 1.45
                    lineHeightMode: Text.ProportionalHeight
                }

                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    visible: root.phase === "error" && root.visible
                    width: 84
                    height: 28
                    radius: 5
                    color: retryMouse.containsMouse ? "#2634d399" : "#12071119"
                    border.width: 1
                    border.color: "#4067e8f9"

                    Text {
                        anchors.centerIn: parent
                        text: "RETRY"
                        color: "#cffafe"
                        font.family: "JetBrains Mono"
                        font.pixelSize: 8
                        font.letterSpacing: 1.1
                    }

                    MouseArea {
                        id: retryMouse

                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.activatePane()
                    }
                }
            }
        }
    }

    Rectangle {
        id: footer

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 36
        color: "#f0020a12"

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 1
            color: "#2467e8f9"
        }

        Text {
            anchors.left: parent.left
            anchors.right: stateLabel.left
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            text: root.selectedLabel
            color: "#99cffafe"
            elide: Text.ElideRight
            font.family: "JetBrains Mono"
            font.pixelSize: 8
        }

        Text {
            id: stateLabel

            anchors.right: parent.right
            anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            text: root.phase === "live" ? "VIDEO ONLY · LIVE" : "VIDEO ONLY"
            color: root.phase === "live" ? "#a76ee7b7" : "#5267e8f9"
            font.family: "JetBrains Mono"
            font.pixelSize: 8
            font.letterSpacing: 0.7
        }
    }
}

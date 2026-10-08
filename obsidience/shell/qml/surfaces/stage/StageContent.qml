pragma ComponentBehavior: Bound

import QtQuick
import "../../components/identity"

Item {
    id: content

    required property bool locked
    property bool oledEnabled: false
    property bool motionActive: false
    property int driftDistance: 32
    property int travelSeconds: 3600

    Identity {
        visible: !content.locked
        oledEnabled: content.oledEnabled
        motionActive: content.motionActive && visible
        driftDistance: content.driftDistance
        travelSeconds: content.travelSeconds
        z: 10
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.leftMargin: 20
        anchors.topMargin: 12
    }
}

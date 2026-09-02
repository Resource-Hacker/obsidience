pragma ComponentBehavior: Bound

import QtQuick
import "../../components/identity"

Item {
    id: content

    required property string surfaceId
    required property bool locked

    Identity {
        visible: !content.locked
        z: 10
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.leftMargin: 20
        anchors.topMargin: 12
    }
}

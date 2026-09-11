pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import "../visual"

Row {
    id: root
    required property ArticleCheckouts controller
    required property var node
    property var agents: []
    property int buttonSize: 20
    spacing: 2
    height: buttonSize
    Repeater {
        model: root.agents.filter(item => item.id !== "library")
        delegate: Button {
            id: choice
            required property var modelData
            width: root.buttonSize
            height: root.buttonSize
            enabled: !root.controller.pending && root.controller.state(root.node, modelData.role).editable
            ToolTip.visible: hovered
            ToolTip.text: root.controller.hint(root.node, modelData)
            contentItem: RoleIcon {
                role: choice.modelData.role
                opacity: root.controller.state(root.node, choice.modelData.role).partial ? 0.6
                    : root.controller.state(root.node, choice.modelData.role).checked ? 1 : 0.25
            }
            background: Rectangle { color: choice.hovered ? "#1867e8f9" : "transparent"; radius: 3 }
            onClicked: root.controller.toggle(root.node, modelData)
        }
    }
}

pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../theme"

AbstractButton {
    id: control
    property string iconName: "home"
    property bool compact: false
    implicitHeight: 42
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.name: text
    background: Rectangle {
        radius: Theme.radius
        color: control.checked ? Theme.selection : control.down ? Theme.strong : control.hovered
                                                                  ? Theme.hover : "transparent"
        border.width: control.visualFocus ? 2 : 0
        border.color: Theme.accent
        Behavior on color {
            ColorAnimation {
                duration: Theme.motion
            }
        }
        Rectangle {
            visible: control.checked
            width: 3
            height: 16
            radius: 1
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.accent
        }
    }
    contentItem: RowLayout {
        spacing: 12
        SplatButton {
            iconName: control.iconName
            kind: "ghost"
            enabled: false
            opacity: 1
            width: 36
            Layout.preferredWidth: 36
            icon.color: control.checked ? Theme.accent : Theme.secondary
        }
        SplatLabel {
            visible: !control.compact
            text: control.text
            color: control.checked ? Theme.text : Theme.secondary
            font.weight: control.checked ? Font.DemiBold : Font.Normal
            Layout.fillWidth: true
        }
    }
    ToolTip.visible: hovered && compact
    ToolTip.text: text
}

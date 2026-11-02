pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import "../theme"

CheckBox {
    id: control
    font.family: Theme.font
    font.pixelSize: Theme.body
    spacing: Theme.space
    implicitHeight: Math.max(Theme.control, implicitContentHeight + Theme.space)
    opacity: enabled ? 1 : 0.5
    hoverEnabled: true
    indicator: Rectangle {
        width: Theme.icon
        height: Theme.icon
        x: control.leftPadding
        anchors.verticalCenter: parent.verticalCenter
        radius: Theme.controlRadius
        color: control.checked ? Theme.accent : control.down ? Theme.hover : Theme.background
        border.width: control.visualFocus ? 2 : 1
        border.color: control.visualFocus || control.hovered ? Theme.accent : Theme.strong
        SplatButton {
            anchors.centerIn: parent
            width: Theme.icon
            height: Theme.icon
            leftPadding: 1
            rightPadding: 1
            iconName: "check"
            icon.width: Theme.icon - 2
            icon.height: Theme.icon - 2
            icon.color: Theme.accentText
            visible: control.checked
            kind: "ghost"
            enabled: false
            opacity: 1
        }
    }
    contentItem: SplatLabel {
        text: control.text
        leftPadding: control.indicator.width + control.spacing
        verticalAlignment: Text.AlignVCenter
    }
    Accessible.name: text
}

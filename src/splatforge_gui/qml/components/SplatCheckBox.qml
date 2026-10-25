pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import "../theme"

CheckBox {
    id: control
    font.family: Theme.font
    font.pixelSize: Theme.body
    spacing: 10
    implicitHeight: Math.max(36, implicitContentHeight + 12)
    opacity: enabled ? 1 : 0.5
    hoverEnabled: true
    indicator: Rectangle {
        width: 20
        height: 20
        x: control.leftPadding
        anchors.verticalCenter: parent.verticalCenter
        radius: 4
        color: control.checked ? Theme.accent : control.down ? Theme.hover : Theme.background
        border.width: control.visualFocus ? 2 : 1
        border.color: control.visualFocus || control.hovered ? Theme.accent : Theme.strong
        SplatButton {
            anchors.centerIn: parent
            width: 20
            height: 20
            leftPadding: 1
            rightPadding: 1
            iconName: "check"
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

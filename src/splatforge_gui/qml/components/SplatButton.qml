pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import "../theme"

Button {
    id: control
    property string kind: "secondary"
    property string iconName: ""
    implicitHeight: Theme.control
    implicitWidth: text === "" ? Theme.control : Math.max(implicitContentWidth + leftPadding + rightPadding, Theme.control)
    leftPadding: text === "" ? (Theme.control - Theme.icon) / 2 : Theme.controlInset
    rightPadding: leftPadding
    spacing: Theme.space
    font.family: Theme.font
    font.pixelSize: Theme.body
    font.weight: kind === "primary" ? Font.DemiBold : Font.Normal
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    icon.source: iconName ? Qt.resolvedUrl("../icons/" + iconName + ".svg") : ""
    icon.width: Theme.icon
    icon.height: Theme.icon
    icon.color: !enabled ? Theme.muted : kind === "primary" ? Theme.accentText : kind === "danger"
                                                              ? Theme.danger : Theme.text
    palette.buttonText: icon.color
    opacity: enabled ? 1 : 0.45
    Accessible.name: text
    background: Rectangle {
        radius: Theme.controlRadius
        color: control.kind === "primary" ? (control.down ? Theme.accentPressed : control.hovered
                                                            ? Theme.accentHover : Theme.accent) :
                                            control.down ? Theme.strong : control.hovered
                                                           ? Theme.hover : control.kind === "ghost"
                                                             ? "transparent" : Theme.raised
        border.width: control.visualFocus ? 2 : control.kind === "secondary" ? 1 : 0
        border.color: control.visualFocus ? Theme.accent : Theme.border
    }
    ToolTip.visible: (hovered || visualFocus) && text === ""
    ToolTip.text: Accessible.name
}

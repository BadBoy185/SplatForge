pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import "../theme"

Button {
    id: control
    property string kind: "secondary"
    property string iconName: ""
    implicitHeight: Theme.control
    implicitWidth: Math.max(implicitContentWidth + 28, 36)
    leftPadding: text === "" ? 9 : 14
    rightPadding: text === "" ? 9 : 14
    spacing: 8
    font.family: Theme.font
    font.pixelSize: Theme.body
    font.weight: Font.DemiBold
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    icon.source: iconName ? Qt.resolvedUrl("../icons/" + iconName + ".svg") : ""
    icon.width: 18
    icon.height: 18
    icon.color: !enabled ? Theme.muted : kind === "primary" ? Theme.accentText : kind === "danger"
                                                              ? Theme.danger : Theme.text
    palette.buttonText: icon.color
    opacity: enabled ? 1 : 0.45
    Accessible.name: text
    background: Rectangle {
        radius: Theme.radius
        color: control.kind === "primary" ? (control.down ? Theme.accentPressed : control.hovered
                                                            ? Theme.accentHover : Theme.accent) :
                                            control.down ? Theme.strong : control.hovered
                                                           ? Theme.hover : control.kind === "ghost"
                                                             ? "transparent" : Theme.raised
        border.width: control.visualFocus ? 2 : control.kind === "secondary" ? 1 : 0
        border.color: control.visualFocus ? Theme.accent : Theme.border
        Behavior on color {
            ColorAnimation {
                duration: Theme.motion
            }
        }
    }
    ToolTip.visible: hovered && text === ""
    ToolTip.text: Accessible.name
}

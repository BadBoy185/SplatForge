pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import "../theme"

TextField {
    id: control
    implicitHeight: Theme.control
    color: Theme.text
    placeholderTextColor: Theme.muted
    selectionColor: Theme.selection
    selectedTextColor: Theme.text
    font.family: Theme.font
    font.pixelSize: Theme.body
    leftPadding: 12
    rightPadding: 12
    selectByMouse: true
    background: Rectangle {
        radius: Theme.radius
        color: Theme.background
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? Theme.accent : control.hovered ? Theme.strong :
                                                                             Theme.border

        opacity: control.enabled ? 1 : 0.5
    }
}

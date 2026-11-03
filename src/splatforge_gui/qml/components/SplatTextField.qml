pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import "../theme"

TextField {
    id: control
    property string editingBuffer: ""

    implicitHeight: Theme.control
    color: Theme.text
    placeholderTextColor: Theme.muted
    selectionColor: Theme.selection
    selectedTextColor: Theme.text
    font.family: Theme.font
    font.pixelSize: Theme.body
    leftPadding: Theme.controlInset
    rightPadding: Theme.controlInset
    selectByMouse: true

    onActiveFocusChanged: {
        if (activeFocus)
            editingBuffer = text;
    }
    onTextEdited: editingBuffer = text
    onTextChanged: {
        if (!activeFocus)
            return;
        Qt.callLater(function() {
            if (control.activeFocus && control.text !== control.editingBuffer)
                control.text = control.editingBuffer;
        });
    }

    background: Rectangle {
        radius: Theme.controlRadius
        color: Theme.background
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? Theme.accent : control.hovered ? Theme.strong :
                                                                             Theme.border

        opacity: control.enabled ? 1 : 0.5
    }
}

pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import "../theme"

ComboBox {
    id: control
    property string enabledRole: ""
    property var selectedValue: undefined
    function synchronizeSelection() {
        if (selectedValue !== undefined)
            currentIndex = indexOfValue(selectedValue);
    }
    onSelectedValueChanged: synchronizeSelection()
    onCountChanged: synchronizeSelection()
    onModelChanged: Qt.callLater(synchronizeSelection)
    implicitHeight: Theme.control
    implicitWidth: 240
    font.family: Theme.font
    font.pixelSize: Theme.body
    leftPadding: 12
    rightPadding: 32
    opacity: enabled ? 1 : 0.45
    contentItem: SplatLabel {
        text: control.displayText
        elide: Text.ElideRight
        verticalAlignment: Text.AlignVCenter
        wrapMode: Text.NoWrap
    }
    indicator: SplatButton {
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        width: 30
        height: 30
        kind: "ghost"
        iconName: "chevron"
        focusPolicy: Qt.NoFocus
        onClicked: control.popup.visible = !control.popup.visible
        Accessible.name: "Choose option"
    }
    background: Rectangle {
        radius: Theme.radius
        color: control.down ? Theme.hover : Theme.raised
        border.color: control.visualFocus ? Theme.accent : control.hovered ? Theme.strong :
                                                                             Theme.border

        border.width: control.visualFocus ? 2 : 1
    }
    delegate: ItemDelegate {
        id: option
        required property int index
        required property var model
        width: control.width
        height: Theme.control
        text: control.textRole ? model[control.textRole] : model.modelData
        highlighted: control.highlightedIndex === index
        enabled: !control.enabledRole || model[control.enabledRole] !== false
        opacity: enabled ? 1 : 0.45
        contentItem: SplatLabel {
            text: option.text
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
            wrapMode: Text.NoWrap
        }
        background: Rectangle {
            color: option.highlighted ? Theme.selection : Theme.raised
            radius: 4
        }
    }
    popup: Popup {
        y: control.height + 4
        width: control.width
        padding: 4
        implicitHeight: Math.min(contentItem.implicitHeight + 8, 320)
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator {}
        }
        background: Rectangle {
            color: Theme.raised
            radius: Theme.radius
            border.color: Theme.strong
        }
    }
}

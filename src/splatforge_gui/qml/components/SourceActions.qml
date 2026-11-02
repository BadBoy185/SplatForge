pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../theme"

RowLayout {
    id: actions
    required property var vm
    required property var record
    required property string sourceId
    property string namePrefix: ""
    readonly property bool interacting: menu.visible || menuButton.activeFocus
    signal detailsRequested
    spacing: 0
    SplatButton {
        id: menuButton
        objectName: actions.namePrefix + "actions-" + actions.sourceId
        text: "⋯"
        kind: "ghost"
        Accessible.name: "Actions for " + actions.record.filename
        onClicked: menu.popup(menuButton, 0, menuButton.height)
    }
    Menu {
        id: menu
        palette.window: Theme.surface
        palette.windowText: Theme.text
        MenuItem {
            objectName: actions.namePrefix + "preview-" + actions.sourceId
            text: "View material"
            onTriggered: actions.vm.media.showSource(actions.sourceId)
        }
        MenuItem {
            objectName: actions.namePrefix + "details-" + actions.sourceId
            text: "Details…"
            onTriggered: {
                actions.vm.media.focusSource(actions.sourceId);
                actions.detailsRequested();
            }
        }
        MenuItem {
            objectName: actions.namePrefix + "participation-" + actions.sourceId
            enabled: actions.vm.state.canMutate && actions.vm.state.participationSupported
            text: actions.record.isIncluded === false ? "Restore to processing" : "Exclude from processing"
            Accessible.description: "Original file stays in place. Applies to the selection when this source is selected."
            onTriggered: actions.vm.setSourceIncluded(actions.sourceId, actions.record.isIncluded === false)
        }
    }
}

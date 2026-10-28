pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts

RowLayout {
    id: actions
    required property var vm
    required property var record
    required property string sourceId
    property string namePrefix: ""
    signal detailsRequested()
    spacing: 0
    SplatButton {
        objectName: actions.namePrefix + "preview-" + actions.sourceId
        iconName: "play"
        kind: "ghost"
        visible: actions.record.type === "photo"
        Accessible.name: "Preview"
        onClicked: actions.vm.media.previewSource(actions.sourceId)
    }
    SplatButton {
        objectName: actions.namePrefix + "details-" + actions.sourceId
        iconName: "info"
        kind: "ghost"
        Accessible.name: "Details"
        onClicked: {
            actions.vm.media.focusSource(actions.sourceId);
            actions.detailsRequested();
        }
    }
    SplatButton {
        objectName: actions.namePrefix + "participation-" + actions.sourceId
        iconName: actions.record.isIncluded === false ? "refresh" : "exclude"
        kind: "ghost"
        enabled: actions.vm.state.canMutate && actions.vm.state.participationSupported
        Accessible.name: actions.record.isIncluded === false
                         ? "Restore to processing" : "Exclude from processing"
        Accessible.description: "Original file stays in place. Applies to the selection when this source is selected."
        onClicked: actions.vm.setSourceIncluded(actions.sourceId, actions.record.isIncluded === false)
    }
}

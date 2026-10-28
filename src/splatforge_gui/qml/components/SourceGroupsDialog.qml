pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../theme"

SplatDialog {
    id: dialog
    required property var vm
    property string mode: "manage"
    objectName: "sourceGroupsDialog"
    title: mode === "create" ? "Create Group" : mode === "move" ? "Move to Group" : "Source groups"
    height: Math.min(580, Overlay.overlay.height - 32)
    readonly property bool editable: vm.state.canMutate && vm.state.groupsSupported
    onOpened: {
        newName.text = "";
        manage.currentIndex = Math.max(0, manage.indexOfValue(vm.sources.selected.logicalGroupId || ""));
        rename.text = manage.currentIndex > 0 ? manage.currentText : "";
        destination.currentIndex = Math.max(0, destination.indexOfValue(vm.sources.selected.logicalGroupId || ""));
    }
    ColumnLayout {
        anchors.fill: parent
        ScrollView {
            id: scroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true
            ColumnLayout {
                width: scroll.availableWidth
                spacing: 12
                SplatLabel {
                    text: "Organize sources into collections for this project."
                    color: Theme.secondary
                    Layout.fillWidth: true
                }
                SplatLabel {
                    text: dialog.vm.sources.selectedCount + " sources will be added."
                    visible: dialog.mode === "create"
                }
                SplatLabel { text: "Create group"; font.weight: Font.DemiBold; visible: dialog.mode !== "move" }
                RowLayout {
                    visible: dialog.mode !== "move"
                    Layout.fillWidth: true
                    SplatTextField {
                        id: newName
                        objectName: "newSourceGroupName"
                        placeholderText: "For example, Exterior Drone"
                        maximumLength: 120
                        Layout.fillWidth: true
                        Accessible.name: "New group name"
                    }
                    SplatButton {
                        objectName: "createSourceGroup"
                        text: "Create Group"
                        enabled: dialog.editable && newName.text.trim().length > 0
                        onClicked: {
                            dialog.vm.createSourceGroup(newName.text); newName.text = "";
                            if (dialog.mode === "create") dialog.close();
                        }
                    }
                }
                SplatLabel { text: "Rename or delete a group"; font.weight: Font.DemiBold; visible: dialog.mode === "manage" }
                SplatComboBox {
                    id: manage
                    visible: dialog.mode === "manage"
                    objectName: "managedSourceGroup"
                    model: dialog.vm.state.logicalGroups
                    textRole: "label"
                    valueRole: "value"
                    Layout.fillWidth: true
                    onActivated: rename.text = currentIndex > 0 ? currentText : ""
                    Accessible.name: "Group to manage"
                }
                RowLayout {
                    Layout.fillWidth: true
                    SplatTextField {
                        id: rename
                        visible: dialog.mode === "manage"
                        objectName: "renameSourceGroupName"
                        maximumLength: 120
                        Layout.fillWidth: true
                        enabled: manage.currentIndex > 0
                        Accessible.name: "Group name"
                    }
                    SplatButton {
                        objectName: "renameSourceGroup"
                        visible: dialog.mode === "manage"
                        text: "Rename"
                        enabled: dialog.editable && manage.currentIndex > 0 && rename.text.trim().length > 0
                        onClicked: dialog.vm.renameSourceGroup(manage.currentValue, rename.text)
                    }
                    SplatButton {
                        objectName: "deleteSourceGroup"
                        visible: dialog.mode === "manage"
                        text: "Delete group"
                        enabled: dialog.editable && manage.currentIndex > 0
                        onClicked: dialog.vm.deleteSourceGroup(manage.currentValue)
                    }
                }
                SplatLabel {
                    text: "Deleting a group leaves its sources ungrouped. Originals stay in place."
                    visible: dialog.mode === "manage"
                    color: Theme.secondary
                    font.pixelSize: Theme.small
                    Layout.fillWidth: true
                }
                SplatLabel { text: "Move selected sources"; font.weight: Font.DemiBold; visible: dialog.mode !== "create" }
                SplatLabel {
                    objectName: "groupSelectedSource"
                    visible: dialog.mode !== "create"
                    text: dialog.vm.sources.selectedCount > 1 ? dialog.vm.sources.selectedCount + " selected sources"
                          : dialog.vm.sources.selected.filename || "Select sources in List or Grid first."
                    Layout.fillWidth: true
                    elide: Text.ElideMiddle
                    wrapMode: Text.NoWrap
                }
                RowLayout {
                    Layout.fillWidth: true
                    SplatComboBox {
                        id: destination
                        visible: dialog.mode !== "create"
                        objectName: "sourceGroupDestination"
                        model: dialog.vm.state.logicalGroups
                        textRole: "label"
                        valueRole: "value"
                        Layout.fillWidth: true
                        Accessible.name: "Destination group"
                    }
                    SplatButton {
                        objectName: "moveSourceToGroup"
                        visible: dialog.mode !== "create"
                        text: destination.currentValue === "" ? "Ungroup" : "Move to Group"
                        enabled: dialog.editable && (dialog.vm.sources.selectedCount > 0
                                 || dialog.vm.sources.selectedId !== "")
                                 && destination.currentIndex >= 0
                        onClicked: {
                            if (dialog.vm.sources.selectedCount > 1)
                                dialog.vm.assignSelectedGroup(destination.currentValue);
                            else dialog.vm.assignSourceGroup(dialog.vm.sources.selectedId, destination.currentValue);
                            if (dialog.mode === "move") dialog.close();
                        }
                    }
                }
            }
            ScrollBar.vertical.policy: ScrollBar.AsNeeded
        }
        SplatButton {
            text: "Close"
            objectName: "closeSourceGroups"
            Layout.alignment: Qt.AlignRight
            onClicked: dialog.close()
        }
    }
}

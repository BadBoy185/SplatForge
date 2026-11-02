pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../theme"
import "../components"

SplatDialog {
    id: dialog
    required property var vm
    property alias location: projectPath.text
    signal browse
    objectName: "createProjectDialog"
    title: "New project"
    width: Math.min(600, Overlay.overlay ? Overlay.overlay.width - 48 : 600)
    height: Math.min(implicitHeight, Overlay.overlay ? Overlay.overlay.height - 32 : 600)
    closePolicy: vm.state.entryPending ? Popup.NoAutoClose : Popup.CloseOnEscape
    readonly property var destination: vm.projectDestination(projectPath.text, projectName.text)
    property bool wasPending: false
    Connections {
        target: dialog.vm
        function onChanged() {
            if (dialog.visible && dialog.wasPending && !dialog.vm.state.entryPending
                    && dialog.vm.state.entryError !== "")
                projectPath.forceActiveFocus();
            dialog.wasPending = dialog.vm.state.entryPending;
        }
    }
    header: SplatLabel {
        text: dialog.title
        padding: 24
        bottomPadding: 12
        font.pixelSize: Theme.title
        font.weight: Font.DemiBold
    }
    function submit() {
        if (destination.valid && !vm.state.busy && !vm.state.entryPending)
            vm.createProject(projectPath.text, projectName.text);
    }
    onOpened: {
        vm.beginCreate();
        projectPath.text = vm.lastProjectParent();
        projectName.forceActiveFocus();
    }
    contentItem: ScrollView {
        id: scroll
        clip: true
        implicitHeight: form.implicitHeight
        contentWidth: availableWidth
        ColumnLayout {
            id: form
            width: scroll.availableWidth
            spacing: 8
            SplatLabel { text: "Project name" }
            SplatTextField {
                id: projectName
                objectName: "projectName"
                Layout.fillWidth: true
                placeholderText: "e.g. Courtyard study"
                Accessible.name: "Project name"
                enabled: !dialog.vm.state.entryPending
                onAccepted: dialog.submit()
                KeyNavigation.tab: projectPath
            }
            SplatLabel {
                objectName: "projectNameError"
                visible: projectName.text !== "" && text !== ""
                text: dialog.destination.field === "name" ? dialog.destination.error : ""
                color: Theme.danger
                Layout.fillWidth: true
            }
            SplatLabel {
                text: "Location"
                Layout.topMargin: 16
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                SplatTextField {
                    id: projectPath
                    objectName: "projectLocation"
                    Layout.fillWidth: true
                    placeholderText: "Choose a parent folder"
                    Accessible.name: "Location"
                    enabled: !dialog.vm.state.entryPending
                    onAccepted: dialog.submit()
                    KeyNavigation.tab: browseButton
                }
                SplatButton {
                    id: browseButton
                    objectName: "browseProjectLocation"
                    text: "Browse…"
                    enabled: !dialog.vm.state.entryPending
                    onClicked: dialog.browse()
                    KeyNavigation.tab: cancelButton
                }
            }
            SplatLabel {
                objectName: "projectLocationError"
                visible: text !== ""
                text: dialog.destination.field === "location" ? dialog.destination.error : ""
                color: Theme.danger
                Layout.fillWidth: true
            }
            Rectangle {
                Layout.fillWidth: true
                Layout.topMargin: 16
                Layout.bottomMargin: 12
                height: 1
                color: Theme.border
            }
            SplatLabel { text: "Project folder" }
            SplatLabel {
                objectName: "projectDestination"
                text: dialog.destination.path || "Choose a project name and location"
                font.family: Theme.mono
                font.pixelSize: Theme.small
                color: Theme.secondary
                Layout.fillWidth: true
                wrapMode: Text.Wrap
            }
            SplatLabel {
                objectName: "createProjectError"
                visible: text !== ""
                text: dialog.vm.state.entryError
                color: Theme.danger
                Layout.fillWidth: true
                Layout.topMargin: 8
                Accessible.role: Accessible.AlertMessage
            }
        }
    }
    footer: ColumnLayout {
        spacing: 16
        Rectangle {
            Layout.fillWidth: true
            Layout.leftMargin: 24
            Layout.rightMargin: 24
            height: 1
            color: Theme.border
        }
        SplatLabel {
            Layout.leftMargin: 24
            Layout.rightMargin: 24
            Layout.fillWidth: true
            text: "Original photos and videos stay in their current locations."
            color: Theme.secondary
            font.pixelSize: Theme.small
        }
        RowLayout {
            Layout.alignment: Qt.AlignRight
            Layout.rightMargin: 24
            Layout.bottomMargin: 24
            spacing: 12
            SplatButton {
                id: cancelButton
                text: "Cancel"
                objectName: "cancelCreateProject"
                enabled: !dialog.vm.state.entryPending
                onClicked: dialog.close()
                KeyNavigation.tab: createButton.enabled ? createButton : projectName
            }
            SplatButton {
                id: createButton
                text: dialog.vm.state.entryPending ? "Creating…" : "Create project"
                objectName: "confirmCreateProject"
                kind: "primary"
                enabled: dialog.destination.valid && !dialog.vm.state.busy && !dialog.vm.state.entryPending
                onClicked: dialog.submit()
                KeyNavigation.tab: projectName
            }
        }
    }
}

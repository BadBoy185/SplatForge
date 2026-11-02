pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../theme"
import "../components"

Item {
    id: page
    required property var vm
    property bool showEntryError: true
    signal newProject
    signal openProject
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 32
        spacing: 24
        SplatLabel {
            text: "Projects"
            font.pixelSize: Theme.title
            font.weight: Font.DemiBold
        }
        RowLayout {
            spacing: 12
            SplatButton {
                text: "New project"
                objectName: "newProject"
                iconName: "plus"
                kind: "primary"
                enabled: !page.vm.state.busy && !page.vm.state.entryPending
                onClicked: page.newProject()
            }
            SplatButton {
                text: "Open project…"
                objectName: "openExistingProject"
                iconName: "folder"
                enabled: !page.vm.state.busy && !page.vm.state.entryPending
                onClicked: page.openProject()
            }
            SplatLabel {
                visible: page.vm.state.busy
                text: page.vm.state.entryPending ? (page.vm.state.entryOperation === "create" ? "Creating project…" : "Opening project…") : "Finish or cancel active work before switching projects."
                color: Theme.secondary
                Layout.fillWidth: true
            }
        }
        Rectangle {
            visible: page.vm.state.hasProject
            Layout.fillWidth: true
            implicitHeight: 72
            color: Theme.surface
            RowLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 16
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    SplatLabel {
                        text: "Current session · " + (page.vm.state.project.name || "")
                        font.weight: Font.DemiBold
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                        wrapMode: Text.NoWrap
                    }
                    SplatLabel {
                        text: page.vm.state.dirty ? "Unsaved changes" : page.vm.state.project.path || ""
                        color: page.vm.state.dirty ? Theme.warning : Theme.secondary
                        font.pixelSize: Theme.small
                        Layout.fillWidth: true
                        elide: Text.ElideMiddle
                        wrapMode: Text.NoWrap
                    }
                }
                SplatButton {
                    visible: page.vm.state.dirty
                    text: "Save"
                    objectName: "saveCurrentProject"
                    enabled: page.vm.state.canMutate
                    onClicked: page.vm.save()
                }
                SplatButton {
                    objectName: "resumeCurrentProject"
                    text: page.vm.state.busy ? "Return to task" : "Return to project"
                    onClicked: page.vm.resumeProject()
                }
            }
        }
        SplatBanner {
            visible: page.vm.state.unresolved
            Layout.fillWidth: true
            text: "Interrupted work needs attention before processing can continue."
            action: "Review recovery"
            onActivated: page.vm.navigate(6)
        }
        SplatLabel {
            objectName: "projectEntryError"
            visible: page.showEntryError && text !== ""
            text: page.vm.state.entryError
            color: Theme.danger
            Layout.fillWidth: true
        }
        RecentProjects {
            vm: page.vm
            Layout.fillWidth: true
            Layout.fillHeight: true
        }
        SplatLabel {
            text: "Local projects · Files stay on this computer"
            font.pixelSize: Theme.small
            color: Theme.secondary
        }
    }
}

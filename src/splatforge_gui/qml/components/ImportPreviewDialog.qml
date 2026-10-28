pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../theme"

SplatDialog {
    id: dialog
    required property var vm
    property bool reviewing: false
    objectName: "importPreviewDialog"
    title: "Import Folder"
    height: Math.min(reviewing ? 650 : 560, Overlay.overlay.height - 48)
    onOpened: reviewing = false
    onClosed: vm.cancelFolder()
    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        SplatLabel {
            text: "Found"
            font.weight: Font.DemiBold
        }
        GridLayout {
            columns: 2
            Layout.fillWidth: true
            columnSpacing: 24
            rowSpacing: 8
            SplatLabel { text: "Photos"; Layout.fillWidth: true }
            SplatLabel { objectName: "scanPhotos"; text: dialog.vm.state.scan.photos }
            SplatLabel { text: "Videos" }
            SplatLabel { objectName: "scanVideos"; text: dialog.vm.state.scan.videos }
            SplatLabel { text: "Unsupported / ignored" }
            SplatLabel { objectName: "scanIgnored"; text: dialog.vm.state.folderIgnored }
            SplatLabel { text: "Folders scanned"; color: Theme.secondary }
            SplatLabel { text: dialog.vm.state.scan.directories; color: Theme.secondary }
        }
        SplatLabel {
            visible: dialog.vm.state.scan.limited
            text: "Folder scan stopped after reaching the safety limit. Only the discovered files are shown. Choose a smaller folder to find the rest."
            color: Theme.warning
            Layout.fillWidth: true
        }
        SplatLabel {
            objectName: "folderGroupsPreview"
            visible: dialog.vm.state.scan.groups.length > 0
            text: "Folders will become source groups:\n" + dialog.vm.state.scan.groups
                  .map(group => group.label + " · " + group.count).join("\n")
            color: Theme.secondary
            font.pixelSize: Theme.small
            Layout.fillWidth: true
            maximumLineCount: 5
            elide: Text.ElideRight
        }
        SplatLabel {
            visible: dialog.vm.state.scan.unreadable
            text: "Some files or folders could not be read. Review Files shows the paths and details."
            color: Theme.warning
            Layout.fillWidth: true
        }
        SplatLabel {
            visible: dialog.vm.state.scan.existing > 0
            text: dialog.vm.state.scan.existing + " paths are already in this project. Importing again adds separate source entries."
            color: Theme.secondary
            font.pixelSize: Theme.small
            Layout.fillWidth: true
        }
        SplatLabel {
            visible: dialog.vm.state.folderCount === 0
            text: "No supported photos or videos were found."
            Layout.fillWidth: true
        }
        SplatButton {
            objectName: "reviewScanFiles"
            text: dialog.reviewing ? "Hide Files" : "Review Files"
            kind: "ghost"
            onClicked: dialog.reviewing = !dialog.reviewing
        }
        ListView {
            id: files
            objectName: "scanFiles"
            visible: dialog.reviewing
            Layout.fillWidth: true
            Layout.fillHeight: true
            model: dialog.vm.scanFiles
            clip: true
            reuseItems: true
            delegate: SplatLabel {
                required property string display
                width: files.width - 16
                text: display
                font.pixelSize: Theme.small
                color: Theme.secondary
                wrapMode: Text.WrapAnywhere
                padding: 4
            }
            ScrollBar.vertical: ScrollBar {}
        }
        SplatLabel {
            visible: !dialog.reviewing
            text: "Photos and videos will be checked during import. Your original files stay in place."
            color: Theme.secondary
            font.pixelSize: Theme.small
            Layout.fillWidth: true
        }
        Item { visible: !dialog.reviewing; Layout.fillHeight: true }
        RowLayout {
            Layout.alignment: Qt.AlignRight
            SplatButton {
                objectName: "cancelFolderImport"
                text: "Cancel"
                onClicked: dialog.close()
            }
            SplatButton {
                objectName: "confirmFolderImport"
                text: "Import " + dialog.vm.state.folderCount + " files"
                kind: "primary"
                enabled: dialog.vm.state.folderCount > 0 && dialog.vm.state.canMutate
                onClicked: {
                    dialog.vm.confirmFolder();
                    dialog.close();
                }
            }
        }
    }
}

pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
import "../theme"

SplatDialog {
    id: dialog
    required property var vm
    readonly property var api: vm.folderRelink
    objectName: "folderRelinkDialog"
    title: "Locate source folder"
    width: Math.min(720, Overlay.overlay ? Overlay.overlay.width - 32 : 720)
    height: Math.min(620, Overlay.overlay ? Overlay.overlay.height - 32 : 620)
    padding: Theme.panelInset
    closePolicy: api.state.busy ? Popup.NoAutoClose : Popup.CloseOnEscape
    onClosed: api.dismiss()
    ColumnLayout {
        anchors.fill: parent
        spacing: 8
        SplatLabel {
            text: "Restore registered files in this folder and every subfolder. Relative paths and content must match; originals stay in place."
            Layout.fillWidth: true
            color: Theme.secondary
            font.pixelSize: Theme.small
        }
        SplatLabel { text: "Recorded source folder" }
        SplatTextField {
            objectName: "relinkOldFolder"
            Layout.fillWidth: true
            text: dialog.api.state.oldFolder
            enabled: !dialog.api.state.busy
            Accessible.name: "Recorded source folder"
            onTextEdited: dialog.api.setOldFolder(text)
        }
        SplatLabel { text: "Replacement folder" }
        RowLayout {
            Layout.fillWidth: true
            SplatTextField {
                objectName: "relinkNewFolder"
                Layout.fillWidth: true
                text: dialog.api.state.newFolder
                enabled: !dialog.api.state.busy
                Accessible.name: "Replacement folder"
                onTextEdited: dialog.api.setNewFolder(text)
            }
            SplatButton {
                objectName: "chooseRelinkFolder"
                text: "Choose…"
                enabled: !dialog.api.state.busy
                onClicked: replacement.open()
            }
        }
        SplatLabel {
            objectName: "relinkSummary"
            Layout.fillWidth: true
            text: dialog.api.state.status === "idle" ? "Choose folders, then check the complete mapping."
                : dialog.api.state.status === "ready" || dialog.api.state.status === "succeeded"
                    ? dialog.api.state.matched + " / " + dialog.api.state.total + " files matched"
                : dialog.api.state.status === "checking" ? "Checking source files…"
                : dialog.api.state.status === "applying" ? "Relinking source files…"
                : dialog.api.state.status === "cancelled" ? "Folder relink cancelled"
                : "Folder relink needs attention"
            font.weight: Font.DemiBold
        }
        ProgressBar {
            objectName: "relinkProgress"
            visible: dialog.api.state.busy
            Layout.fillWidth: true
            indeterminate: !dialog.api.state.progress.total
            from: 0
            to: Math.max(1, dialog.api.state.progress.total || 1)
            value: dialog.api.state.progress.completed || 0
        }
        SplatLabel {
            visible: dialog.api.state.busy && !!dialog.api.state.progress.filename
            text: dialog.api.state.progress.filename || ""
            elide: Text.ElideMiddle
            maximumLineCount: 1
            Layout.fillWidth: true
            font.pixelSize: Theme.small
            color: Theme.secondary
        }
        SplatLabel {
            objectName: "relinkMessage"
            Layout.fillWidth: true
            text: dialog.api.state.message
            color: dialog.api.state.status === "failed" ? Theme.warning : Theme.secondary
            font.pixelSize: Theme.small
        }
        ListView {
            id: rows
            objectName: "relinkRows"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 40
            model: dialog.api.rows
            clip: true
            reuseItems: true
            delegate: SplatLabel {
                required property string display
                width: rows.width - 16
                text: display
                padding: 4
                font.pixelSize: Theme.small
                wrapMode: Text.WrapAnywhere
            }
            ScrollBar.vertical: ScrollBar {}
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            SplatButton {
                objectName: "closeFolderRelink"
                text: "Close"
                enabled: !dialog.api.state.busy
                onClicked: dialog.close()
            }
            Item { Layout.fillWidth: true }
            SplatButton {
                objectName: "cancelFolderRelink"
                text: "Cancel"
                visible: dialog.api.state.busy
                onClicked: dialog.api.cancel()
            }
            SplatButton {
                objectName: "previewFolderRelink"
                text: dialog.api.state.status === "failed" || dialog.api.state.status === "cancelled" ? "Check again" : "Check folders"
                enabled: dialog.api.state.canPreview
                onClicked: dialog.api.preview()
            }
            SplatButton {
                objectName: "applyFolderRelink"
                text: "Relink"
                kind: "primary"
                enabled: dialog.api.state.canApply
                onClicked: dialog.api.apply()
            }
        }
    }
    FolderDialog {
        id: replacement
        objectName: "replacementFolderPicker"
        title: "Locate replacement source folder"
        onAccepted: dialog.api.setNewFolder(String(selectedFolder))
    }
    Connections {
        target: dialog.vm
        function onDialogRequested(name: string) {
            if (name === "folderRelink") dialog.open();
            if (name === "closeFolderRelink") dialog.close();
        }
    }
}

pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
import "theme"
import "components"
import "pages"
import "dialogs"

ApplicationWindow {
    id: window
    required property var vm
    width: 1440
    height: 900
    minimumWidth: 1024
    minimumHeight: 640
    visible: true
    title: "SplatForge" + (vm.state.hasProject ? " — " + vm.state.project.name : "")
    color: Theme.background
    palette.window: Theme.surface
    palette.windowText: Theme.text
    palette.light: Theme.hover
    palette.midlight: Theme.strong
    palette.dark: Theme.border
    font.family: Theme.font
    font.pixelSize: Theme.body
    property bool compact: width < 1380
    Component.onCompleted: Theme.choice = vm.state.theme
    onClosing: close => {
        close.accepted = vm.requestClose();
        if (close.accepted)
            vm.rememberGeometry({
                x: x,
                y: y,
                width: width,
                height: height
            });
    }
    Connections {
        target: window.vm
        function onChanged() {
            Theme.choice = window.vm.state.theme;
            if (window.vm.state.scan.scanning)
                scanProgress.open();
            else
                scanProgress.close();
        }
        function onCloseReady() {
            window.close();
        }
        function onDialogRequested(name: string) {
            if (name === "error")
                errorDialog.open();
            else if (name === "unsaved")
                unsavedDialog.open();
            else if (name === "activeClose")
                closeDialog.open();
            else if (name === "folder")
                folderConfirmation.open();
            else if (name === "closeFolder")
                folderConfirmation.close();
            else if (name === "exact")
                exactDialog.open();
            else if (name === "components")
                componentDialog.open();
            else if (name === "image")
                imageDialog.open();
            else if (name === "closeImage")
                imageDialog.close();
            else if (name === "cleanup")
                cleanupDialog.open();
            else if (name === "locateRecent")
                locateRecentDialog.open();
            else if (name === "confirmRecentLocation")
                confirmRecentDialog.open();
            else if (name === "projectReady")
                projectDialog.close();
        }
    }
    Shortcut {
        sequence: "Ctrl+N"
        enabled: !window.vm.state.busy && !window.vm.state.entryPending
        onActivated: projectDialog.open()
    }
    Shortcut {
        sequence: "Ctrl+O"
        enabled: !window.vm.state.busy && !window.vm.state.entryPending && !projectDialog.visible
        onActivated: {
            window.vm.navigate(0);
            openDialog.open();
        }
    }
    Shortcut {
        sequence: "Ctrl+S"
        onActivated: window.vm.save()
    }
    Shortcut {
        sequence: "F5"
        onActivated: window.vm.refresh()
    }
    Shortcut {
        sequence: "Ctrl+,"
        onActivated: settingsDialog.open()
    }
    DropArea {
        anchors.fill: parent
        enabled: !(window.vm.state.hasProject && window.vm.state.page === 1)
        onDropped: drop => {
            if (drop.hasUrls)
                window.vm.dropUrls(drop.urls.map(u => String(u)));
        }
    }
    RowLayout {
        anchors.fill: parent
        spacing: 0
        ColumnLayout {
            spacing: 0
            Layout.fillWidth: true
            Layout.fillHeight: true
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 50
                color: Theme.background
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    spacing: 12
                    SplatButton {
                        objectName: "nav-Projects"
                        text: "Projects"
                        iconName: "folder"
                        kind: "ghost"
                        visible: window.vm.state.page !== 0
                        onClicked: window.vm.navigate(0)
                    }
                    SplatLabel {
                        text: window.vm.state.page !== 0 && window.vm.state.hasProject ? window.vm.state.project.name : "SplatForge"
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                        wrapMode: Text.NoWrap
                        Layout.fillWidth: true
                        Layout.minimumWidth: 40
                        Layout.maximumWidth: 280
                        ToolTip.visible: projectHover.hovered
                        ToolTip.text: window.vm.state.hasProject ? window.vm.state.project.name + "\n" + window.vm.state.project.path : "SplatForge"
                        HoverHandler { id: projectHover }
                    }
                    SplatBadge {
                        visible: window.vm.state.dirty && window.vm.state.page !== 0
                        text: "Unsaved"
                        tone: Theme.warning
                    }
                    Item {
                        Layout.fillWidth: true
                    }
                    Repeater {
                        model: window.vm.state.hasProject && window.vm.state.page !== 0 ? [["Materials", 1], ["Reconstruction", 2], ["Splat", 4], ["Results", 5]] : []
                        delegate: SplatButton {
                            id: projectTab
                            required property var modelData
                            objectName: "nav-" + modelData[0]
                            text: modelData[0]
                            kind: "ghost"
                            palette.buttonText: window.vm.state.page === modelData[1] ? Theme.accent : Theme.secondary
                            Layout.fillHeight: true
                            background: Rectangle {
                                color: projectTab.hovered ? Theme.hover : "transparent"
                                border.width: projectTab.visualFocus ? 2 : 0
                                border.color: Theme.accent
                                Rectangle {
                                    anchors.bottom: parent.bottom
                                    width: parent.width
                                    height: 3
                                    visible: window.vm.state.page === projectTab.modelData[1]
                                    color: Theme.accent
                                }
                            }
                            onClicked: window.vm.navigate(modelData[1])
                        }
                    }
                    SplatButton {
                        text: "More"
                        objectName: "workspaceMore"
                        visible: window.vm.state.hasProject && window.vm.state.page !== 0
                        onClicked: workspaceMenu.popup()
                        Menu {
                            id: workspaceMenu
                            MenuItem {
                                text: "Dataset preparation / export"
                                onTriggered: window.vm.navigate(3)
                            }
                            MenuItem {
                                objectName: "nav-Diagnostics"
                                text: "History / diagnostics"
                                onTriggered: window.vm.navigate(6)
                            }
                            MenuItem {
                                text: window.vm.state.mode === "Guided" ? "Show advanced controls" : "Show guided controls"
                                onTriggered: window.vm.setMode(window.vm.state.mode === "Guided" ? "Advanced" : "Guided")
                            }
                            MenuItem {
                                text: "Settings"
                                onTriggered: settingsDialog.open()
                            }
                        }
                    }
                    Rectangle {
                        visible: window.vm.state.hasProject && window.vm.state.page !== 0
                        width: 1
                        height: 24
                        color: Theme.border
                    }
                    SplatButton {
                        visible: window.vm.state.hasProject && window.vm.state.page !== 0
                        iconName: "refresh"
                        kind: "ghost"
                        Accessible.name: "Refresh project (F5)"
                        onClicked: window.vm.refresh()
                    }
                    SplatButton {
                        visible: window.vm.state.dirty && window.vm.state.page !== 0
                        enabled: window.vm.state.canMutate
                        text: "Save"
                        iconName: "save"
                        onClicked: window.vm.save()
                    }
                    SplatButton {
                        iconName: "settings"
                        kind: "ghost"
                        Accessible.name: "Application settings"
                        onClicked: settingsDialog.open()
                    }
                }
                Rectangle {
                    anchors.bottom: parent.bottom
                    width: parent.width
                    height: 1
                    color: Theme.border
                    opacity: 0.5
                }
            }
            Item {
                id: pageHost
                objectName: "workspaceHost"
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                Repeater {
                    id: pageLoaders
                    model: 7
                    delegate: Loader {
                        required property int index
                        property bool visited: false
                        readonly property bool current: window.vm.state.page === index
                        anchors.fill: parent
                        active: visited || current
                        visible: current
                        onCurrentChanged: {
                            if (current)
                                visited = true;
                        }
                        Component.onCompleted: {
                            if (current)
                                visited = true;
                        }
                        sourceComponent: [homePage, sourcesPage, reconstructPage, datasetPage, trainPage, resultsPage, diagnosticsPage][index]
                    }
                }
            }
            Rectangle {
                visible: window.vm.state.progress.visible
                Layout.fillWidth: true
                Layout.preferredHeight: visible ? (window.vm.state.progress.metrics.length > 0 ? 136 : 108) : 0
                color: Theme.surface
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 20
                    spacing: 10
                    RowLayout {
                        SplatLabel {
                            text: window.vm.state.progress.cancelling ? "Cancelling…" : window.vm.state.progress.title
                            font.weight: Font.DemiBold
                        }
                        SplatLabel {
                            text: window.vm.state.progress.phase
                            color: Theme.secondary
                            Layout.fillWidth: true
                        }
                        SplatLabel {
                            text: window.vm.state.progress.elapsed ? "Elapsed " + window.vm.state.progress.elapsed : ""
                            color: Theme.secondary
                            font.pixelSize: Theme.small
                        }
                        SplatLabel {
                            text: window.vm.state.progress.eta ? window.vm.state.progress.eta : ""
                            color: Theme.secondary
                            font.pixelSize: Theme.small
                        }
                        SplatButton {
                            text: window.vm.state.progress.cancelling ? "Cancelling…" : "Cancel"
                            objectName: "cancelOperation"
                            kind: "danger"
                            enabled: window.vm.state.progress.canCancel && !window.vm.state.progress.cancelling
                            onClicked: window.vm.cancel()
                        }
                    }
                    SplatProgress {
                        Layout.fillWidth: true
                        value: Math.max(0, window.vm.state.progress.fraction)
                        indeterminate: window.vm.state.progress.fraction < 0
                    }
                    SplatLabel {
                        text: window.vm.state.progress.work + (window.vm.state.progress.percent ? " · " + window.vm.state.progress.percent : "")
                        font.pixelSize: Theme.small
                        color: Theme.secondary
                    }
                    RowLayout {
                        visible: window.vm.state.progress.metrics.length > 0
                        spacing: 20
                        Repeater {
                            model: window.vm.state.progress.metrics.slice(0, 5)
                            delegate: SplatLabel {
                                required property var modelData
                                text: modelData.name + "  " + modelData.value
                                color: Theme.secondary
                                font.pixelSize: Theme.small
                            }
                        }
                    }
                }
            }
        }
    }
    Component {
        id: homePage
        HomePage {
            vm: window.vm
            showEntryError: !projectDialog.visible
            onNewProject: projectDialog.open()
            onOpenProject: openDialog.open()
        }
    }
    Component {
        id: sourcesPage
        SourcesPage {
            vm: window.vm
            viewportHeight: pageHost.height
        }
    }
    Component {
        id: reconstructPage
        WorkspacePanel {
            contentComponent: Component {
                ReconstructPage {
                    vm: window.vm
                }
            }
        }
    }
    Component {
        id: datasetPage
        WorkspacePanel {
            contentComponent: Component {
                DatasetPage {
                    vm: window.vm
                }
            }
        }
    }
    Component {
        id: trainPage
        WorkspacePanel {
            contentComponent: Component {
                TrainPage {
                    vm: window.vm
                }
            }
        }
    }
    Component {
        id: resultsPage
        WorkspacePanel {
            contentComponent: Component {
                ResultsPage {
                    vm: window.vm
                }
            }
        }
    }
    Component {
        id: diagnosticsPage
        WorkspacePanel {
            contentComponent: Component {
                DiagnosticsPage {
                    vm: window.vm
                }
            }
        }
    }
    CleanupDialog {
        id: cleanupDialog
        inspection: window.vm.inspection
    }
    ExactSettingsDialog {
        id: exactDialog
        objectName: "exactDialog"
        editor: window.vm.exact
    }
    ComponentSelectionDialog {
        id: componentDialog
        objectName: "componentDialog"
        selection: window.vm.components
    }
    SourcePreviewDialog {
        id: imageDialog
        media: window.vm.media
    }
    FolderDialog {
        id: openDialog
        title: "Open SplatForge project"
        onAccepted: window.vm.openProject(String(selectedFolder))
    }
    FolderDialog {
        id: directoryDialog
        title: "Choose a parent location"
        onAccepted: projectDialog.location = window.vm.localPath(String(selectedFolder))
    }
    FolderDialog {
        id: locateRecentDialog
        title: "Locate SplatForge project"
        onAccepted: window.vm.locateRecent(window.vm.state.locateRecentPath, String(selectedFolder))
    }
    SplatDialog {
        id: confirmRecentDialog
        objectName: "confirmRecentLocation"
        title: "Confirm project location"
        ColumnLayout {
            width: parent.width
            spacing: 16
            SplatLabel {
                text: "This older recent entry has no saved project identity. Use the selected project?"
                Layout.fillWidth: true
            }
            SplatLabel {
                text: (window.vm.state.recentCandidate.name || "") + "\n" + (window.vm.state.recentCandidate.path || "")
                Layout.fillWidth: true
                wrapMode: Text.WrapAnywhere
            }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                SplatButton {
                    text: "Cancel"
                    onClicked: confirmRecentDialog.close()
                }
                SplatButton {
                    text: "Use this project"
                    onClicked: {
                        window.vm.confirmRecentLocation();
                        confirmRecentDialog.close();
                    }
                }
            }
        }
    }
    CreateProjectDialog {
        id: projectDialog
        vm: window.vm
        onBrowse: directoryDialog.open()
    }
    SplatDialog {
        id: settingsDialog
        objectName: "settingsDialog"
        title: "Application settings"
        onClosed: {
            if (window.vm.state.page === 1) {
                const materials = pageLoaders.itemAt(1) as Loader;
                const workspace = materials ? materials.item as Item : null;
                if (workspace)
                    workspace.forceActiveFocus();
            }
        }
        ColumnLayout {
            width: parent.width
            spacing: 16
            SplatLabel {
                text: "Appearance"
                font.weight: Font.DemiBold
            }
            SplatComboBox {
                model: ["System", "Dark", "Light"]
                currentIndex: model.indexOf(window.vm.state.theme)
                onActivated: window.vm.setTheme(currentText)
                Layout.fillWidth: true
                Accessible.name: "Theme"
            }
            SplatLabel {
                text: "Machine paths"
                font.weight: Font.DemiBold
                topPadding: 8
            }
            SplatLabel {
                text: "Optional local tools. Changing a path requires a new capability check. No numerical project settings are stored here."
                color: Theme.secondary
                Layout.fillWidth: true
            }
            Repeater {
                model: [["colmap", "COLMAP executable"], ["model_directory", "Learned-model directory"], ["trainer_python", "Trainer Python"], ["lichtfeld", "LichtFeld executable"]]
                delegate: ColumnLayout {
                    id: field
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 6
                    SplatLabel {
                        text: field.modelData[1]
                        font.pixelSize: Theme.small
                    }
                    SplatTextField {
                        text: window.vm.state.machine[field.modelData[0]]
                        placeholderText: "Not configured"
                        Layout.fillWidth: true
                        Accessible.name: field.modelData[1]
                        onEditingFinished: window.vm.setMachine(field.modelData[0], text)
                    }
                }
            }
            SplatButton {
                text: "Done"
                kind: "primary"
                Layout.alignment: Qt.AlignRight
                onClicked: settingsDialog.close()
            }
        }
    }
    SplatDialog {
        id: errorDialog
        objectName: "errorDialog"
        title: "Operation could not complete"
        ColumnLayout {
            width: parent.width
            spacing: 16
            SplatLabel {
                text: window.vm.state.error.message || ""
                Layout.fillWidth: true
            }
            SplatLabel {
                text: (window.vm.state.error.stage || "") + " · " + (window.vm.state.error.category || "")
                color: Theme.muted
                Layout.fillWidth: true
            }
            SplatButton {
                text: "Copy technical details"
                onClicked: window.vm.copyText(window.vm.state.error.details || "")
            }
            DetailsPanel {
                Layout.fillWidth: true
                title: "Technical details"
                text: window.vm.state.error.details || ""
            }
            SplatButton {
                text: "Close"
                kind: "primary"
                Layout.alignment: Qt.AlignRight
                onClicked: errorDialog.close()
            }
        }
    }
    SplatDialog {
        id: unsavedDialog
        objectName: "unsavedDialog"
        onRejected: window.vm.resolveUnsaved("cancel")
        title: "Save project intent?"
        ColumnLayout {
            width: parent.width
            spacing: 16
            SplatLabel {
                text: "Your project has unsaved changes."
            }
            RowLayout {
                SplatButton {
                    objectName: "cancelUnsaved"
                    text: "Cancel"
                    onClicked: {
                        window.vm.resolveUnsaved("cancel");
                        unsavedDialog.close();
                    }
                }
                SplatButton {
                    objectName: "discardUnsaved"
                    text: "Discard changes"
                    onClicked: {
                        window.vm.resolveUnsaved("discard");
                        unsavedDialog.close();
                    }
                }
                SplatButton {
                    objectName: "saveUnsaved"
                    text: "Save"
                    kind: "primary"
                    onClicked: {
                        window.vm.resolveUnsaved("save");
                        unsavedDialog.close();
                    }
                }
            }
        }
    }
    SplatDialog {
        id: closeDialog
        title: "An operation is still active"
        ColumnLayout {
            width: parent.width
            spacing: 16
            SplatLabel {
                text: window.vm.state.progress.canCancel ? "This window owns orchestration. Closing waits for confirmed cancellation and backend teardown." : "This operation must finish before closing. It has no mid-call cancellation contract."
                Layout.fillWidth: true
            }
            RowLayout {
                SplatButton {
                    text: "Return"
                    onClicked: closeDialog.close()
                }
                SplatButton {
                    text: "Cancel run and close"
                    kind: "danger"
                    visible: window.vm.state.progress.canCancel
                    onClicked: {
                        window.vm.cancelAndClose();
                        closeDialog.close();
                    }
                }
            }
        }
    }
    ImportPreviewDialog {
        id: folderConfirmation
        vm: window.vm
    }
    SplatDialog {
        id: scanProgress
        objectName: "folderScanProgress"
        title: "Scanning source folders…"
        onRejected: window.vm.cancel()
        ColumnLayout {
            width: parent.width
            spacing: 16
            BusyIndicator {
                running: window.vm.state.scan.scanning
            }
            SplatLabel {
                text: window.vm.state.scan.progress.entries + " entries · " + window.vm.state.scan.progress.directories + " folders scanned"
                Layout.fillWidth: true
            }
            SplatLabel {
                text: "Looking for supported photos and videos. Your project has not changed."
                color: Theme.secondary
                Layout.fillWidth: true
            }
            SplatButton {
                objectName: "cancelFolderScan"
                text: "Cancel"
                enabled: !window.vm.state.progress.cancelling
                onClicked: window.vm.cancel()
            }
        }
    }
}

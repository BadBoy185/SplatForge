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
        }
    }
    Shortcut {
        sequence: "Ctrl+N"
        onActivated: projectDialog.open()
    }
    Shortcut {
        sequence: "Ctrl+O"
        onActivated: openDialog.open()
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
        onDropped: drop => {
            if (drop.hasUrls)
                window.vm.dropUrls(drop.urls.map(u => String(u)));
        }
    }
    RowLayout {
        anchors.fill: parent
        spacing: 0
        Rectangle {
            visible: window.vm.state.hasProject
            Layout.fillHeight: true
            Layout.preferredWidth: window.compact ? 76 : 214
            color: Theme.sidebar
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 4
                RowLayout {
                    Layout.preferredHeight: 64
                    spacing: 10
                    Image {
                        source: "icons/brand.svg"
                        Layout.preferredWidth: 30
                        Layout.preferredHeight: 30
                    }
                    SplatLabel {
                        visible: !window.compact
                        text: "SplatForge"
                        font.pixelSize: 20
                        font.weight: Font.DemiBold
                        font.letterSpacing: -0.5
                    }
                }
                Repeater {
                    model: [["Home", "home", "WORKSPACE"], ["Sources", "sources", "PROJECT"],
                        ["Reconstruct", "reconstruct", ""], ["Dataset", "dataset", ""], ["Train",
                                                                                         "train", ""],
                        ["Results", "results", "OUTPUT"], ["Diagnostics", "diagnostics", "SYSTEM"]]
                    delegate: ColumnLayout {
                        id: nav
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        spacing: 4
                        SplatLabel {
                            visible: nav.modelData[2] !== ""
                            text: window.compact ? "" : nav.modelData[2]
                            topPadding: 20
                            bottomPadding: 8
                            leftPadding: 10
                            font.pixelSize: 10
                            font.letterSpacing: 1.5
                            color: Theme.muted
                        }
                        SplatNavItem {
                            Layout.fillWidth: true
                            text: nav.index === 0 ? "Overview" : nav.modelData[0]
                            objectName: "nav-" + nav.modelData[0]
                            iconName: nav.modelData[1]
                            compact: window.compact
                            checked: window.vm.state.page === nav.index
                            onClicked: window.vm.navigate(nav.index)
                        }
                    }
                }
                Item {
                    Layout.fillHeight: true
                }
                SplatNavItem {
                    text: "Settings"
                    iconName: "settings"
                    compact: window.compact
                    Layout.fillWidth: true
                    onClicked: settingsDialog.open()
                }
                SplatLabel {
                    visible: !window.compact
                    text: "LOCAL BY DESIGN"
                    color: Theme.muted
                    font.pixelSize: 10
                    font.letterSpacing: 1.5
                    leftPadding: 10
                    topPadding: 16
                    bottomPadding: 8
                }
            }
        }
        ColumnLayout {
            spacing: 0
            Layout.fillWidth: true
            Layout.fillHeight: true
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 64
                color: Theme.background
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 32
                    anchors.rightMargin: 32
                    spacing: 12
                    SplatLabel {
                        text: window.vm.state.hasProject ? window.vm.state.project.name :
                                                           "SplatForge"
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                        wrapMode: Text.NoWrap
                        Layout.maximumWidth: 320
                    }
                    SplatBadge {
                        visible: window.vm.state.dirty
                        text: "Unsaved"
                        tone: Theme.warning
                    }
                    Item {
                        Layout.fillWidth: true
                    }
                    RowLayout {
                        visible: window.vm.state.hasProject
                        spacing: 2
                        SplatButton {
                            text: "Guided"
                            kind: window.vm.state.mode === "Guided" ? "secondary" : "ghost"
                            onClicked: window.vm.setMode("Guided")
                        }
                        SplatButton {
                            text: "Advanced"
                            kind: window.vm.state.mode === "Advanced" ? "secondary" : "ghost"
                            onClicked: window.vm.setMode("Advanced")
                        }
                    }
                    Rectangle {
                        visible: window.vm.state.hasProject
                        width: 1
                        height: 24
                        color: Theme.border
                    }
                    SplatButton {
                        visible: window.vm.state.hasProject
                        iconName: "refresh"
                        kind: "ghost"
                        Accessible.name: "Refresh project (F5)"
                        onClicked: window.vm.refresh()
                    }
                    SplatButton {
                        visible: window.vm.state.dirty
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
            ScrollView {
                id: scroll
                objectName: "pageScroll"
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                contentWidth: availableWidth
                ColumnLayout {
                    width: scroll.availableWidth - 64
                    x: 32
                    spacing: 24
                    Item {
                        Layout.preferredHeight: 8
                    }
                    Item {
                        id: pageHost
                        Layout.fillWidth: true
                        implicitHeight: {
                            const current = pageLoaders.itemAt(window.vm.state.page);
                            return current ? current.implicitHeight : 0;
                        }
                        Repeater {
                            id: pageLoaders
                            model: 7
                            delegate: Loader {
                                required property int index
                                property bool visited: false
                                readonly property bool current: window.vm.state.page === index
                                width: pageHost.width
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
                                sourceComponent: [homePage, sourcesPage, reconstructPage,
                                    datasetPage, trainPage, resultsPage, diagnosticsPage][index]
                            }
                        }
                    }
                    Item {
                        Layout.preferredHeight: 8
                    }
                }
            }
            Rectangle {
                visible: window.vm.state.progress.visible
                Layout.fillWidth: true
                Layout.preferredHeight: visible ? (window.vm.state.progress.metrics.length > 0 ? 136 :
                                                                                                 108) : 0
                color: Theme.surface
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 20
                    spacing: 10
                    RowLayout {
                        SplatLabel {
                            text: window.vm.state.progress.cancelling ? "Cancelling…" :
                                                                        window.vm.state.progress.title
                            font.weight: Font.DemiBold
                        }
                        SplatLabel {
                            text: window.vm.state.progress.phase
                            color: Theme.secondary
                            Layout.fillWidth: true
                        }
                        SplatLabel {
                            text: window.vm.state.progress.elapsed ? "Elapsed "
                                                                     + window.vm.state.progress.elapsed :
                                                                     ""
                            color: Theme.secondary
                            font.pixelSize: Theme.small
                        }
                        SplatLabel {
                            text: window.vm.state.progress.eta ? window.vm.state.progress.eta :
                                                                 ""
                            color: Theme.secondary
                            font.pixelSize: Theme.small
                        }
                        SplatButton {
                            text: window.vm.state.progress.cancelling ? "Cancelling…" : "Cancel"
                            objectName: "cancelOperation"
                            kind: "danger"
                            enabled: window.vm.state.progress.canCancel &&
                                     !window.vm.state.progress.cancelling
                            onClicked: window.vm.cancel()
                        }
                    }
                    SplatProgress {
                        Layout.fillWidth: true
                        value: Math.max(0, window.vm.state.progress.fraction)
                        indeterminate: window.vm.state.progress.fraction < 0
                    }
                    SplatLabel {
                        text: window.vm.state.progress.work
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
            onNewProject: projectDialog.open()
            onOpenProject: openDialog.open()
        }
    }
    Component {
        id: sourcesPage
        SourcesPage {
            vm: window.vm
            viewportHeight: scroll.availableHeight - 64
        }
    }
    Component {
        id: reconstructPage
        ReconstructPage {
            vm: window.vm
        }
    }
    Component {
        id: datasetPage
        DatasetPage {
            vm: window.vm
        }
    }
    Component {
        id: trainPage
        TrainPage {
            vm: window.vm
        }
    }
    Component {
        id: resultsPage
        ResultsPage {
            vm: window.vm
        }
    }
    Component {
        id: diagnosticsPage
        DiagnosticsPage {
            vm: window.vm
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
        onAccepted: projectPath.text = window.vm.localPath(String(selectedFolder))
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
                text: (window.vm.state.recentCandidate.name || "") + "\n"
                      + (window.vm.state.recentCandidate.path || "")
                Layout.fillWidth: true
                wrapMode: Text.WrapAnywhere
            }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                SplatButton { text: "Cancel"; onClicked: confirmRecentDialog.close() }
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
    SplatDialog {
        id: projectDialog
        objectName: "createProjectDialog"
        title: "Create New Project"
        readonly property var destination: window.vm.projectDestination(projectPath.text,
                                                                        projectName.text)
        onOpened: {
            projectPath.text = window.vm.lastProjectParent();
            projectName.forceActiveFocus();
        }
        ColumnLayout {
            width: parent.width
            spacing: 16
            SplatLabel {
                text: "Choose a name and parent location for your project. Your original media will remain in place."
                color: Theme.secondary
                Layout.fillWidth: true
            }
            SplatLabel {
                text: "Project name"
                font.pixelSize: Theme.small
            }
            SplatTextField {
                id: projectName
                objectName: "projectName"
                Layout.fillWidth: true
                placeholderText: "e.g. Courtyard study"
                Accessible.name: "Project name"
            }
            SplatLabel {
                text: "Location"
                font.pixelSize: Theme.small
            }
            RowLayout {
                SplatTextField {
                    id: projectPath
                    objectName: "projectLocation"
                    Layout.fillWidth: true
                    placeholderText: "Choose a parent folder"
                    Accessible.name: "Location"
                }
                SplatButton {
                    text: "Browse..."
                    onClicked: directoryDialog.open()
                }
            }
            SplatLabel {
                text: "Project will be created at:"
                font.pixelSize: Theme.small
            }
            SplatLabel {
                objectName: "projectDestination"
                text: projectDialog.destination.path || "Choose a project name and location"
                font.family: Theme.mono
                color: Theme.secondary
                Layout.fillWidth: true
                wrapMode: Text.WrapAnywhere
            }
            SplatLabel {
                objectName: "projectNameError"
                visible: (projectName.text !== "" || projectPath.text !== "") && text !== ""
                text: projectDialog.destination.error
                color: Theme.danger
                Layout.fillWidth: true
            }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                SplatButton {
                    text: "Cancel"
                    objectName: "cancelCreateProject"
                    kind: "ghost"
                    onClicked: projectDialog.close()
                }
                SplatButton {
                    text: "Create Project"
                    objectName: "confirmCreateProject"
                    kind: "primary"
                    enabled: projectDialog.destination.valid && !window.vm.state.busy
                    onClicked: {
                        window.vm.createProject(projectPath.text, projectName.text);
                        projectDialog.close();
                    }
                }
            }
        }
    }
    SplatDialog {
        id: settingsDialog
        objectName: "settingsDialog"
        title: "Application settings"
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
                model: [["colmap", "COLMAP executable"], ["model_directory",
                                                          "Learned-model directory"],
                    ["trainer_python", "Trainer Python"], ["lichtfeld", "LichtFeld executable"]]
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
                text: (window.vm.state.error.stage || "") + " · " + (window.vm.state.error.category
                                                                     || "")
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
        title: "Save project intent?"
        ColumnLayout {
            width: parent.width
            spacing: 16
            SplatLabel {
                text: "Your project has unsaved changes."
            }
            RowLayout {
                SplatButton {
                    text: "Cancel"
                    onClicked: {
                        window.vm.resolveUnsaved("cancel");
                        unsavedDialog.close();
                    }
                }
                SplatButton {
                    text: "Discard changes"
                    onClicked: {
                        window.vm.resolveUnsaved("discard");
                        unsavedDialog.close();
                    }
                }
                SplatButton {
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
                text: window.vm.state.progress.canCancel
                      ? "This window owns orchestration. Closing waits for confirmed cancellation and backend teardown." :
                        "This operation must finish before closing. It has no mid-call cancellation contract."
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
            BusyIndicator { running: window.vm.state.scan.scanning }
            SplatLabel {
                text: window.vm.state.scan.progress.entries + " entries · "
                      + window.vm.state.scan.progress.directories + " folders scanned"
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

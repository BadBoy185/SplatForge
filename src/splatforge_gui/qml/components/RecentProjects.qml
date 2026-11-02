pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../theme"

ColumnLayout {
    id: recentsSection
    required property var vm
    spacing: 12
    SplatLabel {
        text: "Recent projects"
        color: Theme.secondary
    }
    SplatLabel {
        visible: recentsSection.vm.state.recentsLoading || recentsSection.vm.state.recents.length === 0
        text: recentsSection.vm.state.recentsLoading ? "Loading recent projects…" : "No recent projects. Create a project or open an existing one."
        color: Theme.secondary
        Layout.fillWidth: true
    }
    ListView {
        id: list
        objectName: "recentProjects"
        Layout.fillWidth: true
        Layout.fillHeight: true
        model: recentsSection.vm.state.recents
        clip: true
        keyNavigationEnabled: true
        activeFocusOnTab: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}
        function openSelected() {
            if (currentIndex < 0 || currentIndex >= model.length) return;
            const entry = model[currentIndex];
            if (entry.available) recentsSection.vm.openProject(entry.path);
            else recentsSection.vm.beginLocateRecent(entry.path);
        }
        Keys.onReturnPressed: openSelected()
        Keys.onEnterPressed: openSelected()
        delegate: Rectangle {
            id: recent
            required property var modelData
            required property int index
            readonly property bool selected: ListView.isCurrentItem
            readonly property bool currentSession: modelData.available && recentsSection.vm.state.hasProject
                && recentsSection.vm.state.project.id === modelData.projectId
                && recentsSection.vm.isCurrentProject(modelData.path)
            function open() {
                if (modelData.available && (!recentsSection.vm.state.busy || currentSession))
                    recentsSection.vm.openProject(modelData.path);
                else if (!modelData.available)
                    recentsSection.vm.beginLocateRecent(modelData.path);
            }
            width: list.width
            height: 72
            color: selected ? Theme.selection : rowMouse.containsMouse ? Theme.hover : "transparent"
            border.width: selected && list.activeFocus ? 2 : 0
            border.color: Theme.accent
            Accessible.role: Accessible.ListItem
            Accessible.name: modelData.name + ", " + modelData.path + ", " + modelData.summary
            MouseArea {
                id: rowMouse
                anchors.fill: parent
                hoverEnabled: true
                onClicked: {
                    list.currentIndex = recent.index;
                    list.forceActiveFocus();
                }
                onDoubleClicked: recent.open()
            }
            Rectangle {
                width: 3
                height: parent.height
                visible: recent.selected
                color: Theme.accent
            }
            Rectangle {
                anchors.bottom: parent.bottom
                width: parent.width
                height: 1
                color: Theme.border
            }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 16
                anchors.rightMargin: 12
                spacing: 16
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    SplatLabel {
                        text: recent.modelData.name
                        font.weight: Font.DemiBold
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                        wrapMode: Text.NoWrap
                    }
                    SplatLabel {
                        text: recent.modelData.path
                        color: Theme.secondary
                        Layout.fillWidth: true
                        elide: Text.ElideMiddle
                        wrapMode: Text.NoWrap
                        font.pixelSize: Theme.small
                    }
                }
                SplatLabel {
                    text: recent.currentSession ? "Current session" : recent.modelData.available ? "" : recent.modelData.summary
                    color: recent.modelData.available ? Theme.secondary : Theme.warning
                    Layout.maximumWidth: 185
                    font.pixelSize: Theme.small
                }
                SplatLabel {
                    visible: list.width > 1100
                    text: recent.modelData.lastOpenedLabel
                    color: Theme.secondary
                    font.pixelSize: Theme.small
                    Layout.preferredWidth: 230
                }
                SplatButton {
                    text: recent.modelData.available ? "Open" : "Locate…"
                    objectName: recent.modelData.available ? "openRecentProject" : "locateRecentProject"
                    kind: "ghost"
                    enabled: !recentsSection.vm.state.entryPending && (!recent.modelData.available || !recentsSection.vm.state.busy || recent.currentSession)
                    onClicked: recent.open()
                }
                SplatButton {
                    id: recentMenuButton
                    text: "···"
                    objectName: "recentProjectMenu"
                    kind: "ghost"
                    Accessible.name: "Actions for " + recent.modelData.name
                    onClicked: actions.open()
                    Menu {
                        id: actions
                        objectName: "recentProjectActions"
                        parent: recentMenuButton
                        x: recentMenuButton.width - width
                        y: recentMenuButton.height
                        palette.window: Theme.surface
                        palette.text: Theme.text
                        palette.windowText: Theme.text
                        palette.light: Theme.hover
                        palette.midlight: Theme.strong
                        palette.dark: Theme.border
                        palette.buttonText: Theme.text
                        palette.highlight: Theme.selection
                        palette.highlightedText: Theme.text
                        MenuItem {
                            text: "Copy full path"
                            onTriggered: recentsSection.vm.copyText(recent.modelData.path)
                        }
                        MenuItem {
                            text: "Locate…"
                            onTriggered: recentsSection.vm.beginLocateRecent(recent.modelData.path)
                        }
                        MenuItem {
                            text: "Remove from list"
                            objectName: "removeRecentProject"
                            onTriggered: recentsSection.vm.removeRecent(recent.modelData.path)
                        }
                    }
                }
            }
            ToolTip.visible: rowMouse.containsMouse || (recent.selected && list.activeFocus)
            ToolTip.delay: 800
            ToolTip.text: modelData.name + "\n" + modelData.path
                + (modelData.details ? "\n" + modelData.details : "")
        }
    }
}

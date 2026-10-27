pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../theme"

ColumnLayout {
    id: recentsSection
    required property var vm
    spacing: 12
    SplatLabel {
        text: "Recent Projects"
        font.pixelSize: Theme.section
        font.weight: Font.DemiBold
    }
    SplatLabel {
        visible: recentsSection.vm.state.recents.length === 0
        text: "Projects you create or open will appear here."
        color: Theme.secondary
    }
    ListView {
        objectName: "recentProjects"
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(contentHeight, 300)
        model: recentsSection.vm.state.recents
        spacing: 8
        clip: true
        delegate: SplatCard {
            id: recent
            required property var modelData
            width: ListView.view.width
            height: 108
            padding: 14
            RowLayout {
                anchors.fill: parent
                spacing: 12
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
                    SplatLabel {
                        text: recent.modelData.available ? recent.modelData.lastOpenedLabel
                                                         : "⚠ " + recent.modelData.summary
                        color: recent.modelData.available ? Theme.muted : Theme.warning
                        font.pixelSize: Theme.small
                    }
                }
                SplatButton {
                    text: "Remove from list"
                    kind: "ghost"
                    objectName: "removeRecentProject"
                    onClicked: recentsSection.vm.removeRecent(recent.modelData.path)
                }
                SplatButton {
                    text: recent.modelData.available ? "Open" : "Locate…"
                    objectName: recent.modelData.available ? "openRecentProject" : "locateRecentProject"
                    enabled: !recentsSection.vm.state.busy
                    onClicked: {
                        if (recent.modelData.available)
                            recentsSection.vm.openProject(recent.modelData.path);
                        else
                            recentsSection.vm.beginLocateRecent(recent.modelData.path);
                    }
                }
            }
        }
    }
}

pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
import "../theme"
import "../components"

ColumnLayout {
    id: page
    objectName: "sourcesPage"
    required property var vm
    property real viewportHeight: 512
    readonly property real listHeight: Math.max(112, viewportHeight - header.implicitHeight
                                                - check.implicitHeight - footer.implicitHeight - 48)
    spacing: 16
    SplatPageHeader {
        id: header
        title: "Sources"
        subtitle: page.vm.sources.count > 0
                  ? page.vm.state.sourcesSummary.photos
                    + (page.vm.state.sourcesSummary.photos === 1 ? " photo · " : " photos · ")
                    + page.vm.state.sourcesSummary.videos
                    + (page.vm.state.sourcesSummary.videos === 1 ? " video" : " videos")
                  : "Add the photos and videos you want to use."
        Layout.fillWidth: true
        SplatButton {
            objectName: "addPhotos"
            text: "Add Photos"
            iconName: "plus"
            kind: "primary"
            enabled: page.vm.state.canMutate
            onClicked: photos.open()
        }
        SplatButton {
            objectName: "addVideo"
            text: "Add Video"
            iconName: "plus"
            enabled: page.vm.state.canMutate
            onClicked: videos.open()
        }
        SplatButton {
            text: "Add Folder"
            iconName: "folder"
            enabled: page.vm.state.canMutate
            onClicked: folders.open()
            Accessible.description: "Add supported files from the top level of a folder"
        }
    }
    SplatCard {
        id: check
        Layout.fillWidth: true
        padding: 16
        implicitHeight: checkContent.implicitHeight + padding * 2
        RowLayout {
            id: checkContent
            width: parent.width
            spacing: 16
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 6
                SplatLabel {
                    objectName: "sourceCheckSummary"
                    text: page.vm.state.sourcesSummary.checkMessage
                    font.weight: Font.DemiBold
                    Layout.fillWidth: true
                }
                SplatLabel {
                    text: "Source files stay in their original locations. Check that SplatForge can still access them."
                    color: Theme.secondary
                    font.pixelSize: Theme.small
                    Layout.fillWidth: true
                }
            }
            SplatButton {
                objectName: "checkSourceFiles"
                text: "Check Source Files"
                enabled: page.vm.sources.count > 0 && page.vm.state.canMutate
                onClicked: page.vm.verifySources()
            }
        }
    }
    SplatCard {
        objectName: "sourcesEmptyState"
        visible: page.vm.sources.count === 0
        Layout.fillWidth: true
        Layout.preferredHeight: page.listHeight
        ColumnLayout {
            anchors.centerIn: parent
            width: Math.min(parent.width, 560)
            spacing: 12
            SplatLabel {
                text: "or drop photo/video files here"
                font.pixelSize: Theme.section
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
            }
            SplatLabel {
                text: "SplatForge keeps your original files in place and references them from the project."
                color: Theme.secondary
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
            }
        }
    }
    SplatCard {
        visible: page.vm.sources.count > 0
        Layout.fillWidth: true
        Layout.preferredHeight: page.listHeight
        padding: 0
        ColumnLayout {
            anchors.fill: parent
            spacing: 0
            RowLayout {
                Layout.fillWidth: true
                Layout.margins: 12
                SplatLabel {
                    text: "Source files"
                    font.weight: Font.DemiBold
                    Layout.fillWidth: true
                }
                SplatButton {
                    objectName: "sourceDetails"
                    text: "Details"
                    enabled: page.vm.sources.selectedId !== ""
                    onClicked: details.open()
                }
            }
            ListView {
                id: sources
                objectName: "sourceList"
                Layout.fillWidth: true
                Layout.fillHeight: true
                model: page.vm.sources
                clip: true
                reuseItems: true
                currentIndex: page.vm.sources.selectedIndex
                onCurrentIndexChanged: {
                    if (currentIndex >= 0)
                        positionViewAtIndex(currentIndex, ListView.Contain);
                }
                delegate: ItemDelegate {
                    id: source
                    required property var record
                    required property string recordId
                    width: sources.width
                    height: 76
                    hoverEnabled: true
                    focusPolicy: Qt.StrongFocus
                    objectName: "source-" + recordId
                    Accessible.name: record.filename + ", " + record.description + ", " + record.availability
                    onClicked: page.vm.media.selectSource(recordId)
                    background: Rectangle {
                        color: page.vm.sources.selectedId === source.recordId ? Theme.selection :
                               source.hovered ? Theme.hover : "transparent"
                        border.width: source.visualFocus ? 2 : 0
                        border.color: Theme.accent
                    }
                    contentItem: RowLayout {
                        spacing: 16
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            SplatLabel {
                                text: source.record.filename
                                font.weight: Font.DemiBold
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                                wrapMode: Text.NoWrap
                            }
                            SplatLabel {
                                text: source.record.description
                                color: Theme.secondary
                                font.pixelSize: Theme.small
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                                wrapMode: Text.NoWrap
                            }
                        }
                        SplatLabel {
                            text: source.record.availability
                            color: Theme.secondary
                            font.pixelSize: Theme.small
                        }
                        SplatButton {
                            text: "Preview"
                            visible: source.record.type === "photo"
                            onClicked: page.vm.media.previewSource(source.recordId)
                        }
                    }
                }
                ScrollBar.vertical: ScrollBar {
                    policy: sources.contentHeight > sources.height ? ScrollBar.AlwaysOn : ScrollBar.AsNeeded
                }
            }
        }
    }
    RowLayout {
        id: footer
        Layout.fillWidth: true
        SplatLabel {
            text: page.vm.sources.count > 0
                  ? "Sources are saved. Prepare Data is not available yet."
                  : "Add photos or videos to get started."
            color: Theme.secondary
            Layout.fillWidth: true
        }
        SplatButton {
            objectName: "sourcesContinue"
            text: "Continue →"
            enabled: false
            Accessible.description: "Prepare Data is not available yet"
        }
    }
    SourceDetailsDialog {
        id: details
        vm: page.vm
    }
    FileDialog {
        id: photos
        objectName: "photosPicker"
        title: "Add photos"
        fileMode: FileDialog.OpenFiles
        nameFilters: ["Photos (*.jpg *.jpeg *.png)"]
        onAccepted: page.vm.addFiles(selectedFiles.map(u => String(u)))
    }
    FileDialog {
        id: videos
        objectName: "videosPicker"
        title: "Add video"
        fileMode: FileDialog.OpenFiles
        nameFilters: ["Videos (*.mp4 *.mov)"]
        onAccepted: page.vm.addFiles(selectedFiles.map(u => String(u)))
    }
    FolderDialog {
        id: folders
        title: "Add folder — top level only"
        onAccepted: page.vm.addFolder(String(selectedFolder))
    }
}

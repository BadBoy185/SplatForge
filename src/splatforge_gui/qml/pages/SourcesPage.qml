pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
import "../theme"
import "../components"

ColumnLayout {
    id: page
    required property var vm
    spacing: 24
    SplatPageHeader {
        title: "Sources"
        subtitle: page.vm.sources.count + " original sources · read-only references"
        Layout.fillWidth: true
        SplatButton {
            visible: page.vm.sources.count > 0
            text: "Add folder"
            iconName: "folder"
            enabled: page.vm.state.canMutate
            onClicked: folders.open()
        }
        SplatButton {
            visible: page.vm.sources.count > 0
            text: "Add files"
            iconName: "plus"
            kind: "primary"
            enabled: page.vm.state.canMutate
            onClicked: files.open()
        }
    }
    SplatCard {
        objectName: "sourcesEmptyState"
        visible: page.vm.sources.count === 0
        Layout.fillWidth: true
        implicitHeight: 350
        ColumnLayout {
            anchors.centerIn: parent
            width: Math.min(parent.width, 560)
            spacing: 16
            SplatLabel {
                text: "Add source data"
                font.pixelSize: Theme.title
                font.weight: Font.DemiBold
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
            }
            SplatLabel {
                text: "Add the photos and videos you want to use."
                color: Theme.secondary
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
            }
            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                spacing: 12
                SplatButton {
                    text: "Add Photos"
                    objectName: "addPhotos"
                    iconName: "plus"
                    kind: "primary"
                    enabled: page.vm.state.canMutate
                    onClicked: photos.open()
                }
                SplatButton {
                    text: "Add Video"
                    objectName: "addVideo"
                    iconName: "plus"
                    enabled: page.vm.state.canMutate
                    onClicked: videos.open()
                }
            }
            SplatLabel {
                text: "or drop photo and video files here"
                color: Theme.secondary
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
            }
            SplatButton {
                text: "Add folder…"
                kind: "ghost"
                Layout.alignment: Qt.AlignHCenter
                enabled: page.vm.state.canMutate
                onClicked: folders.open()
                Accessible.description: "Add supported files from the top level of a folder"
            }
            SplatLabel {
                text: "SplatForge will detect cameras and organize files automatically."
                color: Theme.muted
                font.pixelSize: Theme.small
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
            }
        }
    }
    SplatCard {
        visible: page.vm.sources.count > 0
        Layout.fillWidth: true
        padding: 0
        implicitHeight: Math.min(320, 64 + page.vm.sources.count * 58)
        ColumnLayout {
            anchors.fill: parent
            spacing: 0
            RowLayout {
                Layout.fillWidth: true
                Layout.margins: 16
                SplatLabel {
                    text: "SOURCE MEDIA"
                    font.pixelSize: Theme.caption
                    font.letterSpacing: 1
                    color: Theme.muted
                    Layout.fillWidth: true
                }
                SplatButton {
                    text: "Verify sources"
                    kind: "ghost"
                    enabled: page.vm.state.canMutate
                    onClicked: page.vm.verifySources()
                    Accessible.description:
                        "Balanced/local verification; metadata reuse is reported explicitly"
                }
            }
            ListView {
                id: sources
                Layout.fillWidth: true
                Layout.fillHeight: true
                model: page.vm.sources
                clip: true
                reuseItems: true
                delegate: ItemDelegate {
                    id: source
                    required property var record
                    required property string recordId
                    width: sources.width
                    height: 58
                    hoverEnabled: true
                    focusPolicy: Qt.StrongFocus
                    Accessible.name: record.filename + " " + record.type
                    onClicked: page.vm.media.selectSource(recordId)
                    background: Rectangle {
                        color: page.vm.sources.selectedId === source.recordId ? Theme.selection :
                                                                                source.hovered
                                                                                ? Theme.hover :
                                                                                  "transparent"
                        border.width: source.visualFocus ? 2 : 0
                        border.color: Theme.accent
                    }
                    contentItem: RowLayout {
                        spacing: 16
                        SplatButton {
                            iconName: "sources"
                            kind: "ghost"
                            enabled: false
                            opacity: 1
                        }
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
                                text: page.vm.state.mode === "Advanced"
                                      ? source.record.verification : source.record.verificationLabel
                                color: Theme.muted
                                font.pixelSize: Theme.caption
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                                wrapMode: Text.NoWrap
                            }
                        }
                        SplatLabel {
                            text: source.record.dimensions
                            color: Theme.secondary
                            Layout.preferredWidth: 120
                        }
                        SplatBadge {
                            text: source.record.type
                        }
                    }
                }
                ScrollBar.vertical: ScrollBar {}
            }
        }
    }
    RowLayout {
        visible: page.vm.sources.count > 0
        Layout.fillWidth: true
        spacing: 16
        SplatLabel {
            text: "Media browser"
            font.pixelSize: Theme.section
            font.weight: Font.DemiBold
            Layout.fillWidth: true
        }
        RunPicker {
            workflow: page.vm.workflow
            inputKind: "views"
            Layout.preferredWidth: Math.min(300, page.width * 0.4)
        }
        SplatButton {
            text: "Load views"
            enabled: page.vm.workflow.state.inputs.views !== ""
            onClicked: page.vm.media.loadGallery(page.vm.workflow.state.inputs.views, 0)
        }
    }
    SplatLabel {
        visible: page.vm.sources.count > 0
        text: page.vm.media.state.message
              || "Select a photo for a bounded preview, or load published views from a video."
        color: Theme.secondary
        Layout.fillWidth: true
    }
    GridLayout {
        visible: page.vm.sources.count > 0
        columns: page.width > 1050 ? 2 : 1
        Layout.fillWidth: true
        columnSpacing: 16
        rowSpacing: 16
        SplatCard {
            Layout.fillWidth: true
            Layout.preferredWidth: 3
            Layout.preferredHeight: 300
            padding: 12
            GridView {
                id: gallery
                anchors.fill: parent
                model: page.vm.media.gallery
                cellWidth: 200
                cellHeight: 226
                clip: true
                delegate: ItemDelegate {
                    id: imageItem
                    required property string caption
                    required property string imageUrl
                    required property string previewStatus
                    required property int index
                    width: 192
                    height: 218
                    onClicked: page.vm.media.preview(index)
                    Accessible.name: caption + ", " + previewStatus
                    background: Rectangle {
                        color: imageItem.hovered ? Theme.hover : Theme.background
                        radius: Theme.radius
                        border.color: imageItem.visualFocus ? Theme.accent : "transparent"
                    }
                    contentItem: ColumnLayout {
                        Item {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Image {
                                anchors.fill: parent
                                source: imageItem.imageUrl
                                sourceSize: Qt.size(192, 192)
                                cache: false
                                fillMode: Image.PreserveAspectFit
                            }
                            SplatLabel {
                                anchors.centerIn: parent
                                width: parent.width - 16
                                horizontalAlignment: Text.AlignHCenter
                                text: imageItem.previewStatus
                                color: Theme.secondary
                                font.pixelSize: Theme.small
                                visible: imageItem.previewStatus !== "Ready"
                            }
                        }
                        SplatLabel {
                            text: imageItem.caption
                            font.pixelSize: Theme.small
                            Layout.fillWidth: true
                            elide: Text.ElideMiddle
                            wrapMode: Text.NoWrap
                        }
                    }
                }
                SplatLabel {
                    anchors.centerIn: parent
                    visible: gallery.count === 0
                    text: "No preview selected"
                    color: Theme.muted
                }
                ScrollBar.vertical: ScrollBar {}
            }
        }
        SplatCard {
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            Layout.preferredHeight: 300
            ColumnLayout {
                anchors.fill: parent
                spacing: 12
                SplatLabel {
                    text: "Source details"
                    font.weight: Font.DemiBold
                }
                SplatLabel {
                    text: page.vm.sources.selected.filename || "Select a source"
                    font.pixelSize: Theme.section
                    Layout.fillWidth: true
                }
                SplatLabel {
                    text: page.vm.sources.selected.dimensions || ""
                    color: Theme.secondary
                }
                SplatLabel {
                    text: (page.vm.state.mode === "Advanced"
                           ? page.vm.sources.selected.verification :
                             page.vm.sources.selected.verificationLabel)
                          || "Verification evidence is shown exactly as recorded."
                    color: Theme.secondary
                    Layout.fillWidth: true
                    font.pixelSize: Theme.small
                }
                Item {
                    Layout.fillHeight: true
                }
                SplatLabel {
                    text: page.vm.sources.selected.locator || ""
                    color: Theme.muted
                    Layout.fillWidth: true
                    font.family: Theme.mono
                    font.pixelSize: Theme.caption
                    maximumLineCount: 3
                    elide: Text.ElideMiddle
                }
            }
        }
    }
    RowLayout {
        visible: page.vm.sources.count > 0
        Layout.alignment: Qt.AlignRight
        SplatLabel {
            text: "Views " + page.vm.media.state.offset + "–" + (page.vm.media.state.offset
                                                                 + page.vm.media.state.count)
            color: Theme.muted
            font.pixelSize: Theme.small
        }
        SplatButton {
            text: "Previous"
            enabled: page.vm.media.state.offset > 0
            onClicked: page.vm.media.loadGallery(page.vm.workflow.state.inputs.views,
                                                 page.vm.media.state.offset - 100)
        }
        SplatButton {
            text: "Next 100"
            enabled: page.vm.media.state.count === 100
            onClicked: page.vm.media.loadGallery(page.vm.workflow.state.inputs.views,
                                                 page.vm.media.state.offset + 100)
        }
    }
    FileDialog {
        id: photos
        title: "Add photos"
        fileMode: FileDialog.OpenFiles
        nameFilters: ["Photos (*.jpg *.jpeg *.png)"]
        onAccepted: page.vm.addFiles(selectedFiles.map(u => String(u)))
    }
    FileDialog {
        id: videos
        title: "Add video"
        fileMode: FileDialog.OpenFiles
        nameFilters: ["Videos (*.mp4 *.mov)"]
        onAccepted: page.vm.addFiles(selectedFiles.map(u => String(u)))
    }
    FileDialog {
        id: files
        title: "Add read-only sources"
        fileMode: FileDialog.OpenFiles
        nameFilters: ["Media (*.jpg *.jpeg *.png *.mp4 *.mov)"]
        onAccepted: page.vm.addFiles(selectedFiles.map(u => String(u)))
    }
    FolderDialog {
        id: folders
        title: "Add folder — top level only"
        onAccepted: page.vm.addFolder(String(selectedFolder))
    }
}

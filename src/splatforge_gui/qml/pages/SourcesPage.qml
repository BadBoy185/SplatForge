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
            text: "Add folder"
            iconName: "folder"
            enabled: page.vm.state.canMutate
            onClicked: folders.open()
        }
        SplatButton {
            text: "Add files"
            iconName: "plus"
            kind: "primary"
            enabled: page.vm.state.canMutate
            onClicked: files.open()
        }
    }
    SplatEmptyState {
        visible: page.vm.sources.count === 0
        Layout.fillWidth: true
        title: "Your captures belong here"
        detail: "Add JPEG or PNG photos, MP4 or MOV videos from ordinary perspective cameras. Sources are fully hashed at ingest."
        iconName: "sources"
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
        text: page.vm.media.state.message
              || "Select a photo for a bounded preview, or load published views from a video."
        color: Theme.secondary
        Layout.fillWidth: true
    }
    GridLayout {
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

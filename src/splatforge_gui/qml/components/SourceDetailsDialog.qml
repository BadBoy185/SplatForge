pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../theme"

SplatDialog {
    id: dialog
    required property var vm
    readonly property bool hasViews: vm.workflow.state.choices.views.length > 1
    objectName: "sourceDetailsDialog"
    title: vm.sources.selected.filename || "Source details"
    height: Math.min(700, Overlay.overlay.height - 48)
    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        SplatLabel {
            text: dialog.vm.sources.selected.description || ""
            Layout.fillWidth: true
        }
        SplatLabel {
            text: dialog.vm.sources.selected.availability || ""
            color: Theme.secondary
            Layout.fillWidth: true
        }
        DetailsPanel {
            title: "Technical Details"
            detailsHeight: 110
            Layout.fillWidth: true
            text: "Source ID: " + (dialog.vm.sources.selected.identity || "")
                  + "\nLocation: " + (dialog.vm.sources.selected.locator || "")
                  + "\n" + (dialog.vm.sources.selected.verificationLabel || "")
                  + "\nSHA-256: " + (dialog.vm.sources.selected.sha256 || "")
                  + "\nCodec: " + (dialog.vm.sources.selected.codec || "Not recorded")
        }
        SplatLabel {
            visible: !dialog.hasViews
            text: "No prepared result yet.\nPrepare Data will become available after sources are ready."
            color: Theme.secondary
            Layout.fillWidth: true
        }
        RowLayout {
            visible: dialog.hasViews
            Layout.fillWidth: true
            RunPicker {
                workflow: dialog.vm.workflow
                inputKind: "views"
                Layout.fillWidth: true
            }
            SplatButton {
                text: "Load views"
                enabled: dialog.vm.workflow.state.inputs.views !== ""
                onClicked: dialog.vm.media.loadGallery(dialog.vm.workflow.state.inputs.views, 0)
            }
        }
        SplatLabel {
            visible: dialog.hasViews && text !== ""
            text: dialog.vm.media.state.message
            color: Theme.secondary
            Layout.fillWidth: true
        }
        GridView {
            id: gallery
            visible: dialog.vm.media.state.galleryRun !== "" && count > 0
            Layout.fillWidth: true
            Layout.fillHeight: true
            model: dialog.vm.media.gallery
            cellWidth: 170
            cellHeight: 160
            clip: true
            delegate: ItemDelegate {
                id: view
                required property string caption
                required property string imageUrl
                required property string previewStatus
                required property int index
                width: 164
                height: 154
                onClicked: dialog.vm.media.preview(index)
                contentItem: ColumnLayout {
                    Image {
                        source: view.imageUrl
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        sourceSize: Qt.size(160, 120)
                        fillMode: Image.PreserveAspectFit
                        cache: false
                    }
                    SplatLabel {
                        text: view.previewStatus === "Ready" ? view.caption : view.previewStatus
                        font.pixelSize: Theme.caption
                        Layout.fillWidth: true
                        elide: Text.ElideMiddle
                        wrapMode: Text.NoWrap
                    }
                }
            }
            ScrollBar.vertical: ScrollBar {}
        }
        RowLayout {
            objectName: "viewsPagination"
            visible: dialog.vm.media.state.galleryRun !== ""
                     && dialog.vm.media.state.count > 0
                     && (dialog.vm.media.state.offset > 0 || dialog.vm.media.state.count === 100)
            SplatButton {
                text: "Previous"
                enabled: dialog.vm.media.state.offset > 0
                onClicked: dialog.vm.media.loadGallery(dialog.vm.media.state.galleryRun,
                                                     dialog.vm.media.state.offset - 100)
            }
            SplatLabel {
                text: "Views " + (dialog.vm.media.state.offset + 1) + "–"
                      + (dialog.vm.media.state.offset + dialog.vm.media.state.count)
                color: Theme.secondary
            }
            SplatButton {
                text: "Next 100"
                enabled: dialog.vm.media.state.count === 100
                onClicked: dialog.vm.media.loadGallery(dialog.vm.media.state.galleryRun,
                                                     dialog.vm.media.state.offset + 100)
            }
        }
        Item { Layout.fillHeight: true }
        SplatButton {
            text: "Close"
            Layout.alignment: Qt.AlignRight
            onClicked: dialog.close()
        }
    }
}

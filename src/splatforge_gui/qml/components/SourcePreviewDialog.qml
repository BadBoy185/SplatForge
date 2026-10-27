pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../theme"

SplatDialog {
    id: dialog
    required property var media
    objectName: "imageDialog"
    title: media.state.previewTitle
    width: Math.min(1100, Overlay.overlay.width - 48)
    height: Math.min(800, Overlay.overlay.height - 48)
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    onClosed: media.closePreview()
    header: RowLayout {
        spacing: 12
        ColumnLayout {
            Layout.fillWidth: true
            Layout.margins: 20
            spacing: 4
            SplatLabel {
                objectName: "previewFilename"
                text: dialog.title
                font.pixelSize: Theme.section
                font.weight: Font.DemiBold
                Layout.fillWidth: true
                elide: Text.ElideMiddle
                wrapMode: Text.NoWrap
            }
            SplatLabel {
                text: dialog.media.state.previewDescription || "Photo preview"
                color: Theme.secondary
                font.pixelSize: Theme.small
            }
        }
        SplatButton {
            objectName: "closeImagePreview"
            iconName: "close"
            Layout.rightMargin: 16
            Accessible.name: "Close preview"
            onClicked: dialog.close()
        }
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Image {
                objectName: "previewImage"
                anchors.fill: parent
                source: dialog.media.state.largeImage
                cache: false
                fillMode: Image.PreserveAspectFit
            }
            ColumnLayout {
                anchors.centerIn: parent
                width: parent.width
                visible: dialog.media.state.previewStatus !== "Ready"
                SplatLabel {
                    objectName: "previewStatus"
                    text: dialog.media.state.previewStatus
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    font.pixelSize: Theme.section
                }
                SplatLabel {
                    text: "The source file could not be displayed."
                    visible: dialog.media.state.previewStatus === "Preview unavailable"
                    color: Theme.secondary
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                }
            }
        }
        DetailsPanel {
            title: "Technical Details"
            detailsHeight: 110
            text: dialog.media.state.previewDetails
            visible: text !== ""
            Layout.fillWidth: true
        }
        RowLayout {
            Layout.fillWidth: true
            SplatButton {
                objectName: "previousImage"
                text: "← Previous"
                enabled: dialog.media.state.canPrevious
                onClicked: dialog.media.stepPreview(-1)
            }
            SplatLabel {
                objectName: "previewPosition"
                text: dialog.media.state.previewIndex + " of " + dialog.media.state.previewCount
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                color: Theme.secondary
            }
            SplatButton {
                objectName: "nextImage"
                text: "Next →"
                enabled: dialog.media.state.canNext
                onClicked: dialog.media.stepPreview(1)
            }
        }
    }
    Shortcut {
        sequence: "Left"
        enabled: dialog.visible && dialog.media.state.canPrevious
        onActivated: dialog.media.stepPreview(-1)
    }
    Shortcut {
        sequence: "Right"
        enabled: dialog.visible && dialog.media.state.canNext
        onActivated: dialog.media.stepPreview(1)
    }
}

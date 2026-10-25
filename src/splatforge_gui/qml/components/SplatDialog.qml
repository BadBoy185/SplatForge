pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import "../theme"

Dialog {
    id: dialog
    anchors.centerIn: Overlay.overlay
    modal: true
    padding: 24
    width: Math.min(640, Overlay.overlay ? Overlay.overlay.width - 64 : 640)
    closePolicy: Popup.CloseOnEscape
    font.family: Theme.font
    palette.text: Theme.text
    palette.windowText: Theme.text
    background: Rectangle {
        color: Theme.surface
        radius: Theme.cardRadius
        border.color: Theme.strong
    }
    header: SplatLabel {
        text: dialog.title
        padding: 24
        bottomPadding: 12
        font.pixelSize: Theme.section
        font.weight: Font.DemiBold
    }
    Overlay.modal: Rectangle {
        color: Qt.alpha(Theme.background, 0.75)
    }
}

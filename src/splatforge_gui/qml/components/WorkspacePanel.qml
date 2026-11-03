pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic

ScrollView {
    id: panel
    required property Component contentComponent
    objectName: "pageScroll"
    clip: true
    contentWidth: availableWidth
    contentHeight: contentLoader.y + contentLoader.height + 16

    Loader {
        id: contentLoader
        width: panel.availableWidth - 32
        height: item ? item.implicitHeight : 0
        x: 16
        y: 16
        sourceComponent: panel.contentComponent
    }
}

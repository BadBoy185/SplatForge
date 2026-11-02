pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic

ScrollView {
    id: panel
    required property Component contentComponent
    objectName: "pageScroll"
    clip: true
    contentWidth: availableWidth
    Loader {
        width: panel.availableWidth - 32
        x: 16
        y: 16
        sourceComponent: panel.contentComponent
    }
}

pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: banner
    property string text: ""
    property string action: ""
    property color tone: Theme.warning
    signal activated
    implicitHeight: content.implicitHeight + 24
    radius: Theme.radius
    color: Qt.alpha(tone, 0.09)
    RowLayout {
        id: content
        anchors.fill: parent
        anchors.margins: 12
        spacing: 12
        SplatLabel {
            text: banner.text
            Layout.fillWidth: true
            color: banner.tone
            font.pixelSize: Theme.small
        }
        SplatButton {
            text: banner.action
            visible: text !== ""
            kind: "ghost"
            onClicked: banner.activated()
        }
    }
}

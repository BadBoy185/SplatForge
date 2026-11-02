pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: badge
    property string text: "Not checked"
    property color tone: Theme.statusColor(text)
    implicitWidth: label.implicitWidth + 3 * Theme.space
    implicitHeight: 24
    radius: Theme.controlRadius
    color: Qt.alpha(tone, Theme.dark ? 0.12 : 0.08)
    RowLayout {
        anchors.centerIn: parent
        spacing: Theme.spaceSmall
        Rectangle {
            width: 5
            height: 5
            radius: 2
            color: badge.tone
        }
        SplatLabel {
            id: label
            text: badge.text
            font.pixelSize: Theme.caption
            font.weight: Font.Normal
            color: badge.tone
        }
    }
    Accessible.role: Accessible.StaticText
    Accessible.name: text
}

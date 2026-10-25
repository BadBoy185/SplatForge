pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: badge
    property string text: "Not checked"
    property color tone: Theme.statusColor(text)
    implicitWidth: label.implicitWidth + 28
    implicitHeight: 24
    radius: 5
    color: Qt.alpha(tone, Theme.dark ? 0.12 : 0.08)
    RowLayout {
        anchors.centerIn: parent
        spacing: 6
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
            font.weight: Font.DemiBold
            color: badge.tone
        }
    }
    Accessible.role: Accessible.StaticText
    Accessible.name: text
}

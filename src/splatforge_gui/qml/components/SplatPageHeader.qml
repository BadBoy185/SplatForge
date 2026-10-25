pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../theme"

RowLayout {
    id: header
    property string title: ""
    property string subtitle: ""
    default property alias actions: actions.data
    spacing: 16
    ColumnLayout {
        Layout.fillWidth: true
        spacing: 6
        SplatLabel {
            text: header.title
            font.pixelSize: Theme.title
            font.weight: Font.DemiBold
            Layout.fillWidth: true
        }
        SplatLabel {
            text: header.subtitle
            color: Theme.secondary
            Layout.fillWidth: true
            visible: text !== ""
        }
    }
    RowLayout {
        id: actions
        spacing: 8
    }
}

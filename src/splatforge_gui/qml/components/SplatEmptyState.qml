pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../theme"

SplatCard {
    id: empty
    property string title: "Nothing here yet"
    property string detail: ""
    property string iconName: "cube"
    property string action: ""
    signal activated
    implicitHeight: 240
    ColumnLayout {
        anchors.centerIn: parent
        width: Math.min(parent.width, 460)
        spacing: 12
        SplatButton {
            Layout.alignment: Qt.AlignHCenter
            iconName: empty.iconName
            enabled: false
            width: 48
            height: 48
        }
        SplatLabel {
            text: empty.title
            font.pixelSize: Theme.section
            font.weight: Font.DemiBold
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
        }
        SplatLabel {
            text: empty.detail
            color: Theme.secondary
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
        }
        SplatButton {
            text: empty.action
            visible: text !== ""
            Layout.alignment: Qt.AlignHCenter
            onClicked: empty.activated()
        }
    }
}

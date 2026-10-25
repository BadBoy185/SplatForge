pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../theme"

SplatCard {
    id: card
    property string label: ""
    property string value: "—"
    property string detail: ""
    implicitHeight: 120
    ColumnLayout {
        anchors.fill: parent
        spacing: 6
        SplatLabel {
            text: card.label
            color: Theme.secondary
            font.pixelSize: Theme.small
        }
        SplatLabel {
            text: card.value
            font.pixelSize: Theme.title
            font.weight: Font.DemiBold
        }
        SplatLabel {
            text: card.detail
            color: Theme.muted
            font.pixelSize: Theme.caption
            visible: text !== ""
        }
    }
}

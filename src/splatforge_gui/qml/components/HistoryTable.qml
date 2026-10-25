pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../theme"

SplatCard {
    id: history
    required property var records
    required property var headers
    signal activated(string identity)
    padding: 0
    implicitHeight: 280
    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        HorizontalHeaderView {
            syncView: table
            Layout.fillWidth: true
            model: history.headers
            clip: true
            delegate: Rectangle {
                id: heading
                required property var modelData
                implicitHeight: 36
                implicitWidth: 190
                color: Theme.raised
                SplatLabel {
                    anchors.fill: parent
                    anchors.margins: 8
                    text: heading.modelData
                    color: Theme.secondary
                    font.pixelSize: Theme.small
                    elide: Text.ElideRight
                    wrapMode: Text.NoWrap
                }
            }
        }
        TableView {
            id: table
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: history.records
            columnWidthProvider: column => column === 0 ? 300 : 180
            rowHeightProvider: () => 40
            delegate: ItemDelegate {
                id: cell
                required property string cellText
                required property string recordId
                implicitWidth: 180
                implicitHeight: 40
                onClicked: {
                    history.records.select(recordId);
                    history.activated(recordId);
                }
                Accessible.name: cellText
                contentItem: SplatLabel {
                    text: cell.cellText
                    font.family: Theme.mono
                    font.pixelSize: Theme.small
                    elide: Text.ElideRight
                    wrapMode: Text.NoWrap
                    verticalAlignment: Text.AlignVCenter
                }
                background: Rectangle {
                    color: history.records.selectedId === cell.recordId ? Theme.selection :
                                                                          cell.hovered
                                                                          ? Theme.hover :
                                                                            Theme.surface
                    border.color: cell.visualFocus ? Theme.accent : "transparent"
                }
            }
            ScrollBar.vertical: ScrollBar {}
            ScrollBar.horizontal: ScrollBar {}
        }
    }
}

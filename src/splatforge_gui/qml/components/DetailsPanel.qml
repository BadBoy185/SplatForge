pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../theme"

SplatCard {
    id: panel
    property string title: "Exact evidence"
    property string text: ""
    property bool expanded: false
    implicitHeight: content.implicitHeight + padding * 2
    ColumnLayout {
        id: content
        width: parent.width
        spacing: 12
        SplatButton {
            text: panel.title
            iconName: "chevron"
            kind: "ghost"
            Layout.fillWidth: true
            onClicked: panel.expanded = !panel.expanded
            Accessible.description: panel.expanded ? "Expanded" : "Collapsed"
        }
        ScrollView {
            visible: panel.expanded
            Layout.fillWidth: true
            Layout.preferredHeight: 280
            clip: true
            TextArea {
                text: panel.text || "No evidence yet. Run the relevant inspection or Plan."
                readOnly: true
                selectByMouse: true
                color: Theme.secondary
                font.family: Theme.mono
                font.pixelSize: Theme.small
                wrapMode: TextEdit.Wrap
                background: null
                Accessible.name: panel.title
            }
        }
    }
}

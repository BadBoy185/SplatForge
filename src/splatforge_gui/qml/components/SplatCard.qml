pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import "../theme"

Pane {
    padding: Theme.padding
    background: Rectangle {
        color: Theme.surface
        radius: Theme.cardRadius
    }
}

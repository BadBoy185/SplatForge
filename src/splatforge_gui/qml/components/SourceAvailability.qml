pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../theme"

RowLayout {
    id: indicator
    required property var record
    readonly property string stateName: record.availabilityState || "neutral"
    readonly property color semanticColor: stateName === "available" ? Theme.success
        : stateName === "missing" ? Theme.danger : stateName === "warning" ? Theme.warning
        : Theme.secondary
    spacing: 6
    Accessible.name: record.availability || "Not checked this session"
    Accessible.description: record.availabilityDetail || ""
    SplatLabel {
        text: indicator.stateName === "neutral" ? "○" : "●"
        color: indicator.semanticColor
        Accessible.ignored: true
    }
    SplatLabel {
        text: indicator.record.availability || "Not checked this session"
        color: indicator.semanticColor
        font.pixelSize: Theme.small
        elide: Text.ElideRight
        wrapMode: Text.NoWrap
        Layout.fillWidth: true
    }
    HoverHandler { id: hover }
    ToolTip.visible: hover.hovered
    ToolTip.text: record.availabilityDetail || ""
}

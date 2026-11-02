pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: panel
    required property var session
    required property var media
    signal closeRequested
    color: Theme.surface
    objectName: "videoTrimProperties"
    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        RowLayout {
            Layout.fillWidth: true; Layout.preferredHeight: Theme.panelHeader
            Layout.leftMargin: Theme.panelInset; Layout.rightMargin: Theme.space
            SplatLabel { text: "Used ranges"; font.pixelSize: Theme.panelHeading; font.weight: Font.DemiBold; Layout.fillWidth: true }
            SplatButton {
                objectName: "collapseMaterialProperties"
                iconName: "close"; kind: "ghost"
                Accessible.name: "Hide used ranges panel"
                onClicked: panel.closeRequested()
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
        ScrollView {
            id: scroll
            Layout.fillWidth: true; Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ColumnLayout {
                width: scroll.availableWidth - 2 * Theme.panelInset
                x: Theme.panelInset
                spacing: Theme.inspectorGap
                Item { height: Theme.spaceSmall }
                SplatLabel {
                    objectName: "videoUsageSummary"
                    text: !panel.session.usage.restricted ? "Entire clip is used"
                        : panel.session.usage.intervals.length === 0 ? "No used ranges"
                        : panel.session.usage.intervals.length + (panel.session.usage.intervals.length === 1 ? " used range" : " used ranges")
                    font.weight: Font.DemiBold
                    Layout.fillWidth: true
                }
                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border; Layout.topMargin: 4; Layout.bottomMargin: 2 }
                SplatLabel {
                    text: panel.session.selectedIndex >= 0 ? "Used range " + (panel.session.selectedIndex + 1) : "Range selection"
                    font.weight: Font.DemiBold
                    Layout.fillWidth: true
                }
                SplatLabel {
                    text: "Start · source seconds"
                    Layout.fillWidth: true
                    color: Theme.secondary; font.pixelSize: Theme.small
                }
                SplatTextField {
                    id: startField
                    objectName: "trimStartInput"
                    text: panel.session.startText
                    placeholderText: "10 or 1001/30"
                    Layout.fillWidth: true
                    enabled: panel.session.usage.canEdit
                    Accessible.name: "Used range start in exact source seconds"
                    onTextEdited: panel.session.startText = text
                    onAccepted: panel.session.selectedIndex >= 0 ? panel.session.applyBounds() : panel.session.projectRange()
                    Keys.onEscapePressed: event => { panel.session.cancelGesture(); panel.session.api.clearError(); event.accepted = true; }
                }
                SplatLabel {
                    text: "End · source seconds, exclusive"
                    Layout.fillWidth: true
                    color: Theme.secondary; font.pixelSize: Theme.small
                }
                SplatTextField {
                    objectName: "trimEndInput"
                    text: panel.session.endText
                    placeholderText: "25 or 2002/30"
                    Layout.fillWidth: true
                    enabled: panel.session.usage.canEdit
                    Accessible.name: "Used range end in exact source seconds, exclusive"
                    onTextEdited: panel.session.endText = text
                    onAccepted: panel.session.selectedIndex >= 0 ? panel.session.applyBounds() : panel.session.projectRange()
                    Keys.onEscapePressed: event => { panel.session.cancelGesture(); panel.session.api.clearError(); event.accepted = true; }
                }
                GridLayout {
                    id: boundaryActions
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    columns: width >= setStart.implicitWidth + setEnd.implicitWidth + columnSpacing ? 2 : 1
                    columnSpacing: Theme.spaceSmall; rowSpacing: Theme.spaceSmall
                    SplatButton {
                        id: setStart
                        objectName: "trimSetStart"
                        text: "Set start"; kind: "secondary"
                        Layout.fillWidth: true; Layout.minimumWidth: 0
                        enabled: panel.session.usage.canEdit && panel.session.mapped
                        onClicked: panel.session.setBoundary(true, panel.session.player.position)
                    }
                    SplatButton {
                        id: setEnd
                        objectName: "trimSetEnd"
                        text: "Set end"; kind: "secondary"
                        Layout.fillWidth: true; Layout.minimumWidth: 0
                        enabled: panel.session.usage.canEdit && panel.session.mapped
                        onClicked: panel.session.setBoundary(false, panel.session.player.position)
                    }
                }
                SplatButton {
                    objectName: "trimApplyBounds"
                    text: "Apply bounds"
                    Layout.fillWidth: true
                    visible: panel.session.selectedIndex >= 0
                    enabled: panel.session.usage.canEdit && panel.session.rangeReady
                    onClicked: panel.session.applyBounds()
                }
                GridLayout {
                    id: rangeActions
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    columns: width >= includeAction.implicitWidth + excludeAction.implicitWidth + columnSpacing ? 2 : 1
                    columnSpacing: Theme.spaceSmall; rowSpacing: Theme.spaceSmall
                    SplatButton {
                        id: includeAction
                        objectName: "trimIncludeRange"
                        text: "Include range"
                        kind: "primary"
                        Layout.fillWidth: true; Layout.minimumWidth: 0
                        leftPadding: Theme.space; rightPadding: Theme.space
                        enabled: panel.session.usage.canEdit && panel.session.rangeReady
                        onClicked: panel.session.includeRange()
                    }
                    SplatButton {
                        id: excludeAction
                        objectName: "trimExcludeRange"
                        text: "Exclude range"; kind: "secondary"
                        Layout.fillWidth: true; Layout.minimumWidth: 0
                        leftPadding: Theme.space; rightPadding: Theme.space
                        enabled: panel.session.usage.canEdit && panel.session.rangeReady
                            && (panel.session.usage.restricted || panel.session.mapped)
                        onClicked: panel.session.excludeRange()
                    }
                }
                SplatLabel {
                    objectName: "trimValidationError"
                    text: panel.session.usage.error.message || panel.session.playReason || panel.session.playbackError
                    visible: text !== ""
                    color: Theme.warning; font.pixelSize: Theme.small
                    Layout.fillWidth: true
                }
                SplatLabel {
                    text: panel.session.mapped ? "Exact PTS seconds or fractions. Displayed clip time is approximate." : panel.session.extent.reason || ""
                    color: Theme.muted; font.pixelSize: Theme.caption
                    Layout.fillWidth: true
                }
                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border; Layout.topMargin: 4; Layout.bottomMargin: 2 }
                Repeater {
                    model: panel.session.usage.intervals
                    delegate: SplatButton {
                        id: rangeRow
                        required property int index
                        required property var modelData
                        readonly property var positions: panel.session.mapped ? panel.session.extent.ranges[index] : null
                        objectName: "trimUsedRange" + index
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        implicitHeight: Theme.rangeRow
                        kind: "ghost"
                        background: Rectangle {
                            color: panel.session.selectedIndex === rangeRow.index ? Theme.selection
                                : rangeRow.down ? Theme.strong : rangeRow.hovered ? Theme.hover : "transparent"
                            border.width: rangeRow.visualFocus ? 2 : 0
                            border.color: Theme.accent
                            Rectangle {
                                width: 2; height: parent.height
                                color: Theme.accent
                                visible: panel.session.selectedIndex === rangeRow.index
                            }
                        }
                        Accessible.name: "Select used range " + (index + 1) + ", " + modelData.start + " to " + modelData.end + " source seconds"
                        contentItem: Item {
                            SplatLabel {
                                width: parent.width
                                height: 20
                                elide: Text.ElideRight
                                wrapMode: Text.NoWrap
                                text: rangeRow.positions ? panel.session.clock(rangeRow.positions.start - panel.session.extent.startPosition)
                                    + " — " + panel.session.clock(rangeRow.positions.end - panel.session.extent.startPosition)
                                    : rangeRow.modelData.start + " — " + rangeRow.modelData.end + " s"
                                font.pixelSize: Theme.body
                                color: panel.session.selectedIndex === rangeRow.index ? Theme.accent : Theme.text
                            }
                            SplatLabel { y: 23; width: parent.width; text: "Used range " + (rangeRow.index + 1); font.pixelSize: Theme.caption; color: Theme.secondary }
                        }
                        onClicked: { panel.session.selectRange(index); panel.session.api.clearError(); }
                    }
                }
                SplatLabel {
                    text: panel.session.usage.restricted && panel.session.usage.intervals.length === 0
                        ? "This video contributes no frames. Include a range or use the entire clip."
                        : !panel.session.usage.restricted ? "No time restriction. The original clip stays available for review." : "Excluded gaps remain on the original timeline."
                    Layout.fillWidth: true; color: Theme.secondary; font.pixelSize: Theme.small
                }
                SplatButton {
                    objectName: "trimRemoveRange"
                    text: "Remove from used"; kind: "ghost"
                    Layout.fillWidth: true
                    visible: panel.session.selectedIndex >= 0
                    enabled: panel.session.usage.canEdit
                    onClicked: panel.session.api.removeInterval(panel.session.selectedIndex)
                }
                SplatButton {
                    objectName: "trimUseEntireClip"
                    text: "Use entire clip"; kind: "secondary"
                    Layout.fillWidth: true
                    enabled: panel.session.usage.canEdit && (panel.session.usage.restricted || Boolean(panel.session.usage.error.code))
                    onClicked: panel.session.api.resetIntervals()
                }
                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border; Layout.topMargin: 4 }
                SplatLabel {
                    text: "Original video is preserved. Save the project to keep used ranges."
                    Layout.fillWidth: true; color: Theme.secondary; font.pixelSize: Theme.small
                }
                SplatButton {
                    objectName: "trimSourceParticipation"
                    text: panel.media.state.previewSource.isIncluded === false ? "Restore source" : "Exclude source"
                    kind: "ghost"; Layout.fillWidth: true
                    enabled: panel.media.state.canChangeParticipation
                    onClicked: panel.media.togglePreviewParticipation()
                }
                Item { height: Theme.space }
            }
        }
    }
}

pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: panel
    required property var vm
    readonly property var sourceRecord: vm.media.state.previewSource
    readonly property bool hasSource: vm.media.state.previewIndex > 0
    signal closeRequested
    signal detailsRequested
    color: Theme.surface
    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.panelHeader
            Layout.leftMargin: Theme.panelInset
            Layout.rightMargin: Theme.space
            SplatLabel {
                text: "Source"
                font.pixelSize: Theme.panelHeading
                font.weight: Font.DemiBold
                Layout.fillWidth: true
            }
            SplatButton {
                objectName: "collapseMaterialProperties"
                iconName: "close"
                kind: "ghost"
                Accessible.name: "Hide source properties"
                onClicked: panel.closeRequested()
            }
        }
        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.border
        }
        ScrollView {
            id: scroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true
            ColumnLayout {
                width: scroll.availableWidth - 2 * Theme.panelInset
                x: Theme.panelInset
                spacing: Theme.panelInset
                SplatLabel {
                    text: panel.vm.media.state.previewTitle || (panel.vm.state.sourcesSummary.registered > 0 ? "No material selected" : "No media yet")
                    Layout.fillWidth: true
                    topPadding: Theme.panelInset
                    font.weight: Font.DemiBold
                    wrapMode: Text.WrapAnywhere
                }
                SplatLabel {
                    objectName: "emptySourceProperties"
                    visible: !panel.hasSource
                    text: panel.vm.state.sourcesSummary.registered > 0 ? "Select a material to see its properties." : "Add media to see source properties."
                    color: Theme.secondary
                    Layout.fillWidth: true
                }
                SourceAvailability {
                    record: panel.sourceRecord
                    visible: panel.hasSource
                    Layout.fillWidth: true
                }
                GridLayout {
                    visible: panel.hasSource
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: Theme.inspectorGap
                    rowSpacing: Theme.inspectorGap
                    Repeater {
                        model: [
                            {
                                label: "Type",
                                value: panel.sourceRecord.type === "video" ? "Video" : "Photo"
                            },
                            {
                                label: "Resolution",
                                value: panel.sourceRecord.dimensions || "Not recorded"
                            },
                            {
                                label: "Duration",
                                value: panel.sourceRecord.type === "video" ? panel.sourceRecord.durationLabel || "Not recorded" : ""
                            },
                            {
                                label: "Device",
                                value: panel.sourceRecord.device || "Unknown device"
                            },
                            {
                                label: "Group",
                                value: panel.sourceRecord.logicalGroupLabel || "Ungrouped"
                            },
                            {
                                label: "Processing",
                                value: panel.sourceRecord.participationLabel || "Included"
                            }
                        ]
                        delegate: RowLayout {
                            id: field
                            required property var modelData
                            visible: modelData.value !== ""
                            Layout.columnSpan: 2
                            Layout.fillWidth: true
                            spacing: Theme.inspectorGap
                            SplatLabel {
                                text: field.modelData.label
                                color: Theme.secondary
                                Layout.preferredWidth: 80
                                font.pixelSize: Theme.small
                            }
                            SplatLabel {
                                text: field.modelData.value
                                Layout.fillWidth: true
                                wrapMode: Text.WrapAnywhere
                            }
                        }
                    }
                }
                SplatButton {
                    objectName: "currentMaterialParticipation"
                    visible: panel.hasSource
                    text: panel.sourceRecord.isIncluded === false ? "Restore to processing" : "Exclude from processing"
                    iconName: panel.sourceRecord.isIncluded === false ? "refresh" : "exclude"
                    Layout.fillWidth: true
                    enabled: panel.vm.media.state.canChangeParticipation
                    Accessible.description: "Applies only to the displayed material; originals stay in place"
                    onClicked: panel.vm.media.togglePreviewParticipation()
                }
                Rectangle {
                    Layout.fillWidth: true
                    visible: panel.hasSource
                    height: 1
                    color: Theme.border
                }
                SplatButton {
                    objectName: "sourceDetails"
                    visible: panel.hasSource
                    text: "Technical details…"
                    iconName: "chevron"
                    kind: "ghost"
                    Layout.fillWidth: true
                    enabled: panel.hasSource
                    onClicked: panel.detailsRequested()
                }
                SplatLabel {
                    visible: !!panel.vm.media.state.sourceDetails.error
                    text: panel.vm.media.state.sourceDetails.error || ""
                    Layout.fillWidth: true
                    color: Theme.warning
                    font.pixelSize: Theme.small
                }
                SplatLabel {
                    text: "Original files stay in place."
                    visible: panel.hasSource
                    color: Theme.muted
                    font.pixelSize: Theme.small
                    Layout.fillWidth: true
                    bottomPadding: Theme.panelInset
                }
            }
        }
        Rectangle {
            Layout.fillWidth: true
            visible: panel.vm.state.sourcesSummary.registered > 0
            height: 1
            color: Theme.border
        }
        SplatLabel {
            visible: panel.vm.state.sourcesSummary.registered > 0
            text: panel.vm.state.sourcesSummary.included + " included · " + panel.vm.state.sourcesSummary.excluded + " excluded"
            color: Theme.secondary
            font.pixelSize: Theme.small
            Layout.fillWidth: true
            Layout.margins: Theme.panelInset
        }
    }
}

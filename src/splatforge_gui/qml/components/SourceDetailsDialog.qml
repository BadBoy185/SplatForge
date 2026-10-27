pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../theme"

SplatDialog {
    id: dialog
    required property var vm
    readonly property bool hasViews: vm.workflow.state.choices.views.length > 1
    readonly property var sourceRecord: vm.sources.selected
    objectName: "sourceDetailsDialog"
    title: sourceRecord.filename || "Source details"
    height: Math.min(720, Overlay.overlay.height - 48)
    onOpened: technical.expanded = false
    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        ScrollView {
            id: scroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true
            ColumnLayout {
                width: scroll.availableWidth
                spacing: 12
                SplatLabel {
                    objectName: "sourceHumanType"
                    text: dialog.sourceRecord.type === "video" ? "Video" : "Photo"
                    font.pixelSize: Theme.section
                }
                RowLayout {
                    SplatLabel {
                        objectName: "sourceHumanDimensions"
                        text: dialog.sourceRecord.dimensions || "Dimensions not recorded"
                        font.pixelSize: Theme.section
                    }
                    SplatLabel {
                        objectName: "sourceHumanDuration"
                        visible: dialog.sourceRecord.type === "video"
                        text: "Duration  " + (dialog.sourceRecord.durationLabel || "Not recorded")
                        color: Theme.secondary
                    }
                }
                SplatLabel {
                    text: "File"
                    font.weight: Font.DemiBold
                }
                SplatLabel {
                    objectName: "sourceHumanLocation"
                    text: "Location  " + (dialog.sourceRecord.locator || "Not recorded")
                    color: Theme.secondary
                    wrapMode: Text.WrapAnywhere
                    Layout.fillWidth: true
                }
                SplatLabel {
                    text: "Status"
                    font.weight: Font.DemiBold
                }
                SourceAvailability {
                    record: dialog.sourceRecord
                    Layout.fillWidth: true
                }
                SplatLabel {
                    objectName: "sourceHumanChecked"
                    text: dialog.sourceRecord.checkedLabel || "Not checked this session"
                    color: Theme.secondary
                    Layout.fillWidth: true
                }
                SplatLabel {
                    visible: dialog.sourceRecord.availabilityDetail !== dialog.sourceRecord.checkedLabel
                    text: dialog.sourceRecord.availabilityDetail || ""
                    color: Theme.secondary
                    Layout.fillWidth: true
                }
                SplatLabel {
                    visible: dialog.sourceRecord.availabilityState === "neutral"
                    text: "Last verified: " + (dialog.sourceRecord.lastVerifiedLabel || "Not recorded")
                    color: Theme.secondary
                    font.pixelSize: Theme.small
                    Layout.fillWidth: true
                }
                SplatLabel {
                    text: "Processing"
                    font.weight: Font.DemiBold
                }
                SplatLabel {
                    text: "Included by default"
                    color: Theme.secondary
                }
                DetailsPanel {
                    id: technical
                    objectName: "sourceTechnicalDetails"
                    title: "Technical Details"
                    detailsHeight: 140
                    Layout.fillWidth: true
                    text: "Source ID: " + (dialog.sourceRecord.identity || "") + "\nSHA-256: " + (dialog.sourceRecord.sha256 || "") + "\nCodec: " + (dialog.sourceRecord.codec || "Not recorded") + "\nSource revision: " + (dialog.sourceRecord.sourceRevision || "") + "\nLast full hash: " + (dialog.sourceRecord.lastHashedAt || "Not recorded") + "\n" + (dialog.sourceRecord.verificationLabel || "")
                }
                ColumnLayout {
                    visible: technical.expanded && dialog.vm.state.mode === "Advanced" && dialog.hasViews
                    Layout.fillWidth: true
                    SplatLabel {
                        text: "Published view inspection"
                        color: Theme.secondary
                    }
                    RowLayout {
                        visible: dialog.hasViews
                        Layout.fillWidth: true
                        RunPicker {
                            workflow: dialog.vm.workflow
                            inputKind: "views"
                            Layout.fillWidth: true
                        }
                        SplatButton {
                            text: "Load views"
                            enabled: dialog.vm.workflow.state.inputs.views !== ""
                            onClicked: dialog.vm.media.loadGallery(dialog.vm.workflow.state.inputs.views, 0)
                        }
                    }
                    SplatLabel {
                        visible: dialog.hasViews && text !== ""
                        text: dialog.vm.media.state.message
                        color: Theme.secondary
                        Layout.fillWidth: true
                    }
                    GridView {
                        id: gallery
                        visible: dialog.vm.media.state.galleryRun !== "" && count > 0
                        Layout.fillWidth: true
                        Layout.preferredHeight: 220
                        model: dialog.vm.media.gallery
                        cellWidth: 170
                        cellHeight: 160
                        clip: true
                        delegate: ItemDelegate {
                            id: view
                            required property string caption
                            required property string imageUrl
                            required property string previewStatus
                            required property int index
                            width: 164
                            height: 154
                            onClicked: dialog.vm.media.preview(index)
                            contentItem: ColumnLayout {
                                Image {
                                    source: view.imageUrl
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    sourceSize: Qt.size(160, 120)
                                    fillMode: Image.PreserveAspectFit
                                    cache: false
                                }
                                SplatLabel {
                                    text: view.previewStatus === "Ready" ? view.caption : view.previewStatus
                                    font.pixelSize: Theme.caption
                                    Layout.fillWidth: true
                                    elide: Text.ElideMiddle
                                    wrapMode: Text.NoWrap
                                }
                            }
                        }
                        ScrollBar.vertical: ScrollBar {}
                    }
                    RowLayout {
                        objectName: "viewsPagination"
                        visible: dialog.vm.media.state.galleryRun !== "" && dialog.vm.media.state.count > 0 && (dialog.vm.media.state.offset > 0 || dialog.vm.media.state.count === 100)
                        SplatButton {
                            text: "Previous"
                            enabled: dialog.vm.media.state.offset > 0
                            onClicked: dialog.vm.media.loadGallery(dialog.vm.media.state.galleryRun, dialog.vm.media.state.offset - 100)
                        }
                        SplatLabel {
                            text: "Views " + (dialog.vm.media.state.offset + 1) + "–" + (dialog.vm.media.state.offset + dialog.vm.media.state.count)
                            color: Theme.secondary
                        }
                        SplatButton {
                            text: "Next 100"
                            enabled: dialog.vm.media.state.count === 100
                            onClicked: dialog.vm.media.loadGallery(dialog.vm.media.state.galleryRun, dialog.vm.media.state.offset + 100)
                        }
                    }
                }
            }
        }
        SplatButton {
            text: "Close"
            objectName: "closeSourceDetails"
            Layout.alignment: Qt.AlignRight
            onClicked: dialog.close()
        }
    }
}

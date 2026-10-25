pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import SplatForge.Preview 1.0
import "../theme"
import "../components"

ColumnLayout {
    id: page
    required property var vm
    readonly property var inspection: vm.inspection
    spacing: 24
    SplatPageHeader {
        title: "Results"
        subtitle: "Explore your published work and its provenance."
        Layout.fillWidth: true
        SplatButton {
            text: "Copy path"
            kind: "ghost"
            enabled: page.inspection.state.hasPreview
            onClicked: page.inspection.action("copyPath")
        }
        SplatButton {
            text: "Open folder"
            iconName: "folder"
            enabled: page.inspection.state.hasPreview
            onClicked: page.inspection.action("openFolder")
        }
    }
    SplatBanner {
        visible: !!page.vm.state.project.truncated
        Layout.fillWidth: true
        text: "Showing the most recent 2000 indexed records. Older history remains available through the CLI."
        tone: Theme.muted
    }
    SplatEmptyState {
        visible: page.vm.outputs.count === 0
        Layout.fillWidth: true
        title: "Your scene takes shape here"
        detail: "Published reconstructions, prepared datasets, checkpoints and Gaussian scenes appear as processing completes."
        iconName: "results"
    }
    RowLayout {
        visible: page.vm.outputs.count > 0
        Layout.fillWidth: true
        spacing: 16
        SplatCard {
            padding: 12
            Layout.preferredWidth: page.width > 1000 ? 248 : 210
            Layout.preferredHeight: 460
            ColumnLayout {
                anchors.fill: parent
                spacing: 12
                SplatLabel {
                    text: "PUBLISHED OUTPUTS"
                    color: Theme.muted
                    font.pixelSize: Theme.caption
                    font.letterSpacing: 1
                    padding: 8
                }
                ListView {
                    id: outputs
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: page.vm.outputs
                    clip: true
                    reuseItems: true
                    spacing: 4
                    delegate: ItemDelegate {
                        id: artifact
                        required property var record
                        required property string recordId
                        width: outputs.width
                        height: 88
                        padding: 12
                        Accessible.name: record.title + " " + record.storage_status
                        onClicked: page.inspection.inspectArtifact(recordId)
                        background: Rectangle {
                            radius: Theme.radius
                            color: page.vm.artifacts.selectedId === artifact.recordId
                                   ? Theme.selection : artifact.hovered ? Theme.hover :
                                                                          "transparent"
                            border.color: artifact.visualFocus ? Theme.accent : "transparent"
                        }
                        contentItem: ColumnLayout {
                            spacing: 6
                            SplatLabel {
                                text: artifact.record.title
                                font.weight: Font.DemiBold
                                Layout.fillWidth: true
                                maximumLineCount: 1
                                elide: Text.ElideRight
                            }
                            SplatLabel {
                                text: artifact.record.storage_status + (artifact.record.pinned
                                                                        ? " · pinned" : "")
                                color: Theme.muted
                                font.pixelSize: Theme.caption
                            }
                            SplatLabel {
                                text: artifact.record.publishedLabel
                                color: Theme.muted
                                font.pixelSize: Theme.caption
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                                wrapMode: Text.NoWrap
                            }
                        }
                    }
                    ScrollBar.vertical: ScrollBar {}
                }
            }
        }
        SplatCard {
            Layout.fillWidth: true
            Layout.preferredHeight: 460
            padding: 0
            ColumnLayout {
                anchors.fill: parent
                spacing: 0
                RowLayout {
                    Layout.fillWidth: true
                    Layout.margins: 16
                    SplatLabel {
                        text: page.vm.artifacts.selected.title || "Point-center viewport"
                        font.weight: Font.DemiBold
                        Layout.fillWidth: true
                    }
                    SplatButton {
                        text: "Reset"
                        kind: "ghost"
                        onClicked: preview.reset()
                        Accessible.description: "Reset orbit and zoom (R)"
                    }
                }
                PointPreview {
                    id: preview
                    objectName: "pointCenterPreview"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    source: page.inspection
                    dark: Theme.dark
                    Accessible.role: Accessible.Canvas
                    Accessible.name: "Point-center preview"
                    Accessible.description:
                        "Drag or arrow keys to orbit, wheel or plus and minus to zoom, R to reset. Not final Gaussian rasterization."
                    Rectangle {
                        anchors.fill: parent
                        color: "transparent"
                        border.width: preview.activeFocus ? 2 : 0
                        border.color: Theme.accent
                    }
                    SplatLabel {
                        visible: page.inspection.state.pointCount === 0
                                 && page.inspection.state.cameraCount === 0
                        anchors.centerIn: parent
                        width: parent.width - 48
                        horizontalAlignment: Text.AlignHCenter
                        text: page.inspection.state.hasPreview
                              ? "This artifact has no point-center sample.\nInspect its metadata and files." :
                                "Select an output to inspect"
                        color: Theme.muted
                    }
                }
                SplatLabel {
                    Layout.fillWidth: true
                    padding: 12
                    text: "Point-center preview — not final Gaussian rasterization."
                    font.pixelSize: Theme.caption
                    color: Theme.secondary
                }
                SplatLabel {
                    Layout.fillWidth: true
                    leftPadding: 12
                    rightPadding: 12
                    bottomPadding: 12
                    text: page.inspection.state.previewLabel
                    font.pixelSize: Theme.caption
                    color: Theme.muted
                }
            }
        }
    }
    SplatCard {
        visible: page.vm.artifacts.selectedId !== ""
        Layout.fillWidth: true
        implicitHeight: resultDetails.implicitHeight + 48
        RowLayout {
            id: resultDetails
            width: parent.width
            spacing: 24
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 8
                SplatLabel {
                    text: page.inspection.state.outputTitle
                    font.pixelSize: Theme.section
                    font.weight: Font.DemiBold
                }
                SplatLabel {
                    text: "Published " + page.inspection.state.publishedAt
                    color: Theme.secondary
                    font.pixelSize: Theme.small
                    Layout.fillWidth: true
                }
            }
            SplatBadge {
                text: page.inspection.state.outputStatus
            }
        }
    }
    RowLayout {
        visible: page.inspection.state.hasPreview
        Layout.fillWidth: true
        spacing: 16
        MetricCard {
            Layout.fillWidth: true
            label: "Sampled centers"
            value: String(page.inspection.state.pointCount)
            detail: "At most 20,000 centers"
        }
        MetricCard {
            Layout.fillWidth: true
            label: "Camera centers"
            value: String(page.inspection.state.cameraCount)
            detail: "At most 2,000 cameras"
        }
        MetricCard {
            Layout.fillWidth: true
            label: "Published payload"
            value: page.inspection.state.payloadBytes !== null ? (
                                                                     page.inspection.state.payloadBytes
                                                                     / 1048576).toFixed(2) + " MiB" :
                                                                 "Unavailable"
            detail: "Indexed immutable artifact"
        }
    }
    SplatLabel {
        visible: page.inspection.state.hasPreview
        text: page.inspection.state.path
        Layout.fillWidth: true
        font.family: Theme.mono
        color: Theme.muted
        font.pixelSize: Theme.small
    }
    RowLayout {
        visible: page.vm.state.mode === "Advanced"
        SplatButton {
            text: "Pin artifact"
            enabled: page.vm.artifacts.selectedId !== "" && page.vm.state.canMutate
            onClicked: page.inspection.action("pin")
        }
        SplatButton {
            text: "Unpin artifact"
            enabled: page.vm.artifacts.selectedId !== "" && page.vm.state.canMutate
            onClicked: page.inspection.action("unpin")
        }
        SplatLabel {
            text: "Pins are explicit. Current, lineage and active protection remain authoritative."
            Layout.fillWidth: true
            color: Theme.muted
            font.pixelSize: Theme.small
        }
    }
    DetailsPanel {
        visible: page.vm.state.mode === "Advanced"
        Layout.fillWidth: true
        title: "Artifact identity, lineage and metadata"
        text: page.inspection.state.metadata
    }
    SplatLabel {
        visible: page.vm.state.mode === "Advanced"
        text: "All artifacts"
        font.pixelSize: Theme.section
        font.weight: Font.DemiBold
    }
    HistoryTable {
        visible: page.vm.state.mode === "Advanced"
        Layout.fillWidth: true
        records: page.vm.artifacts
        headers: ["Type", "Artifact ID", "Semantic digest", "Producer run", "Storage", "Pinned"]
        onActivated: identity => page.inspection.inspectArtifact(identity)
    }
    SplatLabel {
        visible: page.vm.state.mode === "Advanced"
        text: "Run history"
        font.pixelSize: Theme.section
        font.weight: Font.DemiBold
    }
    HistoryTable {
        visible: page.vm.state.mode === "Advanced"
        Layout.fillWidth: true
        records: page.vm.runs
        headers: ["Run ID", "Stage", "Status", "Started", "Finished", "Cache", "Duration (s)",
            "Failure category", "Failure"]
        onActivated: identity => page.inspection.inspectRun(identity)
    }
    DetailsPanel {
        visible: page.vm.state.mode === "Advanced"
        Layout.fillWidth: true
        title: "Selected run evidence"
        text: page.inspection.state.details
    }
}

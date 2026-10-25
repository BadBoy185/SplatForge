pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../theme"
import "../components"

ColumnLayout {
    id: page
    required property var vm
    readonly property var work: vm.workflow
    readonly property var plan: work.state.plans.dataset || ({})
    spacing: 24
    SplatPageHeader {
        title: "Dataset"
        subtitle: "Prepare a precise, traceable foundation for training."
        Layout.fillWidth: true
        SplatButton {
            text: "Plan"
            enabled: page.work.state.inputs.selection !== "" && !page.vm.state.busy
            onClicked: page.work.action("planDataset")
        }
        SplatButton {
            text: "Prepare dataset"
            iconName: "dataset"
            kind: "primary"
            enabled: page.work.state.inputs.selection !== "" && page.vm.state.canMutate
            onClicked: page.work.action("prepareDataset")
        }
    }
    SplatEmptyState {
        visible: page.work.state.choices.selection.length <= 1
        Layout.fillWidth: true
        title: "A deliberate selection comes first"
        detail: "Validate your reconstruction and explicitly choose components. Each component becomes a separate dataset."
        iconName: "dataset"
        action: "Review reconstruction"
        onActivated: page.vm.navigate(2)
    }
    SplatCard {
        Layout.fillWidth: true
        implicitHeight: config.implicitHeight + 48
        ColumnLayout {
            id: config
            width: parent.width
            spacing: 20
            SplatLabel {
                text: "Dataset input"
                font.pixelSize: Theme.section
                font.weight: Font.DemiBold
            }
            SplatLabel {
                text: "Published component selection"
                font.pixelSize: Theme.small
                color: Theme.secondary
            }
            RunPicker {
                workflow: page.work
                inputKind: "selection"
                Layout.fillWidth: true
            }
            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    Layout.fillWidth: true
                    SplatLabel {
                        text: "Maximum image side"
                        font.weight: Font.DemiBold
                    }
                    SplatLabel {
                        text: "0 uses native size. Applies to this run only."
                        color: Theme.muted
                        font.pixelSize: Theme.small
                    }
                }
                SplatTextField {
                    text: String(page.work.state.datasetMaximum)
                    Layout.preferredWidth: 140
                    validator: IntValidator {
                        bottom: 0
                        top: 32768
                    }
                    inputMethodHints: Qt.ImhDigitsOnly
                    onEditingFinished: page.work.setDatasetMaximum(Number(text))
                    Accessible.name: "Maximum image side, zero for native"
                }
                SplatLabel {
                    text: "px"
                    color: Theme.muted
                }
            }
            SplatLabel {
                text: "Uses historical published pixels, cameras and poses. Original media is not reopened for dataset preparation."
                color: Theme.secondary
                Layout.fillWidth: true
                font.pixelSize: Theme.small
            }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        spacing: 16
        MetricCard {
            Layout.fillWidth: true
            label: "Selected components"
            value: page.plan.components ? String(page.plan.components.length) : "Not planned"
            detail: "Separate coordinate systems"
        }
        MetricCard {
            Layout.fillWidth: true
            label: "Required free disk"
            value: page.plan.required_free_disk_bytes !== undefined ? (
                                                                          page.plan.required_free_disk_bytes
                                                                          / 1048576).toFixed(1)
                                                                      + " MiB" : "Not measured"
            detail: "Backend resource evidence"
        }
        MetricCard {
            Layout.fillWidth: true
            label: "Plan status"
            value: page.plan.runnable === undefined ? "Not checked" : page.plan.runnable ? "Runnable" :
                                                                                           "Blocked"
            detail: "Exact input and capability checks"
        }
    }
    SplatBanner {
        visible: !!page.work.state.messages.dataset
        Layout.fillWidth: true
        text: page.work.state.messages.dataset || ""
        tone: page.plan.runnable ? Theme.success : Theme.muted
    }
    SplatBanner {
        visible: (page.plan.diagnostics || []).length > 0
        Layout.fillWidth: true
        text: (page.plan.diagnostics || []).join("\n")
    }
    SplatCard {
        visible: (page.plan.components || []).length > 0
        Layout.fillWidth: true
        implicitHeight: evidence.implicitHeight + 48
        ColumnLayout {
            id: evidence
            width: parent.width
            spacing: 16
            SplatLabel {
                text: "Planned outputs"
                font.pixelSize: Theme.section
                font.weight: Font.DemiBold
            }
            Repeater {
                model: page.plan.components || []
                delegate: RowLayout {
                    id: component
                    required property var modelData
                    required property int index
                    SplatLabel {
                        text: "Component " + (component.index + 1)
                        font.weight: Font.DemiBold
                        Layout.fillWidth: true
                    }
                    SplatLabel {
                        text: component.modelData.registered_views + " images"
                        color: Theme.secondary
                    }
                    SplatLabel {
                        text: Object.keys(component.modelData.input_camera_models).join(" · ")
                        color: Theme.secondary
                    }
                    SplatBadge {
                        text: component.modelData.cache_hit ? "Cached" : "Prepare"
                    }
                }
            }
            SplatLabel {
                text: "Output: undistorted images + sparse cameras, poses and tracks. Current compatibility is validated again before publication."
                color: Theme.muted
                Layout.fillWidth: true
                font.pixelSize: Theme.small
            }
        }
    }
    SplatButton {
        visible: page.vm.state.mode === "Advanced"
        text: "Edit exact dataset settings"
        onClicked: page.work.editExact("dataset")
    }
    DetailsPanel {
        visible: page.vm.state.mode === "Advanced"
        Layout.fillWidth: true
        title: "Exact dataset plan / result"
        text: page.work.state.details.dataset || ""
    }
}

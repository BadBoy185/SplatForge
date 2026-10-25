pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../theme"
import "../components"

ColumnLayout {
    id: page
    required property var vm
    readonly property var inspection: vm.inspection
    spacing: 24
    SplatPageHeader {
        title: "Diagnostics"
        subtitle: "Understand your workstation. Verify each processing route."
        Layout.fillWidth: true
        SplatButton {
            text: "Deep probes"
            visible: page.vm.state.mode === "Advanced"
            enabled: !page.vm.state.busy
            onClicked: page.inspection.action("deepDoctor")
        }
        SplatButton {
            text: "Run Doctor"
            iconName: "diagnostics"
            kind: "primary"
            enabled: !page.vm.state.busy
            onClicked: page.inspection.action("doctor")
        }
    }
    SplatBanner {
        visible: page.vm.state.hasProject && page.vm.state.project.stateVersion < 4
        Layout.fillWidth: true
        text: "Legacy state v" + page.vm.state.project.stateVersion
              + ". Use splatforge project upgrade-state <project> before processing. The application creates a validated backup before upgrading."
    }
    SplatCard {
        visible: page.inspection.state.recoveryRuns.length > 1
        Layout.fillWidth: true
        implicitHeight: recovery.implicitHeight + 48
        ColumnLayout {
            id: recovery
            width: parent.width
            spacing: 16
            RowLayout {
                SplatLabel {
                    text: "Recovery & ownership"
                    font.pixelSize: Theme.section
                    font.weight: Font.DemiBold
                    Layout.fillWidth: true
                }
                SplatBadge {
                    text: "Attention required"
                    tone: Theme.warning
                }
            }
            SplatLabel {
                text: "An active or interrupted run needs inspection. Recovery uses the application's publication and teardown contracts."
                color: Theme.secondary
                Layout.fillWidth: true
            }
            SplatComboBox {
                model: page.inspection.state.recoveryRuns
                textRole: "label"
                valueRole: "value"
                selectedValue: page.inspection.state.recoveryRun
                Layout.fillWidth: true
                onActivated: page.inspection.chooseRecovery(currentValue)
                Accessible.name: "Run to recover"
            }
            RowLayout {
                SplatButton {
                    text: "Inspect run"
                    enabled: page.inspection.state.recoveryRun !== ""
                    onClicked: page.inspection.action("inspectRecovery")
                }
                SplatButton {
                    text: "Recover publication"
                    enabled: page.inspection.state.recoveryRun !== "" && !page.vm.state.exclusive
                    onClicked: page.inspection.action("recover")
                }
                SplatButton {
                    text: "Cancel active run"
                    kind: "danger"
                    enabled: page.vm.state.progress.canCancel
                    onClicked: page.vm.cancel()
                }
            }
        }
    }
    GridLayout {
        Layout.fillWidth: true
        columns: page.width > 950 ? 3 : 2
        columnSpacing: 16
        rowSpacing: 16
        Repeater {
            model: page.inspection.state.health
            delegate: SplatCard {
                id: health
                required property var modelData
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.fillHeight: true
                implicitHeight: healthContent.implicitHeight + 48
                ColumnLayout {
                    id: healthContent
                    width: parent.width
                    spacing: 14
                    RowLayout {
                        SplatButton {
                            iconName: health.modelData.icon
                            kind: "ghost"
                            enabled: false
                            opacity: 1
                        }
                        SplatLabel {
                            text: health.modelData.title
                            font.pixelSize: Theme.section
                            font.weight: Font.DemiBold
                            Layout.fillWidth: true
                        }
                    }
                    SplatBadge {
                        text: health.modelData.status
                    }
                    SplatLabel {
                        text: health.modelData.detail
                        color: Theme.secondary
                        font.pixelSize: Theme.small
                        Layout.fillWidth: true
                        Layout.minimumHeight: 64
                    }
                    DetailsPanel {
                        visible: page.vm.state.mode === "Advanced"
                        Layout.fillWidth: true
                        padding: 0
                        title: "Exact evidence"
                        text: health.modelData.exact
                    }
                    SplatButton {
                        visible: health.modelData.title === "Trainer"
                        text: "Open trainer"
                        kind: "ghost"
                        onClicked: page.vm.navigate(4)
                    }
                }
            }
        }
    }
    SplatLabel {
        text: page.inspection.state.message
              || "Probes are explicit. Unknown capabilities remain unknown. No dependencies or models are installed automatically."
        color: Theme.muted
        font.pixelSize: Theme.small
        Layout.fillWidth: true
    }
    SplatCard {
        visible: page.vm.state.mode === "Advanced" && page.vm.state.hasProject
        Layout.fillWidth: true
        implicitHeight: storage.implicitHeight + 48
        RowLayout {
            id: storage
            width: parent.width
            spacing: 24
            ColumnLayout {
                Layout.fillWidth: true
                SplatLabel {
                    text: "Project storage"
                    font.pixelSize: Theme.section
                    font.weight: Font.DemiBold
                }
                SplatLabel {
                    text: "Preview exact eligible generated payloads before applying cleanup. Pins, current outputs and protected lineage remain explicit."
                    color: Theme.secondary
                    Layout.fillWidth: true
                }
            }
            SplatButton {
                text: "Preview cleanup"
                enabled: page.vm.state.canMutate
                onClicked: page.inspection.action("previewCleanup")
            }
        }
    }
    DetailsPanel {
        visible: page.vm.state.mode === "Advanced" || page.vm.state.unresolved
        Layout.fillWidth: true
        title: "Lifecycle / run details"
        text: page.inspection.state.details
    }
}

pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../theme"
import "../components"

ColumnLayout {
    id: page
    required property var vm
    readonly property var work: vm.workflow
    readonly property var runtime: work.state.capability
    readonly property bool ready: !!runtime.python_version
    readonly property var plan: work.state.plans.training || ({})
    spacing: 24
    SplatPageHeader {
        title: "Train"
        subtitle: "Turn a prepared dataset into a Gaussian scene."
        Layout.fillWidth: true
        SplatButton {
            text: "Plan"
            enabled: page.work.state.inputs.dataset !== "" && !page.vm.state.busy
            onClicked: page.work.action("planTraining")
        }
        SplatButton {
            text: "Run training"
            kind: "primary"
            iconName: "play"
            enabled: page.work.state.inputs.dataset !== "" && page.vm.state.canMutate
            onClicked: page.work.action("runTraining")
        }
    }
    SplatEmptyState {
        visible: page.work.state.choices.dataset.length <= 1
        Layout.fillWidth: true
        title: "Build on a prepared dataset"
        detail: "Prepare a selected reconstruction before training. Components remain separate jobs and scenes."
        iconName: "train"
        action: "Prepare a dataset"
        onActivated: page.vm.navigate(3)
    }
    GridLayout {
        Layout.fillWidth: true
        columns: page.width > 950 ? 2 : 1
        columnSpacing: 24
        rowSpacing: 24
        SplatCard {
            Layout.fillWidth: true
            Layout.preferredWidth: 3
            Layout.alignment: Qt.AlignTop
            implicitHeight: settings.implicitHeight + 48
            ColumnLayout {
                id: settings
                width: parent.width
                spacing: 16
                SplatLabel {
                    text: "Training setup"
                    font.pixelSize: Theme.section
                    font.weight: Font.DemiBold
                }
                SplatLabel {
                    text: "Published dataset"
                    font.pixelSize: Theme.small
                    color: Theme.secondary
                }
                RunPicker {
                    workflow: page.work
                    inputKind: "dataset"
                    Layout.fillWidth: true
                }
                SplatLabel {
                    text: "Densification strategy"
                    font.pixelSize: Theme.small
                    color: Theme.secondary
                }
                SplatComboBox {
                    model: page.work.state.strategyChoices
                    textRole: "label"
                    valueRole: "value"
                    enabledRole: "supported"
                    selectedValue: page.work.state.strategy
                    Layout.fillWidth: true
                    onActivated: page.work.setTraining("strategy", currentValue)
                    Accessible.name: "Training strategy"
                }
                SplatBanner {
                    visible: page.ready && page.runtime.features.indexOf(page.work.state.strategy)
                             < 0
                    Layout.fillWidth: true
                    text: "This runtime does not positively support the selected strategy. The choice is preserved; execution will refuse unsupported settings."
                }
                RowLayout {
                    spacing: 16
                    ColumnLayout {
                        Layout.fillWidth: true
                        SplatLabel {
                            text: "Maximum steps"
                            color: Theme.secondary
                            font.pixelSize: Theme.small
                        }
                        SplatTextField {
                            text: String(page.work.state.steps)
                            Layout.fillWidth: true
                            validator: IntValidator {
                                bottom: 1
                                top: 1000000
                            }
                            inputMethodHints: Qt.ImhDigitsOnly
                            onEditingFinished: page.work.setTraining("max_steps", text)
                            Accessible.name: "Maximum training steps"
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        SplatLabel {
                            text: "Data factor"
                            color: Theme.secondary
                            font.pixelSize: Theme.small
                        }
                        SplatTextField {
                            text: String(page.work.state.factor)
                            Layout.fillWidth: true
                            validator: IntValidator {
                                bottom: 1
                                top: 64
                            }
                            inputMethodHints: Qt.ImhDigitsOnly
                            onEditingFinished: page.work.setTraining("data_factor", text)
                            Accessible.name: "Training data factor"
                        }
                    }
                }
                RowLayout {
                    visible: page.work.state.strategy === "mcmc"
                    SplatLabel {
                        text: "MCMC Gaussian cap"
                        Layout.fillWidth: true
                        color: Theme.secondary
                    }
                    SplatTextField {
                        text: String(page.work.state.cap)
                        Layout.preferredWidth: 160
                        validator: IntValidator {
                            bottom: 4
                            top: 10000000
                        }
                        inputMethodHints: Qt.ImhDigitsOnly
                        onEditingFinished: page.work.setTraining("cap", text)
                        Accessible.name: "MCMC Gaussian cap"
                    }
                }
                SplatLabel {
                    text: "Settings apply to this run. No production quality preset has been adopted. Pose optimization and world normalization stay explicit."
                    color: Theme.muted
                    font.pixelSize: Theme.small
                    Layout.fillWidth: true
                }
            }
        }
        SplatCard {
            Layout.fillWidth: true
            Layout.preferredWidth: 2
            Layout.alignment: Qt.AlignTop
            implicitHeight: runtimeContent.implicitHeight + 48
            ColumnLayout {
                id: runtimeContent
                width: parent.width
                spacing: 16
                RowLayout {
                    SplatLabel {
                        text: "Trainer runtime"
                        font.pixelSize: Theme.section
                        font.weight: Font.DemiBold
                        Layout.fillWidth: true
                    }
                    SplatBadge {
                        text: page.ready ? "Ready" : "Not checked"
                    }
                }
                Repeater {
                    model: [["Python", "python_version"], ["Torch", "torch_version"], ["CUDA",
                                                                                       "cuda_runtime"],
                        ["GPU", "gpu_name"], ["gsplat", "gsplat_version"]]
                    delegate: RowLayout {
                        id: row
                        required property var modelData
                        SplatLabel {
                            text: row.modelData[0]
                            color: Theme.secondary
                            Layout.preferredWidth: 60
                        }
                        SplatLabel {
                            text: page.runtime[row.modelData[1]] || "Not checked"
                            Layout.fillWidth: true
                            horizontalAlignment: Text.AlignRight
                            font.weight: page.ready ? Font.DemiBold : Font.Normal
                            color: page.ready ? Theme.text : Theme.muted
                        }
                    }
                }
                Rectangle {
                    Layout.fillWidth: true
                    height: 1
                    color: Theme.border
                }
                SplatLabel {
                    text: page.vm.state.machine.trainer_python
                          || "Configure trainer Python in Settings."
                    font.family: Theme.mono
                    color: Theme.muted
                    font.pixelSize: Theme.caption
                    Layout.fillWidth: true
                    maximumLineCount: 2
                    elide: Text.ElideMiddle
                }
                SplatButton {
                    text: "Probe trainer runtime"
                    enabled: !page.vm.state.busy
                    Layout.fillWidth: true
                    onClicked: page.work.action("probeTrainer")
                }
                SplatLabel {
                    text: "An explicit functional probe verifies the actual runtime. Hardware presence alone is not readiness."
                    color: Theme.muted
                    font.pixelSize: Theme.small
                    Layout.fillWidth: true
                }
            }
        }
    }
    SplatBanner {
        visible: !!page.work.state.messages.training
        Layout.fillWidth: true
        text: page.work.state.messages.training || ""
        tone: Theme.muted
    }
    SplatBanner {
        visible: (page.plan.diagnostics || []).length > 0
        Layout.fillWidth: true
        text: (page.plan.diagnostics || []).join("\n")
    }
    SplatCard {
        Layout.fillWidth: true
        implicitHeight: resume.implicitHeight + 48
        ColumnLayout {
            id: resume
            width: parent.width
            spacing: 16
            RowLayout {
                SplatLabel {
                    text: "Continue from a checkpoint"
                    font.pixelSize: Theme.section
                    font.weight: Font.DemiBold
                    Layout.fillWidth: true
                }
                SplatBadge {
                    text: page.work.state.resumeReady ? "Compatible" : "Check required"
                }
            }
            SplatLabel {
                text: "Resume preserves the exact dataset, settings and runtime identity. A fresh start is never presented as a resume."
                color: Theme.secondary
                Layout.fillWidth: true
            }
            RowLayout {
                RunPicker {
                    workflow: page.work
                    inputKind: "checkpoint"
                    Layout.fillWidth: true
                }
                SplatButton {
                    text: "Check compatibility"
                    enabled: page.work.state.inputs.dataset !== ""
                             && page.work.state.inputs.checkpoint !== ""
                    onClicked: page.work.action("checkResume")
                }
                SplatButton {
                    text: "Resume"
                    enabled: page.work.state.resumeReady && page.vm.state.canMutate
                    onClicked: page.work.action("resumeTraining")
                }
            }
            SplatLabel {
                text: page.work.state.resumeReason
                color: page.work.state.resumeReady ? Theme.success : Theme.muted
                Layout.fillWidth: true
                font.pixelSize: Theme.small
            }
        }
    }
    RowLayout {
        visible: page.vm.state.mode === "Advanced"
        SplatButton {
            text: "Edit exact training settings"
            onClicked: page.work.editExact("training")
        }
        SplatButton {
            text: "Edit session runtime"
            onClicked: page.work.editExact("runtime")
        }
    }
    DetailsPanel {
        visible: page.vm.state.mode === "Advanced"
        Layout.fillWidth: true
        title: "Training plan / result evidence"
        text: page.work.state.details.training || ""
    }
    DetailsPanel {
        visible: page.vm.state.mode === "Advanced"
        Layout.fillWidth: true
        title: "Exact runtime identity"
        text: page.work.state.details.runtime || ""
    }
}

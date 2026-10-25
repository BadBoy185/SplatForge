pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../theme"
import "../components"

ColumnLayout {
    id: page
    required property var vm
    readonly property var work: vm.workflow
    readonly property var plan: work.state.plans.reconstruction || ({})
    spacing: 24
    SplatPageHeader {
        title: "Reconstruct"
        subtitle: "From individual captures to a coherent scene."
        Layout.fillWidth: true
        SplatButton {
            text: "Plan"
            enabled: page.work.state.requestAvailable && !page.vm.state.busy
            onClicked: page.work.action("planReconstruction")
        }
        SplatButton {
            text: "Run reconstruction"
            iconName: "play"
            kind: "primary"
            enabled: page.work.state.canReconstruct && page.vm.state.canMutate
            onClicked: page.work.action("runReconstruction")
        }
    }
    SplatBanner {
        Layout.fillWidth: true
        visible: !page.work.state.requestAvailable
        text: page.work.state.messages.reconstruction
              || "Open a project and add sources to configure reconstruction."
    }
    RowLayout {
        Layout.fillWidth: true
        spacing: 16
        SplatCard {
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            implicitHeight: 186
            ColumnLayout {
                anchors.fill: parent
                spacing: 12
                RowLayout {
                    SplatLabel {
                        text: "01 / FRAME PREPARATION"
                        color: Theme.muted
                        font.pixelSize: Theme.caption
                        font.letterSpacing: 1
                        Layout.fillWidth: true
                    }
                    SplatBadge {
                        text: page.vm.state.project.sourceCount > 0 ? "Configured" : "No sources"
                    }
                }
                SplatLabel {
                    text: page.work.state.frameSelection
                    font.pixelSize: Theme.section
                    font.weight: Font.DemiBold
                }
                SplatLabel {
                    text: page.vm.state.project.sourceCount ? page.vm.state.project.sourceCount
                                                              + " sources · bounded view preparation" :
                                                              "Add photos or video to begin"
                    color: Theme.secondary
                    Layout.fillWidth: true
                }
                SplatLabel {
                    text: page.plan.selected_views
                          || "Selected view count is known after preparation."
                    color: Theme.muted
                    font.pixelSize: Theme.small
                    Layout.fillWidth: true
                }
            }
        }
        SplatCard {
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            implicitHeight: 186
            ColumnLayout {
                anchors.fill: parent
                spacing: 12
                RowLayout {
                    SplatLabel {
                        text: "02 / FEATURES & MATCHING"
                        color: Theme.muted
                        font.pixelSize: Theme.caption
                        font.letterSpacing: 1
                        Layout.fillWidth: true
                    }
                    SplatBadge {
                        text: page.work.state.canReconstruct ? "Ready" : "Plan required"
                    }
                }
                SplatLabel {
                    text: page.work.state.extractor.replace("feature_extraction.", "").replace(/_/g,
                                                                                               " ").toUpperCase(
                              ) + " + " + page.work.state.matcher.replace("feature_matching.",
                                                                          "").replace(/_/g,
                                                                                      " ").toUpperCase(
                              )
                    font.pixelSize: Theme.section
                    font.weight: Font.DemiBold
                    Layout.fillWidth: true
                }
                SplatComboBox {
                    model: page.work.state.profiles
                    textRole: "label"
                    valueRole: "value"
                    selectedValue: page.work.state.profile
                    Layout.fillWidth: true
                    enabled: page.work.state.requestAvailable
                    onActivated: page.work.setReconstruction("profile", currentValue)
                    Accessible.name: "Feature and matching profile"
                }
                SplatLabel {
                    text: "The exact route is verified by Plan. No silent fallback."
                    color: Theme.muted
                    font.pixelSize: Theme.small
                    Layout.fillWidth: true
                }
            }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        SplatLabel {
            text: "Reconstruction method"
            font.pixelSize: Theme.section
            font.weight: Font.DemiBold
            Layout.fillWidth: true
        }
        SplatLabel {
            text: "YOUR EXPLICIT CHOICE"
            font.pixelSize: Theme.caption
            color: Theme.muted
            font.letterSpacing: 1
        }
    }
    RowLayout {
        Layout.fillWidth: true
        spacing: 16
        Repeater {
            model: [["global", "Global", "Solve the scene together",
                     "Estimate camera poses across the verified view graph."], ["incremental",
                                                                                "Incremental",
                                                                                "Build step by step",
                                                                                "Register cameras progressively with bundle adjustment."],
                ["hierarchical", "Hierarchical", "Reconstruct in clusters",
                 "Map overlapping clusters and use the native merge route."]]
            delegate: AbstractButton {
                id: method
                required property var modelData
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                implicitHeight: 196
                checked: page.work.state.mapper === modelData[0]
                enabled: page.work.state.requestAvailable
                hoverEnabled: true
                focusPolicy: Qt.StrongFocus
                onClicked: page.work.setReconstruction("mapper", modelData[0])
                Accessible.name: modelData[1] + " reconstruction"
                Accessible.description: modelData[3]
                background: Rectangle {
                    color: method.checked ? Theme.selection : method.down ? Theme.hover : method.hovered
                                                                            ? Theme.raised :
                                                                              Theme.surface
                    radius: Theme.cardRadius
                    border.color: method.checked || method.visualFocus ? Theme.accent :
                                                                         "transparent"
                    border.width: method.visualFocus ? 2 : 1
                    Behavior on color {
                        ColorAnimation {
                            duration: Theme.motion
                        }
                    }
                }
                contentItem: ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 20
                    spacing: 8
                    RowLayout {
                        SplatLabel {
                            text: method.modelData[1]
                            font.pixelSize: Theme.section
                            font.weight: Font.DemiBold
                            Layout.fillWidth: true
                        }
                        SplatBadge {
                            text: method.checked ? "Selected" : "Explicit route"
                            tone: method.checked ? Theme.accent : Theme.muted
                        }
                    }
                    SplatLabel {
                        text: method.modelData[2]
                        color: Theme.secondary
                        font.weight: Font.DemiBold
                        Layout.fillWidth: true
                    }
                    SplatLabel {
                        text: method.modelData[3]
                        color: Theme.muted
                        font.pixelSize: Theme.small
                        Layout.fillWidth: true
                    }
                    Item {
                        Layout.fillHeight: true
                    }
                    SplatLabel {
                        text: "Plan verifies installed backend support"
                        color: Theme.muted
                        font.pixelSize: Theme.caption
                        Layout.fillWidth: true
                    }
                }
            }
        }
    }
    SplatCard {
        Layout.fillWidth: true
        implicitHeight: pairingContent.implicitHeight + 48
        RowLayout {
            id: pairingContent
            width: parent.width
            spacing: 24
            ColumnLayout {
                Layout.fillWidth: true
                SplatLabel {
                    text: "Image pairing"
                    font.weight: Font.DemiBold
                }
                SplatLabel {
                    text: "Sequential connects views within clips. Exhaustive is a bounded reference route. Production multi-video retrieval remains pending."
                    color: Theme.secondary
                    font.pixelSize: Theme.small
                    Layout.fillWidth: true
                }
            }
            SplatComboBox {
                model: [
                    {
                        label: "Sequential",
                        value: "sequential"
                    },
                    {
                        label: "Exhaustive reference",
                        value: "exhaustive"
                    },
                    {
                        label: "Advanced configured",
                        value: "advanced"
                    }
                ]
                textRole: "label"
                valueRole: "value"
                currentIndex: page.work.state.pairing.endsWith("sequential") ? 0 :
                                                                               page.work.state.pairing.endsWith(
                                                                                   "exhaustive")
                                                                               ? 1 : 2
                enabled: page.work.state.requestAvailable
                onActivated: {
                    if (currentValue !== "advanced")
                        page.work.setReconstruction("pairing", currentValue);
                    else
                        page.work.editExact("reconstruction");
                }
                Accessible.name: "Pair selection"
            }
        }
    }
    SplatBanner {
        visible: !!page.work.state.messages.reconstruction
        Layout.fillWidth: true
        tone: page.work.state.canReconstruct ? Theme.success : Theme.muted
        text: page.work.state.messages.reconstruction || ""
    }
    SplatBanner {
        visible: (page.plan.validation_warnings || []).length > 0
        Layout.fillWidth: true
        text: (page.plan.validation_warnings || []).join("\n")
    }
    SplatLabel {
        visible: !!page.plan.cache
        text: (page.plan.cache || "") + " · " + (page.plan.pair_count || "")
        color: Theme.muted
        font.pixelSize: Theme.small
        Layout.fillWidth: true
    }
    DetailsPanel {
        visible: page.vm.state.mode === "Advanced"
        Layout.fillWidth: true
        title: "Advanced reconstruction evidence"
        text: page.work.state.details.reconstruction || ""
    }
    RowLayout {
        visible: page.vm.state.mode === "Advanced"
        SplatButton {
            text: "Edit exact settings"
            enabled: page.work.state.requestAvailable
            onClicked: page.work.editExact("reconstruction")
        }
        SplatButton {
            text: "Stage methods as project intent"
            enabled: page.work.state.requestAvailable && page.vm.state.canMutate
            onClicked: page.work.action("stageIntent")
        }
        SplatButton {
            text: "Project intent"
            kind: "ghost"
            enabled: page.vm.state.hasProject
            onClicked: page.work.editExact("intent")
        }
    }
    SplatCard {
        Layout.fillWidth: true
        implicitHeight: validationContent.implicitHeight + 48
        ColumnLayout {
            id: validationContent
            width: parent.width
            spacing: 16
            RowLayout {
                SplatLabel {
                    text: "Validate & select components"
                    font.pixelSize: Theme.section
                    font.weight: Font.DemiBold
                    Layout.fillWidth: true
                }
                SplatBadge {
                    text: (page.vm.state.project.validation || "not started").replace(/_/g, " ")
                }
            }
            SplatLabel {
                text: "Inspect the reconstruction evidence, then make an explicit component choice. Ambiguous results remain unselected."
                color: Theme.secondary
                Layout.fillWidth: true
            }
            RowLayout {
                RunPicker {
                    workflow: page.work
                    inputKind: "validation"
                    Layout.fillWidth: true
                }
                SplatButton {
                    text: "Inspect"
                    enabled: page.work.state.inputs.validation !== ""
                    onClicked: page.work.action("inspectValidation")
                }
            }
            SplatLabel {
                text: page.work.state.messages.validation || "No report inspected"
                color: Theme.secondary
                Layout.fillWidth: true
            }
            RowLayout {
                SplatButton {
                    text: "Request policy selection"
                    enabled: page.work.state.inputs.validation !== "" && page.vm.state.canMutate
                    onClicked: page.work.action("policySelection")
                }
                SplatButton {
                    text: "Choose components"
                    enabled: page.work.state.canSelect && page.vm.state.canMutate
                    onClicked: page.work.action("manualSelection")
                }
                SplatLabel {
                    text: page.work.state.messages.selection || ""
                    color: Theme.secondary
                    Layout.fillWidth: true
                }
            }
            DetailsPanel {
                visible: page.vm.state.mode === "Advanced"
                Layout.fillWidth: true
                title: "Validation report and measurements"
                text: page.work.state.details.validation || ""
            }
        }
    }
}

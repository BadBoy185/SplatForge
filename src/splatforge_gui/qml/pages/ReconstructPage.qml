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
    readonly property var state: work.state
    readonly property var plan: state.plans.reconstruction || ({})
    property bool expertOpen: false
    property bool pipelineChecking: false
    property string pipelineMessageBeforeCheck: ""
    spacing: 16

    function parseIntOr(text: string, fallback: int): int {
        const value = parseInt(text);
        return isNaN(value) ? fallback : value;
    }
    function parseFloatOr(text: string, fallback: real): real {
        const value = parseFloat(text);
        return isNaN(value) ? fallback : value;
    }
    function estimatedPairs(): string {
        const count = state.preparedInput.selectedCount || 0;
        if (state.pairingMode !== "exhaustive" || count < 2)
            return "";
        return Math.floor(count * (count - 1) / 2).toLocaleString(Qt.locale(), "f", 0) + " pairs";
    }
    function checkPipeline() {
        if (pipelineChecking)
            return;
        pipelineMessageBeforeCheck = state.messages.reconstruction || "";
        pipelineChecking = true;
        work.action("planReconstruction");
    }
    onStateChanged: {
        const message = state.messages.reconstruction || "";
        if (pipelineChecking && (state.canReconstruct || message !== pipelineMessageBeforeCheck))
            pipelineChecking = false;
    }

    SplatPageHeader {
        title: "Reconstruction"
        subtitle: "Build sparse reconstruction from one exact prepared image set."
        Layout.fillWidth: true
        SplatButton {
            objectName: "checkReconstructionPipeline"
            text: page.pipelineChecking ? "Checking…" : "Check pipeline"
            enabled: page.state.requestAvailable && page.state.hasPreparedInput
                     && !page.vm.state.busy && !page.pipelineChecking
            onClicked: page.checkPipeline()
        }
        SplatButton {
            objectName: "runReconstruction"
            text: "Run reconstruction"
            iconName: "play"
            kind: "primary"
            enabled: page.state.canReconstruct && page.vm.state.canMutate && !page.pipelineChecking
            onClicked: page.work.action("runReconstruction")
        }
    }

    SplatBanner {
        Layout.fillWidth: true
        visible: !page.state.requestAvailable
        text: page.state.messages.reconstruction
              || "Open a project with supported reconstruction settings."
    }

    SplatCard {
        Layout.fillWidth: true
        implicitHeight: inputContent.implicitHeight + 40
        ColumnLayout {
            id: inputContent
            anchors.fill: parent
            anchors.margins: 20
            spacing: 10
            RowLayout {
                Layout.fillWidth: true
                SplatLabel {
                    text: "01 / PREPARED INPUT"
                    color: Theme.muted
                    font.pixelSize: Theme.caption
                    font.letterSpacing: 1
                    Layout.fillWidth: true
                }
                SplatBadge {
                    text: page.state.hasPreparedInput ? "Exact published set" : "Required"
                    tone: page.state.hasPreparedInput ? Theme.accent : Theme.warning
                }
            }
            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    Layout.fillWidth: true
                    SplatLabel {
                        text: page.state.preparedInput.label || "Choose a prepared set"
                        font.pixelSize: Theme.section
                        font.weight: Font.DemiBold
                        Layout.fillWidth: true
                    }
                    SplatLabel {
                        text: page.state.preparedInput.selectedCount > 0
                              ? page.state.preparedInput.selectedCount + " reviewed selected frames"
                              : page.state.hasPreparedInput
                                ? "Exact selected-view run is locked for reconstruction"
                                : "Finish Prepare Data first. Reconstruction will not prepare frames again."
                        color: Theme.secondary
                        Layout.fillWidth: true
                    }
                }
                RunPicker {
                    objectName: "reconstructionPreparedRun"
                    workflow: page.work
                    inputKind: "views"
                    Layout.preferredWidth: 330
                    enabled: page.state.choices.views.length > 0 && !page.vm.state.busy
                             && !page.pipelineChecking
                }
                SplatButton {
                    text: "Materials"
                    kind: "ghost"
                    enabled: !page.pipelineChecking
                    onClicked: page.vm.navigate(1)
                }
            }
            SplatLabel {
                visible: !!page.state.preparedInput.runId
                text: "Run " + page.state.preparedInput.runId
                color: Theme.muted
                font.pixelSize: Theme.small
                wrapMode: Text.WrapAnywhere
                Layout.fillWidth: true
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 16

        SplatCard {
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            implicitHeight: featuresContent.implicitHeight + 40
            ColumnLayout {
                id: featuresContent
                anchors.fill: parent
                anchors.margins: 20
                spacing: 10
                SplatLabel { text: "02 / FEATURE EXTRACTION"; color: Theme.muted; font.pixelSize: Theme.caption; font.letterSpacing: 1 }
                SplatLabel { text: "Local features"; font.pixelSize: Theme.section; font.weight: Font.DemiBold }
                SplatComboBox {
                    objectName: "reconstructionExtractor"
                    model: page.state.extractorChoices
                    textRole: "label"
                    valueRole: "value"
                    selectedValue: page.state.extractorVariant
                    Layout.fillWidth: true
                    enabled: page.state.requestAvailable && !page.pipelineChecking
                    onActivated: page.work.setReconstruction("extractor", currentValue)
                    Accessible.name: "Feature extractor"
                }
                RowLayout {
                    Layout.fillWidth: true
                    SplatLabel { text: "Device"; color: Theme.secondary; Layout.fillWidth: true }
                    SplatComboBox {
                        objectName: "featureDevice"
                        model: [{label: "GPU", value: "gpu"}, {label: "CPU", value: "cpu"}]
                        textRole: "label"; valueRole: "value"
                        selectedValue: page.state.featureDevice
                        Layout.preferredWidth: 150
                        enabled: !page.pipelineChecking
                        onActivated: page.work.setReconstruction("feature_device", currentValue)
                    }
                }
                GridLayout {
                    columns: 2
                    Layout.fillWidth: true
                    SplatLabel { text: "Max features"; color: Theme.secondary }
                    SplatTextField {
                        objectName: "featureMaxFeatures"
                        text: String(page.state.featureMaxFeatures)
                        validator: IntValidator { bottom: 1; top: 100000 }
                        enabled: !page.pipelineChecking
                        onEditingFinished: page.work.setReconstructionInt("feature_max_features", page.parseIntOr(text, page.state.featureMaxFeatures))
                    }
                    SplatLabel { text: "Max image side"; color: Theme.secondary }
                    SplatTextField {
                        objectName: "featureMaxImageSize"
                        text: String(page.state.featureMaxImageSize)
                        validator: IntValidator { bottom: 32; top: 32768 }
                        enabled: !page.pipelineChecking
                        onEditingFinished: page.work.setReconstructionInt("feature_max_image_size", page.parseIntOr(text, page.state.featureMaxImageSize))
                    }
                }
            }
        }

        SplatCard {
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            implicitHeight: pairingContent.implicitHeight + 40
            ColumnLayout {
                id: pairingContent
                anchors.fill: parent
                anchors.margins: 20
                spacing: 10
                SplatLabel { text: "03 / IMAGE PAIRING"; color: Theme.muted; font.pixelSize: Theme.caption; font.letterSpacing: 1 }
                SplatLabel { text: "Pair candidate views"; font.pixelSize: Theme.section; font.weight: Font.DemiBold }
                SplatComboBox {
                    objectName: "reconstructionPairing"
                    model: [
                        {label: "Exhaustive", value: "exhaustive"},
                        {label: "Sequential", value: "sequential"},
                        {label: "Configured retrieval / hybrid", value: "advanced"}
                    ]
                    textRole: "label"; valueRole: "value"
                    selectedValue: page.state.pairingMode
                    Layout.fillWidth: true
                    enabled: !page.pipelineChecking
                    onActivated: {
                        if (currentValue === "advanced")
                            page.work.editExact("reconstruction");
                        else
                            page.work.setReconstruction("pairing", currentValue);
                    }
                }
                SplatLabel {
                    text: page.estimatedPairs() || (page.state.pairingMode === "sequential"
                          ? "Chronological neighbors within each video timeline"
                          : "Use Exact settings for an already configured retrieval route")
                    color: Theme.secondary
                    Layout.fillWidth: true
                }
                RowLayout {
                    visible: page.state.pairingMode === "sequential"
                    Layout.fillWidth: true
                    SplatLabel { text: "Forward neighbors"; color: Theme.secondary; Layout.fillWidth: true }
                    SplatTextField {
                        objectName: "pairForwardNeighbors"
                        text: String(page.state.pairForwardNeighbors)
                        validator: IntValidator { bottom: 1; top: 1000 }
                        Layout.preferredWidth: 110
                        enabled: !page.pipelineChecking
                        onEditingFinished: page.work.setReconstructionInt("pair_forward_neighbors", page.parseIntOr(text, page.state.pairForwardNeighbors))
                    }
                }
                SplatLabel {
                    visible: page.state.preparedInput.selectedCount > 0 && page.state.pairingMode === "exhaustive"
                    text: page.state.preparedInput.selectedCount + " views · default pair budget 100,000"
                    color: Theme.muted
                    font.pixelSize: Theme.small
                    Layout.fillWidth: true
                }
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 16

        SplatCard {
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            implicitHeight: matchingContent.implicitHeight + 40
            ColumnLayout {
                id: matchingContent
                anchors.fill: parent
                anchors.margins: 20
                spacing: 10
                SplatLabel { text: "04 / FEATURE MATCHING"; color: Theme.muted; font.pixelSize: Theme.caption; font.letterSpacing: 1 }
                SplatLabel { text: "Match descriptors"; font.pixelSize: Theme.section; font.weight: Font.DemiBold }
                SplatComboBox {
                    objectName: "reconstructionMatcher"
                    model: page.state.matcherChoices
                    textRole: "label"; valueRole: "value"
                    selectedValue: page.state.matcherVariant
                    Layout.fillWidth: true
                    enabled: !page.pipelineChecking
                    onActivated: page.work.setReconstruction("matcher", currentValue)
                    Accessible.name: "Feature matcher"
                }
                RowLayout {
                    Layout.fillWidth: true
                    SplatLabel { text: "Device"; color: Theme.secondary; Layout.fillWidth: true }
                    SplatComboBox {
                        objectName: "matchingDevice"
                        model: [{label: "GPU", value: "gpu"}, {label: "CPU", value: "cpu"}]
                        textRole: "label"; valueRole: "value"
                        selectedValue: page.state.matchingDevice
                        Layout.preferredWidth: 150
                        enabled: !page.pipelineChecking
                        onActivated: page.work.setReconstruction("matching_device", currentValue)
                    }
                }
                GridLayout {
                    columns: 2
                    Layout.fillWidth: true
                    SplatLabel { text: "Threads"; color: Theme.secondary }
                    SplatTextField {
                        text: String(page.state.matchingThreads)
                        validator: IntValidator { bottom: 1; top: 64 }
                        enabled: !page.pipelineChecking
                        onEditingFinished: page.work.setReconstructionInt("matching_threads", page.parseIntOr(text, page.state.matchingThreads))
                    }
                    SplatLabel { text: "Max matches / pair"; color: Theme.secondary }
                    SplatTextField {
                        text: String(page.state.matchingMaxMatches)
                        validator: IntValidator { bottom: 1; top: 100000 }
                        enabled: !page.pipelineChecking
                        onEditingFinished: page.work.setReconstructionInt("matching_max_matches", page.parseIntOr(text, page.state.matchingMaxMatches))
                    }
                }
            }
        }

        SplatCard {
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            implicitHeight: verifyContent.implicitHeight + 40
            ColumnLayout {
                id: verifyContent
                anchors.fill: parent
                anchors.margins: 20
                spacing: 10
                SplatLabel { text: "05 / GEOMETRIC VERIFICATION"; color: Theme.muted; font.pixelSize: Theme.caption; font.letterSpacing: 1 }
                SplatLabel { text: "Verify geometry"; font.pixelSize: Theme.section; font.weight: Font.DemiBold }
                GridLayout {
                    columns: 2
                    Layout.fillWidth: true
                    SplatLabel { text: "Minimum inliers"; color: Theme.secondary }
                    SplatTextField {
                        objectName: "verificationMinInliers"
                        text: String(page.state.verificationMinInliers)
                        validator: IntValidator { bottom: 8; top: 100000 }
                        enabled: !page.pipelineChecking
                        onEditingFinished: page.work.setReconstructionInt("verification_min_inliers", page.parseIntOr(text, page.state.verificationMinInliers))
                    }
                    SplatLabel { text: "Max error (px)"; color: Theme.secondary }
                    SplatTextField {
                        objectName: "verificationMaxError"
                        text: String(page.state.verificationMaxError)
                        validator: DoubleValidator { bottom: 0.01; top: 100; decimals: 4 }
                        enabled: !page.pipelineChecking
                        onEditingFinished: page.work.setReconstructionFloat("verification_max_error", page.parseFloatOr(text, page.state.verificationMaxError))
                    }
                }
                SplatLabel {
                    text: "Other RANSAC and camera-verification parameters remain available under Exact settings."
                    color: Theme.muted
                    font.pixelSize: Theme.small
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
            }
        }
    }

    SplatCard {
        Layout.fillWidth: true
        implicitHeight: mappingContent.implicitHeight + 40
        ColumnLayout {
            id: mappingContent
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            SplatLabel { text: "06 / MAPPING & BUNDLE ADJUSTMENT"; color: Theme.muted; font.pixelSize: Theme.caption; font.letterSpacing: 1 }
            RowLayout {
                Layout.fillWidth: true
                SplatComboBox {
                    objectName: "reconstructionMapper"
                    model: [
                        {label: "Incremental", value: "incremental"},
                        {label: "Global", value: "global"},
                        {label: "Hierarchical", value: "hierarchical"}
                    ]
                    textRole: "label"; valueRole: "value"
                    selectedValue: page.state.mapper
                    Layout.fillWidth: true
                    enabled: !page.pipelineChecking
                    onActivated: page.work.setReconstruction("mapper", currentValue)
                }
                SplatComboBox {
                    objectName: "calibrationPolicy"
                    model: [
                        {label: "Preserve priors", value: "preserve_priors"},
                        {label: "View-graph calibration", value: "view_graph"}
                    ]
                    textRole: "label"; valueRole: "value"
                    selectedValue: page.state.calibrationPolicy
                    Layout.fillWidth: true
                    enabled: !page.pipelineChecking
                    onActivated: page.work.setReconstruction("calibration", currentValue)
                }
            }
            GridLayout {
                columns: 4
                Layout.fillWidth: true
                SplatLabel { text: "Threads"; color: Theme.secondary }
                SplatTextField {
                    text: String(page.state.mappingThreads)
                    validator: IntValidator { bottom: 1; top: 64 }
                    enabled: !page.pipelineChecking
                    onEditingFinished: page.work.setReconstructionInt("mapping_threads", page.parseIntOr(text, page.state.mappingThreads))
                }
                SplatLabel { text: "Min matches"; color: Theme.secondary }
                SplatTextField {
                    text: String(page.state.mappingMinMatches)
                    validator: IntValidator { bottom: 8; top: 100000 }
                    enabled: !page.pipelineChecking
                             && (page.state.mapper !== "hierarchical" || page.state.mappingMinMatches > 0)
                    onEditingFinished: page.work.setReconstructionInt("mapping_min_matches", page.parseIntOr(text, page.state.mappingMinMatches))
                }
                SplatLabel { text: "Min model size"; color: Theme.secondary }
                SplatTextField {
                    text: String(page.state.mappingMinModelSize)
                    validator: IntValidator { bottom: 3; top: 100000 }
                    enabled: !page.pipelineChecking
                    onEditingFinished: page.work.setReconstructionInt("mapping_min_model_size", page.parseIntOr(text, page.state.mappingMinModelSize))
                }
                SplatLabel { text: "BA backend"; color: Theme.secondary; visible: page.state.mapper === "incremental" }
                SplatComboBox {
                    objectName: "baBackend"
                    visible: page.state.mapper === "incremental"
                    model: [{label: "Ceres", value: "ceres"}, {label: "Caspar", value: "caspar"}]
                    textRole: "label"; valueRole: "value"
                    selectedValue: page.state.baBackend
                    enabled: !page.pipelineChecking
                    onActivated: page.work.setReconstruction("ba_backend", currentValue)
                }
                SplatLabel { text: "GPU index"; color: Theme.secondary; visible: page.state.mapper === "incremental" && page.state.baBackend === "caspar" }
                SplatTextField {
                    visible: page.state.mapper === "incremental" && page.state.baBackend === "caspar"
                    text: String(page.state.baGpuIndex)
                    validator: IntValidator { bottom: 0; top: 31 }
                    enabled: !page.pipelineChecking
                    onEditingFinished: page.work.setReconstructionInt("ba_gpu_index", page.parseIntOr(text, page.state.baGpuIndex))
                }
            }
        }
    }

    SplatCard {
        Layout.fillWidth: true
        implicitHeight: planContent.implicitHeight + 40
        ColumnLayout {
            id: planContent
            anchors.fill: parent
            anchors.margins: 20
            spacing: 10
            RowLayout {
                Layout.fillWidth: true
                SplatLabel {
                    text: "PIPELINE CHECK"
                    color: Theme.muted
                    font.pixelSize: Theme.caption
                    font.letterSpacing: 1
                    Layout.fillWidth: true
                }
                SplatBadge {
                    text: page.pipelineChecking ? "Checking" : page.state.canReconstruct ? "Ready" : "Not checked"
                    tone: page.state.canReconstruct ? Theme.success : page.pipelineChecking ? Theme.accent : Theme.muted
                }
            }
            SplatLabel {
                text: page.pipelineChecking
                      ? "Checking COLMAP, feature extraction, matching, verification and mapper capability…"
                      : page.state.messages.reconstruction
                        || "Choose the exact settings above, then Check pipeline."
                color: page.state.canReconstruct ? Theme.text : Theme.secondary
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }
            SplatLabel {
                visible: (page.plan.validation_warnings || []).length > 0
                text: (page.plan.validation_warnings || []).join("\n")
                color: Theme.warning
                wrapMode: Text.WrapAnywhere
                Layout.fillWidth: true
            }
            SplatLabel {
                visible: !!page.plan.selected_views || !!page.plan.pair_count
                text: (page.plan.selected_views || "") + (page.plan.pair_count ? " · " + page.plan.pair_count : "")
                color: Theme.secondary
                Layout.fillWidth: true
            }
            RowLayout {
                Layout.fillWidth: true
                SplatButton {
                    text: page.expertOpen ? "Hide exact evidence" : "Show exact settings / evidence"
                    kind: "ghost"
                    enabled: page.state.requestAvailable && !page.pipelineChecking
                    onClicked: page.expertOpen = !page.expertOpen
                }
                SplatButton {
                    text: "Edit exact JSON"
                    kind: "ghost"
                    enabled: page.state.requestAvailable && !page.pipelineChecking
                    onClicked: page.work.editExact("reconstruction")
                }
                SplatButton {
                    text: "Save these methods as project defaults"
                    kind: "ghost"
                    enabled: page.state.requestAvailable && page.vm.state.canMutate && !page.pipelineChecking
                    onClicked: page.work.action("stageIntent")
                }
                Item { Layout.fillWidth: true }
                SplatButton {
                    text: page.pipelineChecking ? "Checking…" : "Check pipeline"
                    enabled: page.state.hasPreparedInput && !page.vm.state.busy && !page.pipelineChecking
                    onClicked: page.checkPipeline()
                }
                SplatButton {
                    text: "Run reconstruction"
                    iconName: "play"
                    kind: "primary"
                    enabled: page.state.canReconstruct && page.vm.state.canMutate && !page.pipelineChecking
                    onClicked: page.work.action("runReconstruction")
                }
            }
            DetailsPanel {
                visible: page.expertOpen
                Layout.fillWidth: true
                title: "Exact reconstruction request and capability evidence"
                text: page.state.details.reconstruction || "Check pipeline to populate runtime evidence."
            }
        }
    }

    SplatCard {
        visible: page.state.inputs.validation !== "" || !!page.state.messages.validation
        Layout.fillWidth: true
        implicitHeight: validationContent.implicitHeight + 40
        ColumnLayout {
            id: validationContent
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            RowLayout {
                Layout.fillWidth: true
                SplatLabel {
                    text: "07 / REVIEW RECONSTRUCTION"
                    color: Theme.muted
                    font.pixelSize: Theme.caption
                    font.letterSpacing: 1
                    Layout.fillWidth: true
                }
                SplatBadge { text: "Validation published" }
            }
            SplatLabel {
                text: "Inspect registration and component evidence, then choose the component(s) that may continue to Dataset preparation."
                color: Theme.secondary
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }
            RowLayout {
                Layout.fillWidth: true
                RunPicker { workflow: page.work; inputKind: "validation"; Layout.fillWidth: true }
                SplatButton {
                    text: "Inspect"
                    enabled: page.state.inputs.validation !== ""
                    onClicked: page.work.action("inspectValidation")
                }
            }
            SplatLabel {
                text: page.state.messages.validation || "Inspect the report to see registration metrics."
                color: Theme.secondary
                Layout.fillWidth: true
            }
            RowLayout {
                Layout.fillWidth: true
                SplatButton {
                    text: "Use policy recommendation"
                    enabled: page.state.inputs.validation !== "" && page.vm.state.canMutate
                    onClicked: page.work.action("policySelection")
                }
                SplatButton {
                    text: "Choose components manually"
                    enabled: page.state.canSelect && page.vm.state.canMutate
                    onClicked: page.work.action("manualSelection")
                }
                SplatLabel { text: page.state.messages.selection || ""; color: Theme.secondary; Layout.fillWidth: true }
            }
            DetailsPanel {
                visible: page.expertOpen && !!page.state.details.validation
                Layout.fillWidth: true
                title: "Validation evidence"
                text: page.state.details.validation || ""
            }
        }
    }
}

pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../theme"
import "../components"

Rectangle {
    id: page
    objectName: "preparePage"
    required property var vm
    readonly property var preparation: vm.prepare.state
    readonly property var summary: preparation.selectedSummary
    readonly property var plan: preparation.plan
    readonly property var review: vm.prepare.review.state
    readonly property var settings: vm.prepare.settings.state
    property bool technicalOpen: false
    property bool savedSettingsOpen: false
    color: Theme.background
    function bytesLabel(value: var): string {
        if (value === null || value === undefined)
            return "Unavailable";
        return value >= 1073741824 ? (value / 1073741824).toFixed(1) + " GiB" : Math.ceil(value / 1048576) + " MiB";
    }
    function showBlockingReason(): void {
        const flick = inspectorScroll.contentItem as Flickable;
        if (!flick)
            return;
        const y = flick.contentY + planBlockers.mapToItem(flick, Qt.point(0, 0)).y;
        flick.contentY = Math.max(0, Math.min(y - Theme.panelInset, flick.contentHeight - flick.height));
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.panelHeader + 4
            Layout.leftMargin: Theme.panelInset
            Layout.rightMargin: Theme.panelInset
            SplatButton {
                objectName: "returnToSources"
                text: "← Sources"
                kind: "ghost"
                enabled: !page.vm.state.busy && !page.preparation.busy && !page.vm.prepare.review.state.saving
                onClicked: page.vm.prepare.sources()
            }
            SplatLabel {
                text: "Prepare Data"
                font.pixelSize: Theme.panelHeading
                font.weight: Font.DemiBold
                Layout.fillWidth: true
            }
            SplatButton {
                objectName: "prepareRecovery"
                text: "Review interrupted work"
                visible: page.vm.state.unresolved
                onClicked: page.vm.prepare.recover()
            }
        }
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.border }
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0
            Rectangle {
                Layout.preferredWidth: page.width < 1100 ? 284 : 320
                Layout.fillHeight: true
                color: Theme.surface
                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0
                    SplatLabel {
                        objectName: "prepareInspectorHeading"
                        text: "Prepare your image set"
                        font.pixelSize: Theme.panelHeading
                        font.weight: Font.DemiBold
                        Layout.fillWidth: true
                        Layout.margins: Theme.panelInset
                    }
                    Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.border }
                    ScrollView {
                        id: inspectorScroll
                        objectName: "prepareInspectorScroll"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.minimumHeight: 0
                        clip: true
                        contentWidth: availableWidth
                        ScrollBar.vertical.policy: ScrollBar.AlwaysOn
                        ColumnLayout {
                            width: inspectorScroll.availableWidth
                            spacing: Theme.inspectorGap
                            Item { implicitHeight: 4 }
                            PrepareSettings {
                                api: page.vm.prepare.settings
                                Layout.fillWidth: true
                                Layout.leftMargin: 12; Layout.rightMargin: 12
                            }
                            SplatLabel {
                                objectName: "preparePlanCounts"
                                visible: page.plan.photoCount !== undefined
                                text: page.plan.photoCount + " photos · " + page.plan.videoCount + " videos\n"
                                      + page.plan.usedVideoCount + " videos with used footage\n"
                                      + (page.plan.candidateCount === null || page.plan.candidateCount === undefined ? "Candidate count unavailable" : "Up to " + page.plan.candidateCount + " candidates")
                                Layout.fillWidth: true
                                Layout.leftMargin: 12; Layout.rightMargin: 12
                            }
                            SplatLabel {
                                visible: page.plan.method !== undefined
                                text: "Saved selection\n" + (page.plan.method === "frame_selection.sharpest_interval" ? "Sharpest per interval" : "Fixed interval") + (page.plan.usedVideoCount > 0 ? "\nTarget frame rate: " + (page.plan.targetFps || "") + " fps" : "\nPhotos · no time sampling") + "\n\nCandidate storage bound: " + page.bytesLabel(page.plan.candidateBytes)
                                      + "\nPeak workspace bound: " + page.bytesLabel(page.plan.peakWorkspaceBytes)
                                color: Theme.secondary
                                Layout.fillWidth: true
                                Layout.leftMargin: 12; Layout.rightMargin: 12
                            }
                            SplatLabel {
                                id: planBlockers
                                objectName: "preparePlanBlockers"
                                visible: page.plan.blockers !== undefined && page.plan.blockers.length > 0
                                text: page.plan.blockers ? page.plan.blockers.join("\n") : ""
                                color: Theme.warning
                                Layout.fillWidth: true
                                Layout.leftMargin: 12; Layout.rightMargin: 12
                            }
                            SplatLabel {
                                objectName: "preparePlanNotes"
                                visible: page.plan.warnings !== undefined && page.plan.warnings.length > 0
                                text: page.plan.warnings ? page.plan.warnings.join("\n") : ""
                                color: Theme.secondary
                                Layout.fillWidth: true
                                Layout.leftMargin: 12; Layout.rightMargin: 12
                            }
                            SplatLabel {
                                text: page.preparation.message
                                visible: text !== "" && page.preparation.status !== "blocked"
                                color: Theme.secondary
                                Layout.fillWidth: true
                                Layout.leftMargin: 12; Layout.rightMargin: 12
                            }
                            SplatLabel {
                                objectName: "prepareError"
                                text: page.preparation.error
                                wrapMode: Text.WrapAnywhere
                                visible: text !== ""
                                color: Theme.danger
                                Layout.fillWidth: true
                                Layout.leftMargin: 12; Layout.rightMargin: 12
                            }
                            Rectangle { Layout.fillWidth: true; Layout.topMargin: 8; implicitHeight: 1; color: Theme.border }
                            SplatLabel {
                                text: "Published prepared sets"
                                font.weight: Font.DemiBold
                                Layout.fillWidth: true
                                Layout.leftMargin: 12; Layout.rightMargin: 12
                            }
                            SplatComboBox {
                                objectName: "prepareHistory"
                                model: page.preparation.history
                                textRole: "created"
                                valueRole: "runId"
                                selectedValue: page.preparation.selectedRun
                                enabled: !page.preparation.busy && !page.vm.prepare.review.state.saving && count > 0
                                Accessible.name: "Published prepared set"
                                Layout.fillWidth: true
                                Layout.leftMargin: 12; Layout.rightMargin: 12
                                onActivated: page.vm.prepare.selectRun(currentValue)
                            }
                            SplatButton {
                                objectName: "refreshPreparedHistory"
                                text: page.preparation.historyLoading ? "Loading saved sets…" : "Reload saved sets"
                                enabled: !page.preparation.historyLoading && !page.vm.state.busy
                                kind: "ghost"
                                Layout.leftMargin: 12; Layout.rightMargin: 12
                                onClicked: page.vm.prepare.refreshHistory()
                            }
                            SplatLabel {
                                text: "Saved output is historical. Check the saved plan before creating a new set."
                                color: Theme.secondary
                                Layout.fillWidth: true
                                Layout.leftMargin: 12; Layout.rightMargin: 12
                            }
                            SplatButton {
                                objectName: "togglePreparedRunSettings"
                                text: page.savedSettingsOpen ? "Hide published run settings" : "Published run settings…"
                                visible: !!page.summary.settingsText
                                kind: "ghost"
                                Layout.fillWidth: true
                                Layout.leftMargin: 12; Layout.rightMargin: 12
                                onClicked: page.savedSettingsOpen = !page.savedSettingsOpen
                            }
                            SplatLabel {
                                objectName: "preparedRunSettings"
                                text: page.summary.settingsText || ""
                                visible: page.savedSettingsOpen && text !== ""
                                color: Theme.secondary
                                font.pixelSize: Theme.small
                                Layout.fillWidth: true
                                Layout.leftMargin: 12; Layout.rightMargin: 12
                            }
                            SplatLabel {
                                objectName: "prepareResultCounts"
                                visible: page.summary.autoSelectedCount !== undefined
                                text: "Whole prepared set · " + page.summary.candidateCount + " candidates\nAutomatic: "
                                      + page.summary.autoSelectedCount + " selected · " + page.summary.autoRejectedCount + " rejected\n"
                                      + (page.summary.reviewCountsAvailable
                                         ? "Review: " + page.summary.selectedCount + " selected · " + page.summary.rejectedCount + " rejected\n"
                                         : page.vm.prepare.review.state.loading ? "Review membership loading…\n" : "Review membership unavailable\n")
                                      + (page.summary.measuredCount === null || page.summary.measuredCount === undefined ? "Quality measurements not recorded" : page.summary.measuredCount + " quality measured")
                                Layout.fillWidth: true
                                Layout.leftMargin: 12; Layout.rightMargin: 12
                            }
                            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.border }
                            SplatLabel {
                                text: "View scope"
                                font.weight: Font.DemiBold
                                Layout.fillWidth: true
                                Layout.leftMargin: 12; Layout.rightMargin: 12
                            }
                            SplatComboBox {
                                id: scopes
                                objectName: "preparedFrameScope"
                                model: page.review.scopes
                                textRole: "caption"
                                valueRole: "key"
                                selectedValue: page.review.scope
                                enabled: !page.review.saving && count > 0
                                Accessible.name: "Prepared frame view scope"
                                Accessible.description: "View only; intersects the Selected, Rejected or All tab"
                                Layout.fillWidth: true
                                Layout.leftMargin: 12; Layout.rightMargin: 12
                                ToolTip.visible: hovered
                                ToolTip.text: page.review.scopeLabel
                                onActivated: page.vm.prepare.review.setScope(currentValue)
                            }
                            SplatLabel {
                                text: "View only · source participation and frame decisions stay as saved."
                                color: Theme.secondary
                                font.pixelSize: Theme.small
                                Layout.fillWidth: true
                                Layout.leftMargin: 12; Layout.rightMargin: 12
                            }
                            SplatLabel {
                                objectName: "preparedScopeCounts"
                                visible: !!page.preparation.selectedRun
                                text: page.review.scopeCountsAvailable
                                    ? "Current scope · " + page.review.scopeCandidateTotal + " candidates\nAutomatic: "
                                      + page.review.scopeAutoSelectedTotal + " selected · "
                                      + (page.review.scopeCandidateTotal - page.review.scopeAutoSelectedTotal) + " rejected\nReview: "
                                      + page.review.scopeSelectedTotal + " selected · " + page.review.scopeRejectedTotal + " rejected\n"
                                      + page.review.scopeManualTotal + " manual decisions"
                                    : page.review.loading ? "Scope counts loading…" : "Scope counts unavailable"
                                Layout.fillWidth: true
                                Layout.leftMargin: 12; Layout.rightMargin: 12
                            }
                            SplatButton {
                                objectName: "togglePreparedTechnical"
                                visible: page.summary.runId !== undefined
                                text: page.technicalOpen ? "Hide prepared-set identifiers" : "Prepared-set identifiers…"
                                kind: "ghost"
                                Layout.fillWidth: true
                                Layout.leftMargin: 12; Layout.rightMargin: 12
                                onClicked: page.technicalOpen = !page.technicalOpen
                            }
                            SplatLabel {
                                visible: page.technicalOpen && page.summary.runId !== undefined
                                text: "Published run\n" + (page.summary.runId || "")
                                      + "\n\nSaved reconstruction input\n" + (page.review.effectiveRun || "Unavailable")
                                      + "\n" + page.review.manualTotal + " manual decisions in whole prepared set"
                                color: Theme.secondary
                                font.pixelSize: Theme.small
                                wrapMode: Text.WrapAnywhere
                                Layout.fillWidth: true
                                Layout.leftMargin: 12; Layout.rightMargin: 12
                            }
                            SplatLabel {
                                visible: page.summary.warnings !== undefined && page.summary.warnings.length > 0
                                text: page.summary.warnings ? page.summary.warnings.join("\n") : ""
                                color: Theme.warning
                                Layout.fillWidth: true
                                Layout.leftMargin: 12; Layout.rightMargin: 12
                            }
                            Item { implicitHeight: 12 }
                        }
                    }
                    Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.border }
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.margins: Theme.panelInset
                        spacing: Theme.spaceSmall
                        SplatButton {
                            objectName: "showPrepareBlockingReason"
                            text: "Preparation blocked · Show reason"
                            visible: page.preparation.status === "blocked"
                            kind: "ghost"
                            Layout.fillWidth: true
                            Accessible.name: "Preparation blocked. Show blocking reason"
                            onClicked: page.showBlockingReason()
                        }
                        SplatLabel {
                            objectName: "prepareSettingsError"
                            text: page.settings.error || ""
                            visible: text !== ""
                            color: Theme.danger
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                        SplatLabel {
                            objectName: "prepareSettingsSaveStatus"
                            text: "Next prepared set · " + (page.settings.supported === false ? "settings unavailable"
                                : page.settings.dirty ? "unsaved settings" : "settings saved")
                            color: page.settings.dirty ? Theme.warning : Theme.secondary
                            font.pixelSize: Theme.small
                            Layout.fillWidth: true
                            visible: !page.preparation.busy
                        }
                        RowLayout {
                            visible: !page.preparation.busy
                            Layout.fillWidth: true
                            spacing: Theme.spaceSmall
                            SplatButton {
                                objectName: "savePrepareSettings"
                                text: "Save settings"
                                enabled: page.settings.canSave === true
                                Layout.fillWidth: true
                                onClicked: page.vm.prepare.settings.save()
                            }
                            SplatButton {
                                objectName: "planPrepare"
                                text: page.preparation.status === "planning" ? "Checking…" : "Check plan"
                                enabled: page.preparation.canPlan
                                Layout.fillWidth: true
                                onClicked: page.vm.prepare.plan()
                            }
                        }
                        SplatButton {
                            objectName: "runPrepare"
                            text: page.preparation.status === "cancelled" || page.preparation.status === "failed" ? "Restart Prepare Data" : "Prepare Data"
                            kind: "primary"
                            enabled: page.preparation.canRun
                            visible: !page.preparation.busy
                            Layout.fillWidth: true
                            onClicked: page.vm.prepare.run()
                        }
                        ColumnLayout {
                            visible: page.preparation.busy
                            Layout.fillWidth: true
                            SplatLabel { text: page.vm.state.progress.phase; Layout.fillWidth: true }
                            ProgressBar {
                                Layout.fillWidth: true
                                indeterminate: page.vm.state.progress.fraction < 0
                                value: Math.max(0, page.vm.state.progress.fraction)
                            }
                            SplatLabel {
                                text: page.vm.state.progress.work + "\n" + page.vm.state.progress.elapsed + " " + page.vm.state.progress.eta
                                Layout.fillWidth: true
                                color: Theme.secondary
                            }
                            SplatButton {
                                objectName: "cancelPrepare"
                                text: page.vm.state.progress.cancelling ? "Cancelling…" : "Cancel"
                                enabled: page.vm.state.progress.canCancel && !page.vm.state.progress.cancelling
                                onClicked: page.vm.prepare.cancel()
                            }
                        }
                    }
                }
            }
            Rectangle { Layout.fillHeight: true; implicitWidth: 1; color: Theme.border }
            PreparedFrameReview {
                Layout.fillWidth: true
                Layout.fillHeight: true
                vm: page.vm
            }
        }
    }
}

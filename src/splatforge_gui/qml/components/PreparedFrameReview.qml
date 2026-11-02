pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../theme"

FocusScope {
    id: review
    required property var vm
    readonly property var presenter: vm.prepare.review
    readonly property var reviewState: presenter.state
    readonly property var viewed: reviewState.viewed
    readonly property bool single: reviewState.viewedId !== ""
    function decisionLabel(item: var): string {
        return item.decision === "exclude" ? "Manual · Excluded" : item.decision === "include" ? "Manual · Keep Anyway" : "Automatic";
    }
    Keys.onPressed: event => {
        if (event.isAutoRepeat || !reviewState.canEdit || !single || event.modifiers !== Qt.NoModifier)
            return;
        if (event.key === Qt.Key_Left) presenter.step(-1);
        else if (event.key === Qt.Key_Right) presenter.step(1);
        else if (event.key === Qt.Key_Escape) presenter.close();
        else return;
        event.accepted = true;
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: 8
        RowLayout {
            Layout.fillWidth: true
            Layout.margins: 12
            SplatLabel { text: "Prepared frames"; font.pixelSize: Theme.panelHeading; Layout.fillWidth: true }
            Repeater {
                model: [{value: "selected", label: "Selected"}, {value: "rejected", label: "Rejected"}, {value: "all", label: "All"}]
                delegate: SplatButton {
                    required property var modelData
                    objectName: "reviewFilter_" + modelData.value
                    text: modelData.label
                    kind: review.reviewState.filter === modelData.value ? "primary" : "ghost"
                    enabled: !review.reviewState.saving
                    onClicked: review.presenter.setFilter(modelData.value)
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 12; Layout.rightMargin: 12
            SplatLabel {
                objectName: "frameBatchScope"
                text: review.reviewState.selectedCount + " selected on this page · " + review.reviewState.scopeLabel
                Layout.fillWidth: true
                color: Theme.secondary
            }
            SplatButton { text: "Select page"; enabled: review.reviewState.canEdit; kind: "ghost"; onClicked: review.presenter.selectPage() }
            SplatButton { text: "Clear"; enabled: review.reviewState.canEdit && review.reviewState.selectedCount > 0; kind: "ghost"; onClicked: review.presenter.clearSelection() }
            SplatButton {
                objectName: "batchExcludeFrames"
                iconName: "exclude"; Accessible.name: "Exclude selected frames on this page"
                enabled: review.reviewState.canEdit && review.reviewState.selectedCount > 0
                onClicked: review.presenter.applyBatch("exclude")
            }
            SplatButton {
                objectName: "batchKeepFrames"
                iconName: "check"; Accessible.name: "Keep selected frames anyway on this page"
                enabled: review.reviewState.canEdit && review.reviewState.selectedCount > 0
                onClicked: review.presenter.applyBatch("include")
            }
            SplatButton {
                objectName: "batchResetFrames"
                iconName: "refresh"; Accessible.name: "Reset selected frames to automatic on this page"
                enabled: review.reviewState.canEdit && review.reviewState.selectedCount > 0
                onClicked: review.presenter.applyBatch("automatic")
            }
        }
        SplatLabel {
            Layout.fillWidth: true
            Layout.leftMargin: 12; Layout.rightMargin: 12
            visible: text !== ""
            text: review.reviewState.error || review.reviewState.message
            color: review.reviewState.error ? Theme.danger : Theme.secondary
            wrapMode: Text.WrapAnywhere
        }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            GridView {
                id: frames
                objectName: "preparedFramesGrid"
                anchors.fill: parent
                anchors.leftMargin: 12; anchors.rightMargin: 12
                clip: true
                visible: !review.single && !review.reviewState.loading && count > 0
                model: review.visible ? review.vm.media.gallery : null
                cellWidth: width / Math.max(1, Math.floor(width / 240))
                cellHeight: cellWidth * 0.7 + 76
                delegate: Item {
                    id: tile
                    required property string viewId
                    required property string caption
                    required property string imageUrl
                    required property string previewStatus
                    readonly property var evidence: review.reviewState.items[viewId] || ({})
                    width: frames.cellWidth - 10
                    height: frames.cellHeight - 8
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 4
                        Button {
                            id: viewButton
                            objectName: "viewFrame_" + tile.viewId
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            padding: 2
                            enabled: review.reviewState.canEdit
                            Accessible.name: "View " + tile.caption
                            background: Rectangle {
                                color: Theme.surface
                                border.width: viewButton.visualFocus ? 2 : 0
                                border.color: Theme.accent
                            }
                            contentItem: Item {
                                Image {
                                    anchors.fill: parent
                                    source: tile.imageUrl
                                    sourceSize: Qt.size(320, 240)
                                    fillMode: Image.PreserveAspectFit
                                    cache: false
                                }
                                SplatLabel {
                                    anchors.centerIn: parent
                                    visible: tile.previewStatus !== "Ready"
                                    text: tile.previewStatus
                                    color: Theme.secondary
                                }
                                Rectangle {
                                    anchors.bottom: parent.bottom
                                    width: parent.width
                                    height: 24
                                    visible: tile.evidence.included === false
                                    color: Theme.surface
                                    SplatLabel { anchors.centerIn: parent; text: "Excluded"; font.pixelSize: Theme.small }
                                }
                            }
                            onClicked: { review.forceActiveFocus(); review.presenter.view(tile.viewId); }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            SplatCheckBox {
                                objectName: "selectFrame_" + tile.viewId
                                checked: review.reviewState.selectedIds.indexOf(tile.viewId) >= 0
                                enabled: review.reviewState.canEdit
                                Accessible.name: "Select " + tile.caption + " for page batch"
                                onClicked: review.presenter.select(tile.viewId, checked)
                            }
                            SplatLabel { text: tile.caption; font.pixelSize: Theme.small; elide: Text.ElideMiddle; wrapMode: Text.NoWrap; Layout.fillWidth: true }
                            SplatButton {
                                objectName: "toggleFrame_" + tile.viewId
                                iconName: tile.evidence.included ? "exclude" : "check"
                                Accessible.name: tile.evidence.included ? "Exclude " + tile.caption : "Keep " + tile.caption + " anyway"
                                enabled: review.reviewState.canEdit
                                onClicked: review.presenter.applyFrame(tile.viewId, tile.evidence.included ? "exclude" : "include")
                            }
                            SplatButton {
                                iconName: "refresh"; Accessible.name: "Reset " + tile.caption + " to automatic"
                                enabled: review.reviewState.canEdit && tile.evidence.decision !== "automatic"
                                onClicked: review.presenter.applyFrame(tile.viewId, "automatic")
                            }
                        }
                        SplatLabel {
                            text: review.decisionLabel(tile.evidence) + " · Auto " + (tile.evidence.autoSelected ? "selected" : "rejected")
                            color: Theme.secondary; font.pixelSize: Theme.small
                            elide: Text.ElideRight; wrapMode: Text.NoWrap; Layout.fillWidth: true
                        }
                        SplatLabel {
                            text: tile.evidence.autoReason || ""
                            color: Theme.secondary; font.pixelSize: Theme.small
                            elide: Text.ElideRight; wrapMode: Text.NoWrap; Layout.fillWidth: true
                        }
                    }
                }
                ScrollBar.vertical: ScrollBar {}
            }
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                visible: review.single && !review.reviewState.loading
                RowLayout {
                    Layout.fillWidth: true
                    SplatButton { text: "Grid"; iconName: "close"; enabled: !review.reviewState.saving; onClicked: review.presenter.close() }
                    SplatLabel { text: review.viewed.caption || ""; elide: Text.ElideMiddle; Layout.fillWidth: true }
                    SplatButton { text: "Previous"; enabled: review.reviewState.canEdit && !!review.viewed.previousId; onClicked: review.presenter.step(-1) }
                    SplatButton { text: "Next"; enabled: review.reviewState.canEdit && !!review.viewed.nextId; onClicked: review.presenter.step(1) }
                }
                GridLayout {
                    id: singleContent
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    columns: review.width >= 900 ? 2 : 1
                    columnSpacing: Theme.inspectorGap
                    rowSpacing: Theme.inspectorGap
                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.minimumHeight: 120
                        PhotoViewport { anchors.fill: parent; imageSource: review.vm.media.state.largeImage }
                        SplatLabel {
                            anchors.centerIn: parent
                            visible: review.vm.media.state.previewStatus !== "Ready"
                            text: review.vm.media.state.previewStatus
                            color: Theme.secondary
                        }
                    }
                    PreparedFrameProvenance {
                        frame: review.viewed
                        Layout.fillWidth: singleContent.columns === 1
                        Layout.fillHeight: true
                        Layout.preferredWidth: singleContent.columns === 2 ? 280 : -1
                        Layout.minimumHeight: 150
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    SplatLabel { text: "Viewed image · page batch stays independent"; color: Theme.secondary; Layout.fillWidth: true }
                    SplatButton {
                        objectName: "previewExcludeFrame"
                        iconName: "exclude"; Accessible.name: "Exclude viewed frame and advance"
                        enabled: review.reviewState.canEditViewed && review.viewed.included === true
                        onClicked: review.presenter.applyFrame(review.reviewState.viewedId, "exclude")
                    }
                    SplatButton {
                        objectName: "previewKeepFrame"
                        iconName: "check"; Accessible.name: "Keep viewed frame anyway"
                        enabled: review.reviewState.canEditViewed && review.viewed.included === false
                        onClicked: review.presenter.applyFrame(review.reviewState.viewedId, "include")
                    }
                    SplatButton {
                        objectName: "previewResetFrame"
                        iconName: "refresh"; Accessible.name: "Reset viewed frame to automatic"
                        enabled: review.reviewState.canEditViewed && review.viewed.decision !== "automatic"
                        onClicked: review.presenter.applyFrame(review.reviewState.viewedId, "automatic")
                    }
                }
            }
            SplatLabel {
                objectName: "frameReviewEmptyState"
                anchors.centerIn: parent
                width: Math.min(420, parent.width - 32)
                horizontalAlignment: Text.AlignHCenter
                text: review.reviewState.error ? "Prepared frames unavailable.\nReload saved sets to retry." : review.reviewState.loading ? "Loading prepared frames…" : review.reviewState.saving ? "Saving frame decisions…" : review.vm.prepare.state.busy ? "Preparing your image set…" : review.vm.prepare.state.selectedRun ? (review.reviewState.scopeCandidateTotal === 0 ? "No prepared candidates in this scope.\n" : "No " + review.reviewState.filter + " frames in this scope.\n") + review.reviewState.scopeLabel : "No available prepared sets.\nCheck the saved plan, then prepare your data."
                visible: review.reviewState.loading || (!review.single && frames.count === 0)
                color: Theme.secondary
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.margins: 12
            SplatLabel {
                text: review.reviewState.count ? (review.reviewState.offset + 1) + "–" + (review.reviewState.offset + review.reviewState.count) + " of " + review.reviewState.total + " · " + review.reviewState.filter + " in current scope" : "Up to 100 frames per page · current scope"
                color: Theme.secondary; Layout.fillWidth: true
            }
            SplatButton { text: "Previous page"; enabled: review.reviewState.canPrevious; onClicked: review.presenter.previousPage() }
            SplatButton { text: "Next page"; enabled: review.reviewState.canNext; onClicked: review.presenter.nextPage() }
            SplatButton {
                objectName: "continueToReconstruction"
                text: "Continue to Reconstruction →"
                kind: "primary"
                visible: review.reviewState.effectiveRun !== "" && review.reviewState.selectedTotal > 0
                enabled: review.reviewState.canEdit && !review.reviewState.saving
                onClicked: {
                    review.vm.workflow.usePreparedRun(review.reviewState.effectiveRun,
                                                      review.reviewState.selectedTotal);
                    review.vm.navigate(2);
                }
            }
        }
    }
}

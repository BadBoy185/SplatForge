pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../theme"
import "../components"

SplatDialog {
    id: dialog
    required property var inspection
    readonly property var plan: inspection.state.cleanup
    title: "Review exact cleanup candidates"
    width: Math.min(900, Overlay.overlay.width - 64)
    height: Math.min(700, Overlay.overlay.height - 64)
    onOpened: confirmation.checked = false
    ColumnLayout {
        anchors.fill: parent
        spacing: 16
        SplatBanner {
            Layout.fillWidth: true
            text: (dialog.plan.candidates || []).length + " artifacts · " + (
                      dialog.plan.total_bytes || 0)
                  + " exact bytes. Only the listed generated payloads will be removed."
        }
        ListView {
            id: candidates
            Layout.fillWidth: true
            Layout.fillHeight: true
            model: dialog.plan.candidates || []
            clip: true
            spacing: 8
            delegate: SplatCard {
                id: candidate
                required property var modelData
                width: candidates.width
                padding: 16
                implicitHeight: candidateContent.implicitHeight + 32
                ColumnLayout {
                    id: candidateContent
                    width: parent.width
                    spacing: 8
                    SplatLabel {
                        text: candidate.modelData.artifact_type
                        font.weight: Font.DemiBold
                    }
                    SplatLabel {
                        text: candidate.modelData.artifact_id
                        font.family: Theme.mono
                        font.pixelSize: Theme.small
                        color: Theme.secondary
                    }
                    SplatLabel {
                        text: candidate.modelData.payloads.map(p => p.path + " · " + p.size
                                                                    + " bytes").join("\n")
                        font.family: Theme.mono
                        font.pixelSize: Theme.small
                        Layout.fillWidth: true
                        color: Theme.secondary
                    }
                }
            }
            SplatLabel {
                anchors.centerIn: parent
                visible: candidates.count === 0
                text: "No eligible generated payloads"
                color: Theme.muted
            }
            ScrollBar.vertical: ScrollBar {}
        }
        DetailsPanel {
            Layout.fillWidth: true
            padding: 0
            title: "Protected artifacts and preview digest"
            text: (dialog.plan.digest || "") + "\n\n" + (dialog.plan.protected_artifact_ids || []).join(
                      "\n")
        }
        SplatCheckBox {
            id: confirmation
            text: "Remove these exact generated payloads"
            enabled: candidates.count > 0
        }
        RowLayout {
            Layout.alignment: Qt.AlignRight
            SplatButton {
                text: "Cancel"
                kind: "ghost"
                onClicked: dialog.close()
            }
            SplatButton {
                text: "Apply cleanup"
                kind: "danger"
                enabled: confirmation.checked && candidates.count > 0
                onClicked: {
                    dialog.inspection.applyCleanup(dialog.plan.digest, confirmation.checked);
                    dialog.close();
                }
            }
        }
    }
}

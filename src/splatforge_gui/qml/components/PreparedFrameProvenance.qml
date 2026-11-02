pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: panel
    required property var frame
    readonly property var evidence: frame.provenance || ({})
    readonly property string viewedIdentity: frame.viewId || ""
    property bool technicalOpen: false
    onViewedIdentityChanged: {
        technicalOpen = false;
        if (scroll.ScrollBar.vertical)
            scroll.ScrollBar.vertical.position = 0;
    }
    color: Theme.surface
    ScrollView {
        id: scroll
        objectName: "frameProvenanceScroll"
        anchors.fill: parent
        contentWidth: availableWidth
        clip: true
        ScrollBar.vertical.objectName: "frameProvenanceScrollbar"
        ScrollBar.vertical.policy: ScrollBar.AlwaysOn
        ColumnLayout {
            width: scroll.availableWidth - 2 * Theme.panelInset
            x: Theme.panelInset
            spacing: Theme.inspectorGap
            SplatLabel {
                text: "Image provenance"
                font.weight: Font.DemiBold
                topPadding: Theme.panelInset
                Layout.fillWidth: true
            }
            SplatLabel {
                objectName: "frameEffectiveStatus"
                text: "Effective: " + (panel.frame.included ? "Selected" : "Rejected") + " · Manual: " + (panel.frame.decision === "include" ? "Keep Anyway" : panel.frame.decision === "exclude" ? "Excluded" : "No override")
                wrapMode: Text.WrapAnywhere
                Layout.fillWidth: true
            }
            SplatLabel {
                objectName: "frameAutomaticStatus"
                text: "Automatic: " + (panel.frame.autoSelected ? "Selected" : "Rejected") + " · " + (panel.frame.autoReason || "Reason not recorded")
                color: Theme.secondary
                wrapMode: Text.WrapAnywhere
                Layout.fillWidth: true
            }
            SplatLabel {
                objectName: "frameProvenanceMissing"
                visible: !panel.evidence.sourceName
                text: "Source provenance was not recorded for this frame."
                color: Theme.secondary
                Layout.fillWidth: true
            }
            Repeater {
                model: panel.evidence.sourceName ? [
                    {label: "Original source", value: panel.evidence.sourceName},
                    {label: "Type", value: panel.evidence.mediaType === "video" ? "Video" : "Photo"},
                    {label: "Original source time", value: panel.evidence.originalTime},
                    {label: "Recorded automatic score", value: panel.evidence.automaticScore},
                    {label: "Prepared dimensions", value: panel.evidence.dimensions},
                    {label: "Captured device", value: panel.evidence.device},
                    {label: "Current group", value: panel.evidence.group},
                    {label: "Locator at preparation", value: panel.evidence.pathAtPreparation},
                    {label: "Current inventory locator", value: panel.evidence.currentLocator},
                    {label: "Current inventory identity", value: panel.evidence.currentSourceState},
                    {label: "Last recorded source check", value: panel.evidence.sourceCheck}
                ] : []
                delegate: ColumnLayout {
                    id: field
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 2
                    SplatLabel {
                        text: field.modelData.label
                        color: Theme.secondary
                        font.pixelSize: Theme.small
                        Layout.fillWidth: true
                    }
                    TextArea {
                        text: field.modelData.value || "Not recorded"
                        readOnly: true
                        selectByMouse: true
                        wrapMode: TextEdit.WrapAnywhere
                        textFormat: TextEdit.PlainText
                        color: Theme.text
                        font.family: Theme.font
                        font.pixelSize: Theme.body
                        padding: 0
                        background: null
                        Layout.fillWidth: true
                        implicitHeight: contentHeight
                    }
                }
            }
            SplatLabel {
                visible: !!panel.evidence.sourceName
                text: "Browsing prepared images does not recheck original file availability."
                color: Theme.secondary
                font.pixelSize: Theme.small
                Layout.fillWidth: true
            }
            SplatButton {
                objectName: "toggleFrameTechnical"
                text: panel.technicalOpen ? "Hide technical details" : "Technical details…"
                kind: "ghost"
                Layout.fillWidth: true
                onClicked: panel.technicalOpen = !panel.technicalOpen
            }
            TextArea {
                visible: panel.technicalOpen
                text: "View UUID: " + (panel.frame.viewId || "") + "\n" + (panel.evidence.technical || "Source technical details not recorded")
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.WrapAnywhere
                textFormat: TextEdit.PlainText
                color: Theme.secondary
                font.family: Theme.font
                font.pixelSize: Theme.small
                padding: 0
                background: null
                Layout.fillWidth: true
                implicitHeight: contentHeight
            }
            Item { implicitHeight: Theme.panelInset }
        }
    }
}

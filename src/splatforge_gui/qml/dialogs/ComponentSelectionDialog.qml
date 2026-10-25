pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../theme"
import "../components"

SplatDialog {
    id: dialog
    required property var selection
    title: "Select reconstruction components"
    width: Math.min(920, Overlay.overlay.width - 64)
    height: Math.min(740, Overlay.overlay.height - 64)
    onOpened: confirmation.checked = false
    ColumnLayout {
        anchors.fill: parent
        spacing: 16
        SplatBanner {
            Layout.fillWidth: true
            text: dialog.selection.state.count
                  + " selected. Components use separate coordinate systems and produce separate datasets/scenes."
            tone: Theme.accent
        }
        ListView {
            id: components
            Layout.fillWidth: true
            Layout.fillHeight: true
            model: dialog.selection.state.components
            spacing: 8
            clip: true
            delegate: ItemDelegate {
                id: component
                required property var modelData
                width: components.width
                height: contentItem.implicitHeight + 32
                padding: 16
                checked: dialog.selection.state.selected.indexOf(modelData.id) >= 0
                onClicked: {
                    dialog.selection.toggleComponent(modelData.id);
                    confirmation.checked = false;
                }
                Accessible.name: modelData.title + " " + modelData.status + " " + modelData.views
                background: Rectangle {
                    radius: Theme.radius
                    color: component.checked ? Theme.selection : Theme.raised
                    border.color: component.visualFocus || component.checked ? Theme.accent :
                                                                               "transparent"
                    border.width: component.visualFocus ? 2 : 1
                }
                contentItem: ColumnLayout {
                    spacing: 8
                    RowLayout {
                        SplatLabel {
                            text: component.modelData.title
                            font.weight: Font.DemiBold
                            Layout.fillWidth: true
                        }
                        SplatLabel {
                            text: component.modelData.views
                            color: Theme.secondary
                        }
                        SplatBadge {
                            text: component.modelData.status
                        }
                    }
                    SplatLabel {
                        text: component.modelData.coverage.join("\n")
                        color: Theme.secondary
                        font.pixelSize: Theme.small
                        Layout.fillWidth: true
                    }
                    SplatLabel {
                        text: component.modelData.issues.join("\n")
                        color: Theme.warning
                        font.pixelSize: Theme.small
                        Layout.fillWidth: true
                        visible: text !== ""
                    }
                }
            }
            ScrollBar.vertical: ScrollBar {}
        }
        ListView {
            id: issues
            visible: count > 0
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(contentHeight, 140)
            model: dialog.selection.state.issues
            clip: true
            delegate: SplatCheckBox {
                id: issue
                required property var modelData
                width: issues.width
                text: "FAIL " + modelData.id + " · " + modelData.scope + "\n" + modelData.message
                checked: dialog.selection.state.checked.indexOf(modelData.id) >= 0
                onClicked: {
                    dialog.selection.toggleIssue(modelData.id);
                    confirmation.checked = false;
                }
                contentItem: SplatLabel {
                    text: issue.text
                    leftPadding: issue.indicator.width + 8
                    color: Theme.warning
                    font.pixelSize: Theme.small
                }
            }
        }
        SplatTextField {
            visible: dialog.selection.state.issues.length > 0
            Layout.fillWidth: true
            placeholderText: "Reason for these exact failure overrides"
            text: dialog.selection.state.reason
            onTextEdited: {
                dialog.selection.setReason(text);
                confirmation.checked = false;
            }
            Accessible.name: "Failure override reason"
        }
        SplatCheckBox {
            id: confirmation
            visible: dialog.selection.state.needsConfirmation
            text: "Confirm publication with these exact issue IDs and reason"
            palette.windowText: Theme.text
            Accessible.name: text
        }
        RowLayout {
            Layout.alignment: Qt.AlignRight
            SplatButton {
                text: "Cancel"
                kind: "ghost"
                onClicked: dialog.close()
            }
            SplatButton {
                text: "Publish selection"
                kind: "primary"
                enabled: dialog.selection.state.valid && (!dialog.selection.state.needsConfirmation
                                                          || confirmation.checked)
                onClicked: {
                    if (dialog.selection.confirm(confirmation.checked))
                        dialog.close();
                }
            }
        }
    }
}

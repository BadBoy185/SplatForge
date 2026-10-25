pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../theme"
import "../components"

SplatDialog {
    id: dialog
    required property var editor
    title: editor.state.title
    width: Math.min(850, Overlay.overlay.width - 64)
    height: Math.min(720, Overlay.overlay.height - 64)
    onOpened: {
        jsonText.text = editor.state.text;
        jsonText.forceActiveFocus();
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: 16
        SplatLabel {
            text: "Exact typed settings · validate before applying. Comments are not accepted."
            color: Theme.secondary
            Layout.fillWidth: true
        }
        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            TextArea {
                id: jsonText
                text: dialog.editor.state.text
                color: Theme.text
                selectionColor: Theme.selection
                selectedTextColor: Theme.text
                font.family: Theme.mono
                font.pixelSize: 13
                selectByMouse: true
                wrapMode: TextEdit.Wrap
                background: Rectangle {
                    color: Theme.background
                    radius: Theme.radius
                }
                onTextChanged: {
                    if (text !== dialog.editor.state.text)
                        dialog.editor.setText(text);
                }
                Accessible.name: "Exact settings JSON"
            }
        }
        SplatLabel {
            text: dialog.editor.state.valid ? "Valid settings" : dialog.editor.state.errors.map(e
                                                                                                => e.path
                                                                                                   + ": " + e.message).join(
                                                  "\n") || "Validate the current text before applying."
            color: dialog.editor.state.valid ? Theme.success : Theme.warning
            Layout.fillWidth: true
            maximumLineCount: 5
            elide: Text.ElideRight
            font.pixelSize: Theme.small
        }
        RowLayout {
            SplatButton {
                text: "Restore defaults"
                visible: dialog.editor.state.hasDefaults
                onClicked: {
                    dialog.editor.restore();
                    jsonText.text = dialog.editor.state.text;
                }
            }
            Item {
                Layout.fillWidth: true
            }
            SplatButton {
                text: "Cancel"
                kind: "ghost"
                onClicked: dialog.close()
            }
            SplatButton {
                text: "Validate"
                onClicked: dialog.editor.validate()
            }
            SplatButton {
                text: "Apply settings"
                kind: "primary"
                enabled: dialog.editor.state.valid
                onClicked: {
                    dialog.editor.apply();
                    dialog.close();
                }
            }
        }
    }
}

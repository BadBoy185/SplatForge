pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import "../theme"

Label {
    color: Theme.text
    font.family: Theme.font
    font.pixelSize: Theme.body
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
}

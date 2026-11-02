pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import "../theme"

Flow {
    id: actions
    required property Action photosAction
    required property Action videoAction
    required property Action folderAction
    property bool compact: false
    property string namePrefix: ""
    readonly property real naturalWidth: Math.ceil(photosButton.implicitWidth) + Math.ceil(videoButton.implicitWidth) + Math.ceil(folderButton.implicitWidth) + spacing * 2 + 2
    spacing: 4
    SplatButton {
        id: photosButton
        objectName: actions.namePrefix + "addPhotos"
        action: actions.photosAction
        text: actions.compact ? "Photos" : "Add photos"
        Accessible.name: "Add photos"
        iconName: "sources"
        leftPadding: actions.compact ? 6 : 12
        rightPadding: leftPadding
        font.pixelSize: actions.compact ? Theme.small : Theme.body
        spacing: actions.compact ? 4 : 8
    }
    SplatButton {
        id: videoButton
        objectName: actions.namePrefix + "addVideo"
        action: actions.videoAction
        text: actions.compact ? "Video" : "Add video"
        Accessible.name: "Add video"
        iconName: "play"
        leftPadding: actions.compact ? 6 : 12
        rightPadding: leftPadding
        font.pixelSize: actions.compact ? Theme.small : Theme.body
        spacing: actions.compact ? 4 : 8
    }
    SplatButton {
        id: folderButton
        objectName: actions.namePrefix + "addFolder"
        action: actions.folderAction
        text: actions.compact ? "Folder" : "Add folder"
        Accessible.name: "Add folder"
        iconName: "folder"
        leftPadding: actions.compact ? 6 : 12
        rightPadding: leftPadding
        font.pixelSize: actions.compact ? Theme.small : Theme.body
        spacing: actions.compact ? 4 : 8
    }
}

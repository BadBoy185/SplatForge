pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../theme"

SplatCard {
    id: flow
    required property var stages
    signal activated(int page)
    function stateFor(name: string): string {
        for (let s of stages)
            if (s.name === name)
                return s.status;
        return "not_started";
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: 20
        RowLayout {
            SplatLabel {
                text: "Project workflow"
                font.weight: Font.DemiBold
                Layout.fillWidth: true
            }
            SplatLabel {
                text: "Published evidence · Plan checks current compatibility"
                font.pixelSize: Theme.small
                color: Theme.muted
            }
        }
        RowLayout {
            spacing: 8
            Repeater {
                model: [["Sources", "sources", "sources", 1], ["Prepare", "views", "image", 2], ["Reconstruct",
                                                                                                 "reconstruction",
                                                                                                 "reconstruct",
                                                                                                 2], ["Validate",
                                                                                                      "validation",
                                                                                                      "check", 2],
                    ["Dataset", "dataset", "dataset", 3], ["Train", "training", "train", 4], ["Result",
                                                                                              "scene", "results",
                                                                                              5]]
                delegate: ColumnLayout {
                    id: stage
                    required property var modelData
                    property string status: flow.stateFor(modelData[1])
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    spacing: 8
                    SplatButton {
                        text: stage.modelData[0]
                        iconName: stage.status === "completed" ? "check" : ""
                        Layout.fillWidth: true
                        kind: "ghost"
                        onClicked: flow.activated(stage.modelData[3])
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        height: 2
                        color: Theme.statusColor(stage.status)
                        opacity: stage.status === "not_started" ? 0.3 : 1
                    }
                    SplatLabel {
                        text: stage.status.replace(/_/g, " ")
                        font.pixelSize: Theme.caption
                        color: Theme.statusColor(stage.status)
                        Layout.alignment: Qt.AlignHCenter
                    }
                }
            }
        }
    }
}

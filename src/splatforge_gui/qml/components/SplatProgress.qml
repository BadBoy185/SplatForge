pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import "../theme"

ProgressBar {
    id: control
    implicitHeight: 4
    background: Rectangle {
        radius: 2
        color: Theme.border
    }
    contentItem: Item {
        clip: true
        Rectangle {
            width: control.indeterminate ? parent.width * 0.25 : parent.width
                                           * control.visualPosition

            height: parent.height
            radius: 2
            color: Theme.accent
            SequentialAnimation on x {
                running: control.indeterminate && control.visible
                loops: Animation.Infinite
                NumberAnimation {
                    from: -control.width * 0.25
                    to: control.width
                    duration: 1500
                }
            }
        }
    }
}

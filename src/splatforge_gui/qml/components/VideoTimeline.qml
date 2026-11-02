pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../theme"

FocusScope {
    id: timeline
    required property var session
    property bool workspaceActive: true
    property real zoom: 1
    readonly property real first: session.mapped ? session.extent.startPosition : 0
    readonly property real last: session.mapped ? session.extent.endPosition : 1
    readonly property real span: Math.max(1, last - first)
    readonly property real tickStep: {
        const target = span / zoom / Math.max(2, width / 110);
        const unit = Math.pow(10, Math.floor(Math.log10(Math.max(1, target))));
        const n = target / unit;
        return unit * (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10);
    }
    implicitHeight: 192
    objectName: "videoTrimTimeline"
    function xAt(ms: real): real { return (ms - first) / span * strip.width; }
    function timeAt(x: real): real { return Math.max(first, Math.min(last, first + x / strip.width * span)); }
    function fit() { zoom = 1; flick.contentX = 0; }
    function magnify(factor: real) {
        const center = (flick.contentX + flick.width / 2) / flick.contentWidth;
        zoom = Math.max(1, Math.min(64, zoom * factor));
        flick.contentX = Math.max(0, Math.min(flick.contentWidth - flick.width, center * flick.contentWidth - flick.width / 2));
    }
    function requestFrames() {
        if (!workspaceActive || !visible || !session.mapped || flick.width <= 0) return;
        session.api.requestThumbnails(timeAt(flick.contentX), timeAt(flick.contentX + flick.width),
            Math.max(2, Math.min(12, Math.ceil(flick.width / 110))));
    }
    function scheduleFrames() {
        frameRequest.restart();
        // Initial frames must not wait for a render/animation tick in an occluded window.
        if (session.api.thumbnails.state.frames.length === 0)
            Qt.callLater(timeline.requestFrames);
    }
    onZoomChanged: frameRequest.restart()
    onWidthChanged: scheduleFrames()
    onWorkspaceActiveChanged: {
        if (workspaceActive) scheduleFrames(); else session.api.thumbnails.stop();
    }
    onVisibleChanged: {
        if (visible) scheduleFrames(); else session.api.thumbnails.stop();
    }
    Connections {
        target: timeline.session
        function onContextKeyChanged() { timeline.fit(); timeline.scheduleFrames(); }
        function onMappedChanged() { timeline.scheduleFrames(); }
    }
    Component.onCompleted: scheduleFrames()
    Timer { id: frameRequest; objectName: "trimFrameRequest"; interval: 120; onTriggered: timeline.requestFrames() }
    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.panelHeader
            Layout.leftMargin: Theme.space
            Layout.rightMargin: Theme.space
            spacing: Theme.spaceSmall
            SplatButton {
                objectName: "fitTimeline"
                text: "Fit timeline"
                kind: "ghost"
                enabled: timeline.session.mapped
                onClicked: timeline.fit()
            }
            SplatButton {
                objectName: "timelineZoomOut"
                text: "−"
                kind: "ghost"
                Accessible.name: "Zoom out timeline"
                enabled: timeline.zoom > 1
                onClicked: timeline.magnify(0.5)
            }
            SplatLabel { text: Math.round(timeline.zoom * 100) + "%"; color: Theme.secondary; font.pixelSize: Theme.small }
            SplatButton {
                objectName: "timelineZoomIn"
                text: "+"
                kind: "ghost"
                Accessible.name: "Zoom in timeline"
                enabled: timeline.session.mapped && timeline.zoom < 64
                onClicked: timeline.magnify(2)
            }
            Item { Layout.fillWidth: true }
            SplatCheckBox {
                objectName: "playUsedRangesOnly"
                text: "Play used ranges only"
                font.pixelSize: Theme.small
                enabled: timeline.session.mapped
                checked: timeline.session.usedOnly
                onToggled: timeline.session.usedOnly = checked
                ToolTip.visible: hovered && !enabled
                ToolTip.text: timeline.session.extent.reason || ""
            }
        }
        Flickable {
            id: flick
            objectName: "trimTimelineScroll"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: Theme.panelInset
            Layout.rightMargin: Theme.panelInset
            clip: true
            contentWidth: width * timeline.zoom
            contentHeight: height
            acceptedButtons: Qt.MiddleButton
            boundsBehavior: Flickable.StopAtBounds
            onContentXChanged: frameRequest.restart()
            ScrollBar.horizontal: ScrollBar { policy: timeline.zoom > 1 ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff }
            Item {
                id: strip
                width: flick.contentWidth
                height: flick.height - 12
                Repeater {
                    model: timeline.session.mapped ? Math.ceil(timeline.span / timeline.zoom / timeline.tickStep) + 2 : 0
                    delegate: Item {
                        required property int index
                        readonly property real value: (Math.floor(flick.contentX / strip.width * timeline.span / timeline.tickStep) + index) * timeline.tickStep
                        x: timeline.xAt(timeline.first + value)
                        height: 28
                        Rectangle { y: 22; width: 1; height: 6; color: Theme.muted }
                        SplatLabel { text: timeline.session.clock(parent.value).slice(0, -4); font.pixelSize: Theme.caption; color: Theme.secondary; x: parent.value >= timeline.span ? -implicitWidth - 2 : 2 }
                    }
                }
                Rectangle {
                    id: band
                    objectName: "trimRangeSurface"
                    x: 0; y: 30
                    width: strip.width; height: Math.max(35, strip.height - 52)
                    color: Theme.strong
                    radius: 2
                    clip: true
                    Repeater {
                        model: timeline.session.api.thumbnails.state.frames
                        delegate: Image {
                            required property var modelData
                            x: timeline.xAt(modelData.position) - width / 2
                            width: flick.width / Math.max(1, timeline.session.api.thumbnails.state.frames.length)
                            height: band.height
                            source: modelData.url
                            fillMode: Image.PreserveAspectCrop
                            visible: source.toString() !== ""
                            cache: false
                        }
                    }
                    Repeater {
                        model: timeline.session.mapped ? timeline.session.extent.gaps : []
                        delegate: Rectangle {
                            required property var modelData
                            x: timeline.xAt(modelData.start)
                            width: timeline.xAt(modelData.end) - x
                            height: band.height
                            color: Theme.background
                            opacity: 0.84
                            Canvas {
                                id: hatch
                                property color stroke: Theme.muted
                                onStrokeChanged: requestPaint()
                                anchors.fill: parent
                                onPaint: {
                                    const c = getContext("2d");
                                    c.clearRect(0, 0, width, height);
                                    c.strokeStyle = hatch.stroke; c.lineWidth = 0.5;
                                    for (let x = -height; x < width; x += 10) {
                                        c.beginPath(); c.moveTo(x, height); c.lineTo(x + height, 0); c.stroke();
                                    }
                                }
                            }
                        }
                    }
                    Repeater {
                        model: timeline.session.mapped ? timeline.session.extent.ranges : []
                        delegate: Rectangle {
                            required property var modelData
                            x: timeline.xAt(modelData.start)
                            width: Math.max(1, timeline.xAt(modelData.end) - x)
                            height: band.height
                            color: "transparent"
                            border.width: 1
                            border.color: Theme.accent
                            Rectangle { width: parent.width; height: 4; color: Theme.accent; opacity: 0.7 }
                        }
                    }
                    MouseArea {
                        id: rangeMouse
                        objectName: "trimRangeGesture"
                        anchors.fill: parent
                        enabled: timeline.session.mapped
                        property real downX: 0
                        property bool dragged: false
                        cursorShape: pressed ? Qt.SizeHorCursor : Qt.CrossCursor
                        onPressed: mouse => {
                            timeline.forceActiveFocus(); downX = mouse.x; dragged = false;
                            timeline.session.beginGesture();
                        }
                        onPositionChanged: mouse => {
                            if (!pressed || !timeline.session.gesture) return;
                            if (Math.abs(mouse.x - downX) > 4) dragged = true;
                            if (!dragged) return;
                            timeline.session.selectedIndex = -1;
                            timeline.session.setBoundary(true, timeline.timeAt(Math.min(downX, mouse.x)));
                            timeline.session.setBoundary(false, timeline.timeAt(Math.max(downX, mouse.x)));
                        }
                        onReleased: mouse => {
                            if (!timeline.session.gesture) return;
                            if (!dragged) {
                                timeline.session.cancelGesture();
                                timeline.session.seek(timeline.timeAt(mouse.x), false);
                            } else timeline.session.finishGesture();
                        }
                        onCanceled: timeline.session.cancelGesture()
                    }
                }
                MouseArea {
                    objectName: "trimRulerSeek"
                    x: 0; y: 0; width: strip.width; height: 28
                    enabled: timeline.session.mapped
                    onPressed: mouse => { timeline.forceActiveFocus(); timeline.session.beginScrub(timeline.timeAt(mouse.x)); }
                    onPositionChanged: mouse => { if (pressed) timeline.session.scrubPosition = timeline.timeAt(mouse.x); }
                    onReleased: timeline.session.endScrub()
                    onCanceled: timeline.session.cancelGesture()
                }
                Rectangle {
                    x: timeline.xAt(timeline.session.startMs)
                    y: band.y - 1
                    width: Math.max(0, timeline.xAt(timeline.session.endMs) - x)
                    height: band.height + 2
                    visible: timeline.session.mapped && isFinite(x) && isFinite(width)
                    color: Theme.selection
                    opacity: 0.25
                    border.color: Theme.accent
                    border.width: 2
                }
                Repeater {
                    model: 2
                    delegate: Rectangle {
                        id: boundary
                        required property int index
                        readonly property bool start: index === 0
                        x: timeline.xAt(start ? timeline.session.startMs : timeline.session.endMs) - 2
                        y: band.y - 3
                        width: 4; height: band.height + 8
                        color: Theme.accent
                        visible: timeline.session.mapped && isFinite(x)
                        SplatLabel {
                            text: timeline.session.clock((boundary.start ? timeline.session.startMs : timeline.session.endMs) - timeline.first)
                            x: boundary.start ? 4 : -implicitWidth - 2
                            y: band.height + 9
                            font.pixelSize: Theme.caption
                            color: Theme.accent
                        }
                        MouseArea {
                            objectName: boundary.start ? "trimStartHandle" : "trimEndHandle"
                            x: -7; width: 18; height: parent.height
                            cursorShape: Qt.SizeHorCursor
                            enabled: timeline.session.usage.canEdit
                            onPressed: { timeline.forceActiveFocus(); timeline.session.beginGesture(); }
                            onPositionChanged: mouse => {
                                if (!pressed || !timeline.session.gesture) return;
                                const point = mapToItem(strip, mouse.x, mouse.y);
                                const ms = timeline.timeAt(point.x);
                                timeline.session.setBoundary(boundary.start, boundary.start
                                    ? Math.min(ms, timeline.session.endMs - 1) : Math.max(ms, timeline.session.startMs + 1));
                            }
                            onReleased: timeline.session.finishGesture()
                            onCanceled: timeline.session.cancelGesture()
                        }
                    }
                }
                Rectangle {
                    id: playhead
                    x: timeline.xAt(timeline.session.displayPosition)
                    y: 18; width: 2; height: strip.height - 18
                    visible: timeline.session.mapped && x >= 0 && x <= strip.width
                    color: Theme.accent
                    Rectangle { x: -4; width: 10; height: 8; color: Theme.accent; radius: 2 }
                    MouseArea {
                        objectName: "trimPlayhead"
                        x: -6; width: 14; height: parent.height
                        cursorShape: Qt.SizeHorCursor
                        onPressed: { timeline.forceActiveFocus(); timeline.session.beginScrub(timeline.session.player.position); }
                        onPositionChanged: mouse => {
                            if (pressed) timeline.session.scrubPosition = timeline.timeAt(mapToItem(strip, mouse.x, mouse.y).x);
                        }
                        onReleased: timeline.session.endScrub()
                        onCanceled: timeline.session.cancelGesture()
                    }
                }
                SplatLabel {
                    anchors.centerIn: parent
                    width: flick.width - 24
                    visible: !timeline.session.mapped
                    text: timeline.session.extent.reason || "Select a video to edit its used ranges."
                    color: Theme.secondary
                    horizontalAlignment: Text.AlignHCenter
                }
            }
        }
        SplatLabel {
            objectName: "timelineThumbnailsMessage"
            readonly property string message: timeline.session.api.thumbnails.state.message
            Layout.leftMargin: Theme.panelInset; Layout.rightMargin: Theme.panelInset
            Layout.bottomMargin: Theme.spaceSmall; Layout.fillWidth: true
            text: timeline.session.mapped ? message || "Drag the strip to select a range · drag its edges to adjust · click the ruler to seek" : ""
            font.pixelSize: Theme.caption; color: message ? Theme.warning : Theme.muted
            elide: message ? Text.ElideNone : Text.ElideRight
            wrapMode: message ? Text.Wrap : Text.NoWrap
        }
    }
    WheelHandler {
        onWheel: event => {
            if (event.modifiers & Qt.ControlModifier) timeline.magnify(event.angleDelta.y > 0 ? 1.25 : 0.8);
            else flick.contentX = Math.max(0, Math.min(flick.contentWidth - flick.width, flick.contentX - event.angleDelta.y));
            event.accepted = true;
        }
    }
    Keys.onEscapePressed: event => { timeline.session.cancelGesture(); timeline.session.api.clearError(); event.accepted = true; }
    Keys.onLeftPressed: event => { timeline.session.seek(timeline.session.player.position - 1000, false); event.accepted = true; }
    Keys.onRightPressed: event => { timeline.session.seek(timeline.session.player.position + 1000, false); event.accepted = true; }
}

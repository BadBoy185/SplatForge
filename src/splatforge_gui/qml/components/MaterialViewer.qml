pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtMultimedia
import "../theme"

Rectangle {
    id: viewer
    required property var media
    required property var videoUsage
    property bool trimMode: false
    property alias trimSession: trim
    property alias playback: videoPlayer
    property bool workspaceActive: true
    property bool shortcutsEnabled: workspaceActive
    property bool catalogCollapsed: false
    property bool propertiesCollapsed: false
    property int registeredCount: 0
    property int visibleCount: 0
    property Component emptyContent
    readonly property bool hasCurrent: media.state.previewIndex > 0
    readonly property bool filteredEmpty: registeredCount > 0 && visibleCount === 0
    signal catalogRequested
    signal propertiesRequested
    signal resetFiltersRequested
    readonly property bool overlayHasFocus: {
        let focus = viewer.Window.window ? viewer.Window.window.activeFocusItem : null;
        while (focus) {
            if (focus === Overlay.overlay)
                return true;
            focus = focus.parent;
        }
        return false;
    }
    readonly property bool video: media.state.previewKind === "video"
    property string loadedVideoUrl: ""
    property string loadedVideoContext: ""
    function syncVideo() {
        const desired = workspaceActive && video ? String(media.state.videoUrl) : "";
        const context = desired ? videoUsage.state.contextKey + ":" + media.state.previewSource.identity : "";
        if (loadedVideoUrl !== desired || loadedVideoContext !== context) {
            trim.pause();
            loadedVideoUrl = desired;
            loadedVideoContext = context;
            videoPlayer.stop();
            videoPlayer.source = "";
            videoPlayer.source = desired;
        }
    }
    Component.onCompleted: syncVideo()
    onWorkspaceActiveChanged: syncVideo()
    onVideoChanged: { if (!video) trimMode = false; syncVideo(); }
    Connections {
        target: viewer.media
        function onChanged() {
            viewer.syncVideo();
        }
    }
    Connections { target: viewer.videoUsage; function onChanged() { viewer.syncVideo(); } }
    function clock(ms: real): string {
        const seconds = Math.floor(ms / 1000);
        return Math.floor(seconds / 60) + ":" + (seconds % 60).toString().padStart(2, "0");
    }
    color: Theme.background
    objectName: "materialViewer"
    VideoTrimSession {
        id: trim
        api: viewer.videoUsage
        player: videoPlayer
        active: viewer.workspaceActive && viewer.video
        trimMode: viewer.trimMode
    }
    MediaPlayer {
        id: videoPlayer
        objectName: "videoPlayer"
        videoOutput: playbackSurface
        audioOutput: AudioOutput {
            volume: 0.7
        }
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.panelHeader
            Layout.leftMargin: Theme.space
            Layout.rightMargin: Theme.space
            spacing: Theme.spaceSmall
            SplatButton {
                objectName: "restoreMaterialsCatalog"
                iconName: "sources"
                kind: "ghost"
                visible: viewer.catalogCollapsed
                Accessible.name: "Show sources catalog"
                onClicked: viewer.catalogRequested()
            }
            SplatButton {
                objectName: "materialsReviewMode"
                text: "Review"
                kind: "ghost"
                font.weight: viewer.trimMode ? Font.Normal : Font.DemiBold
                onClicked: viewer.trimMode = false
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 2; color: Theme.accent; visible: !viewer.trimMode }
            }
            SplatButton {
                objectName: "materialsTrimMode"
                text: "Trim"
                kind: "ghost"
                font.weight: viewer.trimMode ? Font.DemiBold : Font.Normal
                enabled: viewer.hasCurrent && viewer.video && viewer.videoUsage.state.available
                Accessible.description: "Trim is available for registered videos."
                ToolTip.visible: hovered && !enabled
                ToolTip.text: "Trim is available for videos. Select a video from Sources."
                onClicked: viewer.trimMode = true
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 2; color: Theme.accent; visible: viewer.trimMode }
            }
            SplatLabel {
                visible: viewer.hasCurrent && !viewer.video
                text: "Trim needs a video"
                font.pixelSize: Theme.caption
                color: Theme.muted
            }
            Item { Layout.fillWidth: true }
            SplatButton {
                objectName: "fitPhoto"
                text: "Fit"
                kind: "ghost"
                visible: viewer.hasCurrent && !viewer.video && viewer.media.state.previewStatus === "Ready"
                onClicked: photo.fit()
            }
            SplatButton {
                objectName: "zoomOut"
                text: "−"
                kind: "ghost"
                Accessible.name: "Zoom out"
                visible: viewer.hasCurrent && !viewer.video && viewer.media.state.previewStatus === "Ready"
                onClicked: photo.magnify(1 / 1.25)
            }
            SplatLabel {
                text: photo.zoomPercent + "%"
                color: Theme.secondary
                font.pixelSize: Theme.small
                visible: viewer.hasCurrent && !viewer.video && viewer.media.state.previewStatus === "Ready"
            }
            SplatButton {
                objectName: "zoomIn"
                text: "+"
                kind: "ghost"
                Accessible.name: "Zoom in"
                visible: viewer.hasCurrent && !viewer.video && viewer.media.state.previewStatus === "Ready"
                onClicked: photo.magnify(1.25)
            }
            SplatButton {
                objectName: "restoreMaterialProperties"
                iconName: "info"
                kind: "ghost"
                visible: viewer.propertiesCollapsed
                Accessible.name: "Show source properties"
                onClicked: viewer.propertiesRequested()
            }
        }
        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.border
        }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Loader {
                objectName: "emptyMediaState"
                anchors.centerIn: parent
                width: Math.min(parent.width - 40, 410)
                active: viewer.registeredCount === 0
                visible: active
                sourceComponent: viewer.emptyContent
            }
            PhotoViewport {
                id: photo
                anchors.fill: parent
                visible: viewer.hasCurrent && !viewer.video
                imageSource: viewer.media.state.largeImage
            }
            VideoOutput {
                id: playbackSurface
                objectName: "videoOutput"
                anchors.fill: parent
                visible: viewer.hasCurrent && viewer.video && videoPlayer.error === MediaPlayer.NoError
                fillMode: VideoOutput.PreserveAspectFit
            }
            ColumnLayout {
                anchors.centerIn: parent
                width: Math.min(parent.width - 40, 480)
                visible: viewer.registeredCount > 0 && (viewer.video ? videoPlayer.error !== MediaPlayer.NoError : viewer.media.state.previewStatus !== "Ready")
                SplatLabel {
                    objectName: "previewStatus"
                    text: viewer.filteredEmpty ? "No materials match this filter" : viewer.video ? "Video unavailable" : viewer.media.state.previewStatus || "Select a photo or video"
                    font.pixelSize: Theme.section
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                }
                SplatLabel {
                    text: viewer.filteredEmpty ? "Reset the filters to see all registered sources." : viewer.video ? videoPlayer.errorString + "\nCheck the original file and its codec support in the installed Qt runtime." : viewer.media.state.previewDetails || "Choose a material from the catalog to review it."
                    color: Theme.secondary
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                }
                SplatButton {
                    objectName: "viewerResetFilters"
                    text: "Reset filters"
                    visible: viewer.filteredEmpty
                    Layout.alignment: Qt.AlignHCenter
                    onClicked: viewer.resetFiltersRequested()
                }
                SplatButton {
                    objectName: "retryMaterialPreview"
                    text: "Retry preview"
                    visible: viewer.hasCurrent && (viewer.video ? videoPlayer.error !== MediaPlayer.NoError : viewer.media.state.previewStatus === "Preview unavailable")
                    Layout.alignment: Qt.AlignHCenter
                    onClicked: {
                        if (viewer.video) {
                            videoPlayer.stop();
                            videoPlayer.source = "";
                            viewer.loadedVideoUrl = "";
                            viewer.syncVideo();
                        } else {
                            viewer.media.showSource(viewer.media.state.previewSource.identity);
                        }
                    }
                }
            }
        }
        Rectangle {
            Layout.fillWidth: true
            visible: viewer.hasCurrent
            height: 1
            color: Theme.border
        }
        RowLayout {
            objectName: "materialNavigation"
            visible: viewer.hasCurrent
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.transport
            Layout.leftMargin: Theme.space
            Layout.rightMargin: Theme.space
            spacing: Theme.spaceSmall
            SplatButton {
                objectName: "materialPrevious"
                text: "‹"
                kind: "ghost"
                Accessible.name: "Previous material"
                enabled: viewer.media.state.canPrevious
                onClicked: viewer.media.stepPreview(-1)
            }
            SplatButton {
                objectName: "playPauseVideo"
                visible: viewer.video
                text: trim.playIntent || videoPlayer.playbackState === MediaPlayer.PlayingState ? "Pause" : "Play"
                kind: "ghost"
                enabled: videoPlayer.hasVideo && videoPlayer.error === MediaPlayer.NoError && videoPlayer.mediaStatus !== MediaPlayer.LoadingMedia && trim.canPlay
                onClicked: trim.togglePlay()
            }
            SplatButton {
                objectName: "materialNext"
                text: "›"
                kind: "ghost"
                Accessible.name: "Next material"
                enabled: viewer.media.state.canNext
                onClicked: viewer.media.stepPreview(1)
            }
            SplatLabel {
                text: viewer.media.state.previewTitle
                font.pixelSize: Theme.small
                elide: Text.ElideMiddle
                wrapMode: Text.NoWrap
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
            }
            SplatLabel {
                text: viewer.video ? viewer.clock(videoPlayer.position) + " / " + viewer.clock(videoPlayer.duration) : viewer.media.state.previewIndex + " / " + viewer.media.state.previewCount
                color: Theme.secondary
                font.pixelSize: Theme.small
                horizontalAlignment: Text.AlignRight
            }
        }
        SplatLabel {
            visible: viewer.video && (trim.playbackError !== "" || (viewer.trimMode && trim.playReason !== ""))
            text: trim.playbackError || trim.playReason
            color: Theme.warning
            font.pixelSize: Theme.small
            Layout.fillWidth: true
            Layout.leftMargin: Theme.panelInset; Layout.rightMargin: Theme.panelInset; Layout.bottomMargin: Theme.spaceSmall
        }
        Slider {
            id: timeline
            objectName: "videoSeek"
            visible: viewer.video && !viewer.trimMode
            Layout.fillWidth: true
            Layout.leftMargin: Theme.panelInset
            Layout.rightMargin: Theme.panelInset
            from: 0
            stepSize: 1000
            to: Math.max(1, videoPlayer.duration)
            value: videoPlayer.position
            enabled: videoPlayer.seekable
            Accessible.name: "Video position"
            onMoved: trim.seek(value, trim.playIntent || videoPlayer.playbackState === MediaPlayer.PlayingState)
            background: Rectangle {
                x: timeline.leftPadding
                y: timeline.topPadding + timeline.availableHeight / 2 - height / 2
                width: timeline.availableWidth
                height: 4
                radius: 2
                color: Theme.strong
                Rectangle {
                    width: timeline.visualPosition * parent.width
                    height: parent.height
                    color: Theme.accent
                    radius: 2
                }
            }
            handle: Rectangle {
                x: timeline.leftPadding + timeline.visualPosition * (timeline.availableWidth - width)
                y: timeline.topPadding + timeline.availableHeight / 2 - height / 2
                width: 14
                height: 14
                radius: 7
                color: timeline.pressed ? Theme.accentPressed : Theme.accent
                border.width: timeline.visualFocus ? 2 : 0
                border.color: Theme.text
            }
        }
        VideoTimeline {
            id: trimTimeline
            session: trim
            visible: viewer.video && viewer.trimMode
            workspaceActive: viewer.workspaceActive && visible
            Layout.fillWidth: true
            Layout.preferredHeight: viewer.height < 620 ? 166 : 192
        }
        SplatLabel {
            visible: !viewer.video && viewer.media.state.previewIndex > 0
            text: viewer.media.state.reviewLimit
            font.pixelSize: Theme.caption
            color: Theme.muted
            Layout.leftMargin: Theme.panelInset
            Layout.rightMargin: Theme.panelInset
            Layout.bottomMargin: Theme.space
            Layout.fillWidth: true
            elide: Text.ElideRight
            wrapMode: Text.NoWrap
        }
    }
    // The page routes unhandled keys here AFTER focused controls consume them.
    function handleKey(key: int, repeat: bool): bool {
        if (!shortcutsEnabled || overlayHasFocus) return false;
        if (key === Qt.Key_Space && video && videoPlayer.hasVideo) {
            if (!repeat) trim.togglePlay();
        } else if (key === Qt.Key_Left || key === Qt.Key_Right) {
            const direction = key === Qt.Key_Left ? -1 : 1;
            if (trimMode) trim.seek(videoPlayer.position + direction * 1000, false);
            else media.stepPreview(direction);
        } else if (trimMode && trim.mapped && (key === Qt.Key_I || key === Qt.Key_O)) {
            trim.setBoundary(key === Qt.Key_I, videoPlayer.position);
        } else if (trimMode && key === Qt.Key_Escape) {
            trim.cancelGesture(); videoUsage.clearError();
        } else return false;
        return true;
    }
}

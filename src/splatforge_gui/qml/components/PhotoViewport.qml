pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic

Flickable {
    id: viewport
    property url imageSource
    property real zoom: fitScale
    readonly property real fitScale: raster.implicitWidth > 0 && raster.implicitHeight > 0 ? Math.min(1, width / raster.implicitWidth, height / raster.implicitHeight) : 1
    readonly property real zoomPercent: Math.round(zoom * 100)
    function fit() {
        zoom = Qt.binding(() => fitScale);
        contentX = 0;
        contentY = 0;
    }
    function magnify(factor: real) {
        const old = zoom;
        const cx = (contentX + width / 2) / old;
        const cy = (contentY + height / 2) / old;
        zoom = Math.min(1, Math.max(fitScale, zoom * factor));
        contentX = Math.max(0, Math.min(contentWidth - width, cx * zoom - width / 2));
        contentY = Math.max(0, Math.min(contentHeight - height, cy * zoom - height / 2));
    }
    objectName: "photoViewport"
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    contentWidth: Math.max(width, raster.width)
    contentHeight: Math.max(height, raster.height)
    onImageSourceChanged: fit()
    Image {
        id: raster
        objectName: "previewImage"
        source: viewport.imageSource
        cache: false
        width: implicitWidth * viewport.zoom
        height: implicitHeight * viewport.zoom
        x: Math.max(0, (viewport.width - width) / 2)
        y: Math.max(0, (viewport.height - height) / 2)
        onStatusChanged: {
            if (status === Image.Ready)
                viewport.fit();
        }
    }
    ScrollBar.horizontal: ScrollBar {
        policy: raster.width > viewport.width + 0.5 ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff
    }
    ScrollBar.vertical: ScrollBar {
        policy: raster.height > viewport.height + 0.5 ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff
    }
    WheelHandler {
        onWheel: event => {
            viewport.magnify(event.angleDelta.y > 0 ? 1.2 : 1 / 1.2);
            event.accepted = true;
        }
    }
}

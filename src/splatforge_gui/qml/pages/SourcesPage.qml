pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
import "../theme"
import "../components"

FocusScope {
    id: page
    objectName: "sourcesPage"
    required property var vm
    focus: vm.state.page === 1
    Keys.priority: Keys.AfterItem
    Keys.onPressed: event => {
        event.accepted = !page.vm.prepare.state.active && event.modifiers === Qt.NoModifier
            && currentViewer.handleKey(event.key, event.isAutoRepeat);
    }
    property real viewportHeight: height
    property bool catalogVisible: true
    readonly property bool compact: width < 1180
    property bool propertiesVisible: !compact
    onCompactChanged: propertiesVisible = !compact
    property bool expandedGrid: false
    readonly property bool populated: vm.state.sourcesSummary.registered > 0
    function resetFilters() {
        page.vm.setSourceSection("");
        page.vm.setSourceFilter("All");
    }
    Action {
        id: importPhotosAction
        enabled: page.vm.state.canMutate
        onTriggered: photos.open()
    }
    Action {
        id: importVideoAction
        enabled: page.vm.state.canMutate
        onTriggered: videos.open()
    }
    Action {
        id: importFolderAction
        enabled: page.vm.state.canMutate
        onTriggered: folders.open()
    }
    ColumnLayout {
        anchors.fill: parent
        visible: !page.vm.prepare.state.active
        spacing: 0
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.panelHeader
            Layout.leftMargin: Theme.panelInset
            Layout.rightMargin: Theme.panelInset
            SplatLabel {
                text: "Sources"
                Layout.fillWidth: true
                color: Theme.secondary
            }
            SplatButton {
                objectName: "prepareDataEntry"
                text: "Prepare Data →"
                kind: "primary"
                enabled: page.populated && !page.vm.state.busy
                onClicked: page.vm.prepare.enter()
            }
        }
        SplatLabel {
            visible: page.vm.state.participationWarnings.length > 0
            text: page.vm.state.participationWarnings.join("\n")
            color: Theme.warning
            font.pixelSize: Theme.small
            Layout.fillWidth: true
            Layout.margins: 8
        }
        SplitView {
            id: split
            objectName: "materialsSplit"
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal
            handle: Rectangle {
                implicitWidth: 5
                color: SplitHandle.pressed ? Theme.accent : SplitHandle.hovered ? Theme.strong : Theme.border
            }
            Rectangle {
                id: catalog
                objectName: "materialsCatalog"
                visible: page.catalogVisible
                color: Theme.surface
                SplitView.fillWidth: page.expandedGrid
                SplitView.preferredWidth: page.expandedGrid ? Math.max(500, page.width * 0.65) : 280
                SplitView.minimumWidth: 248
                SplitView.maximumWidth: page.expandedGrid ? page.width - 100 : Math.max(300, page.width * 0.45)
                ColumnLayout {
                    anchors.fill: parent
                    spacing: 4
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Theme.panelHeader
                        Layout.leftMargin: Theme.panelInset
                        Layout.rightMargin: Theme.space
                        spacing: 2
                        SplatLabel {
                            text: "Sources"
                            font.pixelSize: Theme.panelHeading
                            font.weight: Font.DemiBold
                            Layout.fillWidth: true
                        }
                        SplatButton {
                            id: catalogMenuButton
                            objectName: "catalogOptions"
                            text: "⋯"
                            kind: "ghost"
                            Accessible.name: "Catalog actions"
                            onClicked: catalogMenu.popup(catalogMenuButton, 0, catalogMenuButton.height)
                        }
                        SplatButton {
                            objectName: "collapseMaterialsCatalog"
                            iconName: "close"
                            kind: "ghost"
                            Accessible.name: "Hide sources catalog"
                            onClicked: {
                                page.expandedGrid = false;
                                page.catalogVisible = false;
                                currentViewer.forceActiveFocus();
                            }
                        }
                    }
                    MediaImportActions {
                        id: catalogImport
                        objectName: "catalogImportActions"
                        Layout.fillWidth: true
                        Layout.leftMargin: 8
                        Layout.rightMargin: 8
                        compact: true
                        photosAction: importPhotosAction
                        videoAction: importVideoAction
                        folderAction: importFolderAction
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.leftMargin: 8
                        Layout.rightMargin: 8
                        spacing: 2
                        Repeater {
                            model: ["Included", "Excluded", "All"]
                            delegate: SplatButton {
                                required property string modelData
                                objectName: "filter" + modelData
                                text: modelData
                                Layout.fillWidth: true
                                leftPadding: 6
                                rightPadding: 6
                                font.pixelSize: Theme.small
                                kind: page.vm.state.sourceFilter === modelData ? "primary" : "ghost"
                                enabled: page.vm.state.participationSupported || modelData === "All"
                                onClicked: page.vm.setSourceFilter(modelData)
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.margins: 8
                        spacing: 4
                        SplatComboBox {
                            objectName: "sourceSectionPicker"
                            Layout.fillWidth: true
                            Layout.minimumWidth: 80
                            model: page.vm.state.sourceSections
                            textRole: "label"
                            valueRole: "value"
                            selectedValue: page.vm.state.sourceSection
                            Accessible.name: "Browse source group or captured device"
                            onActivated: page.vm.setSourceSection(currentValue)
                        }
                        SplatButton {
                            objectName: "sourceGroups"
                            iconName: "folder"
                            kind: "ghost"
                            Accessible.name: "Manage source groups"
                            enabled: page.vm.state.canMutate && page.vm.state.groupsSupported
                            onClicked: {
                                groups.mode = "manage";
                                groups.open();
                            }
                        }
                    }
                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        ColumnLayout {
                            objectName: page.populated ? "filteredSourcesEmptyState" : "sourcesEmptyState"
                            anchors.centerIn: parent
                            width: parent.width - 24
                            visible: page.vm.sources.count === 0
                            SplatLabel {
                                objectName: "participationEmptyState"
                                text: !page.populated ? "No sources yet." : page.vm.state.sourceSection !== "" ? "No sources in this group for this filter." : page.vm.state.sourceFilter === "Excluded" ? "No excluded sources." : "All sources are excluded."
                                Layout.fillWidth: true
                                horizontalAlignment: Text.AlignHCenter
                            }
                            SplatButton {
                                objectName: "viewExcluded"
                                text: "View Excluded"
                                visible: page.populated && page.vm.state.sourceFilter === "Included"
                                onClicked: page.vm.setSourceFilter("Excluded")
                                Layout.alignment: Qt.AlignHCenter
                            }
                            SplatButton {
                                objectName: "resetSourceFilters"
                                text: "Reset filters"
                                visible: page.populated
                                Layout.alignment: Qt.AlignHCenter
                                onClicked: page.resetFilters()
                            }
                        }
                        Repeater {
                            model: 2
                            delegate: Loader {
                                required property int index
                                readonly property bool current: page.populated && page.vm.state.page === 1 && (page.vm.state.sourceView === "Grid" ? index === 1 : index === 0)
                                anchors.fill: parent
                                active: current
                                visible: current && page.vm.sources.count > 0
                                sourceComponent: index === 0 ? listBrowser : gridBrowser
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.margins: 8
                        spacing: 2
                        SplatLabel {
                            text: page.vm.sources.count + " sources"
                            font.pixelSize: Theme.small
                            color: Theme.secondary
                            Layout.fillWidth: true
                        }
                        SplatButton {
                            objectName: "sourceListMode"
                            text: "List"
                            leftPadding: 8
                            rightPadding: 8
                            kind: page.vm.state.sourceView === "List" ? "secondary" : "ghost"
                            onClicked: {
                                page.vm.setSourceView("List");
                                page.expandedGrid = false;
                            }
                        }
                        SplatButton {
                            objectName: "sourceGridMode"
                            text: "Grid"
                            leftPadding: 8
                            rightPadding: 8
                            kind: page.vm.state.sourceView === "Grid" ? "secondary" : "ghost"
                            onClicked: page.vm.setSourceView("Grid")
                        }
                        SplatButton {
                            objectName: "expandMaterialsGrid"
                            text: page.expandedGrid ? "↙" : "↗"
                            kind: "ghost"
                            visible: page.vm.state.sourceView === "Grid"
                            Accessible.name: page.expandedGrid ? "Back to viewer" : "Expand grid"
                            onClicked: page.expandedGrid = !page.expandedGrid
                        }
                    }
                }
            }
            MaterialViewer {
                id: currentViewer
                media: page.vm.media
                videoUsage: page.vm.videoUsage
                registeredCount: page.vm.state.sourcesSummary.registered
                visibleCount: page.vm.sources.count
                onResetFiltersRequested: page.resetFilters()
                emptyContent: Component {
                    ColumnLayout {
                        spacing: 12
                        SplatButton {
                            iconName: "sources"
                            icon.width: 28
                            icon.height: 28
                            background: null
                            enabled: false
                            opacity: 1
                            focusPolicy: Qt.NoFocus
                            Accessible.ignored: true
                            Layout.alignment: Qt.AlignHCenter
                        }
                        SplatLabel {
                            objectName: "emptyMediaTitle"
                            text: "Add your media"
                            font.pixelSize: Theme.section
                            font.weight: Font.DemiBold
                            Layout.fillWidth: true
                            horizontalAlignment: Text.AlignHCenter
                        }
                        SplatLabel {
                            text: "Drag photos, videos, or a folder here"
                            color: Theme.secondary
                            Layout.fillWidth: true
                            horizontalAlignment: Text.AlignHCenter
                        }
                        MediaImportActions {
                            objectName: "emptyMediaActions"
                            Layout.preferredWidth: Math.min(naturalWidth, parent.width)
                            Layout.alignment: Qt.AlignHCenter
                            Layout.topMargin: 8
                            namePrefix: "empty-"
                            photosAction: importPhotosAction
                            videoAction: importVideoAction
                            folderAction: importFolderAction
                        }
                    }
                }
                catalogCollapsed: !page.catalogVisible
                propertiesCollapsed: !page.propertiesVisible || page.compact
                onCatalogRequested: {
                    page.catalogVisible = true;
                    catalogImport.forceActiveFocus();
                }
                onPropertiesRequested: page.propertiesVisible = !page.propertiesVisible
                workspaceActive: page.vm.state.page === 1 && !page.vm.prepare.state.active && page.vm.media.state.embeddedPreview
                shortcutsEnabled: workspaceActive && !details.visible && !groups.visible
                visible: !page.expandedGrid
                SplitView.fillWidth: true
                SplitView.minimumWidth: 260
            }
            Loader {
                id: propertiesDock
                objectName: "materialProperties"
                visible: page.propertiesVisible && !page.compact
                active: visible
                SplitView.preferredWidth: 300
                SplitView.minimumWidth: 260
                SplitView.maximumWidth: 440
                sourceComponent: propertiesContent
            }
        }
        Popup {
            id: propertiesOverlay
            objectName: "materialPropertiesOverlay"
            parent: page
            x: parent.width - width
            y: 0
            width: 300
            height: page.height
            padding: 0
            visible: page.compact && page.propertiesVisible && page.visible
            focus: true
            closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
            onClosed: {
                if (page.compact)
                    page.propertiesVisible = false;
                currentViewer.forceActiveFocus();
            }
            background: Rectangle {
                color: Theme.surface
                border.color: Theme.border
            }
            contentItem: Loader {
                active: propertiesOverlay.visible
                sourceComponent: propertiesContent
            }
        }
        Component {
            id: propertiesContent
            Loader { sourceComponent: currentViewer.trimMode ? trimProperties : reviewProperties }
        }
        Component {
            id: trimProperties
            VideoTrimProperties {
                session: currentViewer.trimSession
                media: page.vm.media
                onCloseRequested: {
                    page.propertiesVisible = false;
                    currentViewer.forceActiveFocus();
                }
            }
        }
        Component {
            id: reviewProperties
            MaterialProperties {
                vm: page.vm
                onCloseRequested: {
                    page.propertiesVisible = false;
                    currentViewer.forceActiveFocus();
                }
                onDetailsRequested: {
                    // The detail dialog follows focus; viewing does not alter the batch set.
                    page.vm.media.focusSource(page.vm.media.state.previewSource.identity);
                    details.open();
                }
            }
        }
        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.border
        }
        Flow {
            objectName: "sourceBatchBar"
            visible: page.vm.sources.selectedCount > 1
            Layout.fillWidth: true
            Layout.margins: 8
            spacing: 4
            SplatLabel {
                text: page.vm.sources.selectedCount + " selected · Batch actions"
                height: 36
                verticalAlignment: Text.AlignVCenter
            }
            SplatButton {
                objectName: "batchCreateGroup"
                text: "Create Group…"
                enabled: page.vm.state.canMutate && page.vm.state.groupsSupported
                onClicked: {
                    groups.mode = "create";
                    groups.open();
                }
            }
            SplatButton {
                objectName: "batchMoveGroup"
                text: "Move to Group…"
                enabled: page.vm.state.canMutate && page.vm.state.groupsSupported
                onClicked: {
                    groups.mode = "move";
                    groups.open();
                }
            }
            SplatButton {
                objectName: "batchExclude"
                text: "Exclude selected"
                visible: page.vm.state.sourceFilter !== "Excluded"
                enabled: page.vm.state.canMutate && page.vm.state.participationSupported
                onClicked: page.vm.setSelectedIncluded(false)
            }
            SplatButton {
                objectName: "batchRestore"
                text: "Restore selected"
                visible: page.vm.state.sourceFilter !== "Included"
                enabled: page.vm.state.canMutate && page.vm.state.participationSupported
                onClicked: page.vm.setSelectedIncluded(true)
            }
            SplatButton {
                objectName: "clearSourceSelection"
                text: "Clear selection"
                kind: "ghost"
                onClicked: page.vm.sources.clearSelection()
            }
        }
    }
    PreparePage {
        anchors.fill: parent
        vm: page.vm
        visible: page.vm.prepare.state.active
    }
    Component {
        id: listBrowser
        ListView {
            id: sources
            objectName: "sourceList"
            anchors.fill: parent
            model: page.vm.sources
            clip: true
            reuseItems: true
            section.property: "sectionKey"
            section.criteria: ViewSection.FullString
            section.delegate: SplatLabel {
                required property string section
                objectName: "sourceSectionHeader"
                width: sources.width
                text: (page.vm.state.sourceSections.find(option => option.value === section) || {}).label || section
                leftPadding: Theme.panelInset
                rightPadding: Theme.panelInset
                topPadding: Theme.space
                bottomPadding: Theme.space
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                wrapMode: Text.NoWrap
                color: Theme.secondary
            }
            currentIndex: page.vm.sources.selectedIndex
            onCurrentIndexChanged: {
                if (currentIndex >= 0)
                    positionViewAtIndex(currentIndex, ListView.Contain);
            }
            delegate: ItemDelegate {
                id: sourceRow
                required property var record
                required property string recordId
                required property string imageUrl
                required property bool sourceSelected
                readonly property bool reviewing: page.vm.media.state.previewSource.identity === recordId
                width: sources.width
                height: Theme.sourceRow
                padding: Theme.sourceRowInset
                hoverEnabled: true
                focusPolicy: Qt.StrongFocus
                objectName: "source-" + recordId
                Accessible.name: record.filename + ", " + record.description + ", " + record.availability + ", " + (record.participationLabel || "Included")
                onClicked: page.vm.media.activateSource(recordId)
                onDoubleClicked: {
                    page.vm.media.showSource(recordId);
                }
                background: Rectangle {
                    color: sourceRow.sourceSelected ? Theme.selection : sourceRow.hovered ? Theme.hover : "transparent"
                    border.width: sourceRow.visualFocus || sourceRow.sourceSelected ? 2 : 0
                    border.color: Theme.accent
                }
                contentItem: Item {
                    Rectangle {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        width: Theme.icon
                        height: Theme.icon
                        z: 1
                        color: Theme.surface
                        visible: sourceRow.reviewing
                        SplatLabel {
                            anchors.centerIn: parent
                            text: "▶"
                            font.pixelSize: Theme.caption
                            color: Theme.accent
                        }
                    }
                    RowLayout {
                        anchors.fill: parent
                        spacing: 8
                        Item {
                            Layout.preferredWidth: Theme.sourceThumbnailWidth
                            Layout.preferredHeight: Theme.sourceThumbnailHeight
                            Image {
                                anchors.fill: parent
                                source: sourceRow.imageUrl
                                sourceSize: Qt.size(192, 192)
                                cache: false
                                fillMode: Image.PreserveAspectFit
                                visible: sourceRow.record.type === "photo"
                            }
                            SplatLabel {
                                anchors.centerIn: parent
                                text: sourceRow.record.type === "video" ? "▶" : "No preview"
                                font.pixelSize: Theme.small
                                color: Theme.secondary
                                visible: sourceRow.record.type === "video" || sourceRow.imageUrl === ""
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            SplatLabel {
                                text: sourceRow.record.filename
                                font.weight: Font.DemiBold
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                                wrapMode: Text.NoWrap
                            }
                            SplatLabel {
                                text: sourceRow.record.description
                                color: Theme.secondary
                                font.pixelSize: Theme.small
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                                wrapMode: Text.NoWrap
                            }
                            SplatLabel {
                                visible: sourceRow.reviewing || sourceRow.record.isIncluded === false || ["missing", "warning"].indexOf(sourceRow.record.availabilityState) >= 0
                                text: (sourceRow.reviewing ? "Viewing" : "") + (sourceRow.record.isIncluded === false ? (sourceRow.reviewing ? " · Excluded" : "Excluded") : !sourceRow.reviewing ? sourceRow.record.availability : "")
                                color: sourceRow.reviewing ? Theme.accent : Theme.secondary
                                font.pixelSize: Theme.caption
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                                wrapMode: Text.NoWrap
                            }
                        }
                    }
                    SourceActions {
                        id: rowActions
                        visible: sourceRow.hovered || sourceRow.activeFocus || interacting
                        anchors.right: parent.right
                        anchors.top: parent.top
                        vm: page.vm
                        record: sourceRow.record
                        sourceId: sourceRow.recordId
                        onDetailsRequested: details.open()
                    }
                }
            }
            ScrollBar.vertical: ScrollBar {
                policy: sources.contentHeight > sources.height ? ScrollBar.AlwaysOn : ScrollBar.AsNeeded
            }
        }
    }
    Component {
        id: gridBrowser
        GridView {
            id: grid
            objectName: "sourceGrid"
            model: page.vm.sources
            clip: true
            reuseItems: true
            cacheBuffer: 0
            cellWidth: Math.max(156, width / Math.max(1, Math.floor(width / 184)))
            cellHeight: Math.max(128, Math.min(240, height))
            currentIndex: count > 0 ? page.vm.sources.selectedIndex : -1
            onCurrentIndexChanged: {
                if (currentIndex >= 0)
                    positionViewAtIndex(currentIndex, GridView.Contain);
            }
            delegate: ItemDelegate {
                id: tile
                required property var record
                required property string recordId
                required property string imageUrl
                required property string thumbStatus
                required property bool sourceSelected
                width: grid.cellWidth - 8
                height: grid.cellHeight - 8
                padding: 8
                objectName: "tile-" + recordId
                hoverEnabled: true
                focusPolicy: Qt.StrongFocus
                Accessible.name: record.filename + ", " + record.description + ", " + record.availability + ", " + (record.participationLabel || "Included")
                onClicked: page.vm.media.activateSource(recordId)
                onDoubleClicked: {
                    page.vm.media.showSource(recordId);
                }
                background: Rectangle {
                    color: tile.sourceSelected ? Theme.selection : tile.hovered ? Theme.hover : Theme.surface
                    radius: Theme.radius
                    border.color: tile.visualFocus || tile.sourceSelected ? Theme.accent : Theme.border
                    border.width: tile.visualFocus || tile.sourceSelected ? 2 : 0
                }
                contentItem: ColumnLayout {
                    spacing: 4
                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.minimumHeight: 36
                        SplatLabel {
                            objectName: "currentTile-" + tile.recordId
                            anchors.left: parent.left
                            anchors.top: parent.top
                            z: 1
                            text: "▶ Viewing"
                            padding: 4
                            font.pixelSize: Theme.caption
                            color: Theme.accent
                            visible: page.vm.media.state.previewSource.identity === tile.recordId
                            background: Rectangle {
                                color: Theme.surface
                            }
                        }
                        Loader {
                            anchors.fill: parent
                            active: tile.record.type === "photo"
                            sourceComponent: Image {
                                objectName: "photoThumbnail"
                                source: tile.record.type === "photo" ? tile.imageUrl : ""
                                sourceSize: Qt.size(192, 192)
                                fillMode: Image.PreserveAspectFit
                                cache: false
                            }
                        }
                        SplatLabel {
                            objectName: "thumbnailPlaceholder"
                            anchors.centerIn: parent
                            visible: tile.record.type === "video" || tile.imageUrl === ""
                            text: tile.record.type === "video" ? "▶\nVIDEO" : "Photo"
                            horizontalAlignment: Text.AlignHCenter
                            color: Theme.secondary
                        }
                        Rectangle {
                            anchors.top: parent.top
                            anchors.right: parent.right
                            visible: tile.hovered || tile.activeFocus || tileActions.interacting
                            width: tileActions.implicitWidth
                            height: tileActions.implicitHeight
                            color: Theme.surface
                            radius: Theme.radius
                            SourceActions {
                                id: tileActions
                                vm: page.vm
                                record: tile.record
                                sourceId: tile.recordId
                                namePrefix: "tile-"
                                onDetailsRequested: details.open()
                            }
                        }
                    }
                    SplatLabel {
                        text: tile.record.filename
                        font.weight: Font.DemiBold
                        font.pixelSize: Theme.small
                        Layout.fillWidth: true
                        elide: Text.ElideMiddle
                        wrapMode: Text.NoWrap
                    }
                    SplatLabel {
                        text: (tile.record.logicalGroupLabel || tile.record.device || "Unknown device") + " · " + tile.record.description
                        color: Theme.secondary
                        font.pixelSize: Theme.caption
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                        wrapMode: Text.NoWrap
                    }
                    SourceAvailability {
                        record: tile.record
                        visible: ["missing", "warning"].indexOf(tile.record.availabilityState) >= 0
                        Layout.fillWidth: true
                    }
                    SplatLabel {
                        visible: tile.record.isIncluded === false
                        text: "Excluded from processing"
                        font.pixelSize: Theme.caption
                        color: Theme.secondary
                        Layout.fillWidth: true
                    }
                }
            }
            ScrollBar.vertical: ScrollBar {}
        }
    }
    Menu {
        id: catalogMenu
        palette.window: Theme.surface
        palette.windowText: Theme.text
        MenuItem {
            text: "Select all visible"
            enabled: page.vm.sources.count > 0
            onTriggered: page.vm.sources.selectAllVisible()
        }
        MenuItem {
            objectName: "sourceParticipation"
            text: "Exclude selected"
            enabled: page.vm.sources.selectedCount > 0 && page.vm.state.canMutate && page.vm.state.participationSupported
            onTriggered: page.vm.setSelectedIncluded(false)
        }
        MenuItem {
            objectName: "restoreSelectedSources"
            text: "Restore selected"
            enabled: page.vm.sources.selectedCount > 0 && page.vm.state.canMutate && page.vm.state.participationSupported
            onTriggered: page.vm.setSelectedIncluded(true)
        }
        MenuSeparator {}
        MenuItem {
            objectName: "checkSourceFiles"
            text: "Check source files…"
            enabled: page.populated && page.vm.state.canMutate
            onTriggered: sourceChecks.open()
        }
        MenuItem {
            objectName: "locateSourceFolder"
            text: "Locate source folder…"
            enabled: page.populated && page.vm.state.canMutate
            onTriggered: page.vm.folderRelink.begin()
        }
        MenuItem {
            text: "Reset panel widths"
            onTriggered: {
                catalog.SplitView.preferredWidth = 280;
                propertiesDock.SplitView.preferredWidth = 300;
                page.expandedGrid = false;
            }
        }
    }
    SplatDialog {
        id: sourceChecks
        title: "Check source files"
        height: 300
        ColumnLayout {
            anchors.fill: parent
            SplatLabel {
                text: "Checks originals at their saved locations."
                Layout.fillWidth: true
            }
            SplatLabel {
                objectName: "sourceCheckSummary"
                text: page.vm.state.sourceCheckResult + page.vm.state.sourcesSummary.checkMessage
                color: Theme.secondary
                Layout.fillWidth: true
            }
            Item {
                Layout.fillHeight: true
            }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                SplatButton {
                    text: "Close"
                    onClicked: sourceChecks.close()
                }
                SplatButton {
                    objectName: "runSourceCheck"
                    text: "Check source files"
                    kind: "primary"
                    enabled: page.populated && page.vm.state.canMutate
                    onClicked: page.vm.verifySources()
                }
            }
        }
    }
    SourceDetailsDialog {
        id: details
        vm: page.vm
    }
    FolderRelinkDialog {
        vm: page.vm
    }
    Connections {
        target: page.vm
        function onDialogRequested(name: string) {
            if (name === "closeSourceDetails") {
                details.close();
                groups.close();
            }
        }
    }
    SourceGroupsDialog {
        id: groups
        vm: page.vm
    }
    Shortcut {
        sequence: StandardKey.SelectAll
        enabled: page.vm.state.page === 1 && !details.visible && !groups.visible && !currentViewer.overlayHasFocus && (page.vm.media.state.embeddedPreview || page.vm.media.state.previewIndex === 0)
        onActivated: page.vm.sources.selectAllVisible()
    }
    Connections {
        target: page.vm.sources
        function onSelectionChanged() {
            if (page.vm.sources.selectedId === "")
                details.close();
        }
    }
    FileDialog {
        id: photos
        objectName: "photosPicker"
        title: "Add photos"
        fileMode: FileDialog.OpenFiles
        nameFilters: ["Photos (*.jpg *.jpeg *.png)"]
        onAccepted: page.vm.addFiles(selectedFiles.map(u => String(u)))
    }
    FileDialog {
        id: videos
        objectName: "videosPicker"
        title: "Add video"
        fileMode: FileDialog.OpenFiles
        nameFilters: ["Videos (*.mp4 *.mov)"]
        onAccepted: page.vm.addFiles(selectedFiles.map(u => String(u)))
    }
    FolderDialog {
        id: folders
        objectName: "folderPicker"
        title: "Add folder"
        onAccepted: page.vm.addFolder(String(selectedFolder))
    }
    DropArea {
        id: mediaDrop
        objectName: "materialsDropArea"
        anchors.fill: parent
        enabled: page.vm.state.page === 1 && !page.vm.prepare.state.active && page.vm.state.canMutate
        onEntered: drag => {
            drag.accepted = drag.hasUrls && page.vm.canDropMedia(drag.urls.map(u => String(u)));
        }
        onDropped: drop => {
            if (drop.hasUrls && page.vm.canDropMedia(drop.urls.map(u => String(u)))) {
                drop.acceptProposedAction();
                page.vm.dropUrls(drop.urls.map(u => String(u)));
            } else {
                drop.accepted = false;
            }
        }
    }
    Rectangle {
        objectName: "materialsDropFeedback"
        anchors.fill: parent
        z: 20
        visible: mediaDrop.containsDrag
        color: Qt.alpha(Theme.accent, 0.06)
        border.color: Theme.accent
        border.width: 2
        SplatLabel {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 64
            text: "Drop to add media"
            padding: 12
            font.weight: Font.DemiBold
            background: Rectangle {
                color: Theme.surface
                radius: Theme.radius
            }
        }
    }
}

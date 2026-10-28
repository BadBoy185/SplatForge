pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
import "../theme"
import "../components"

ColumnLayout {
    id: page
    objectName: "sourcesPage"
    required property var vm
    property real viewportHeight: 512
    readonly property bool populated: vm.state.sourcesSummary.registered > 0
    readonly property real listHeight: Math.max(128, viewportHeight - header.implicitHeight
                                                - (check.visible ? check.implicitHeight + 16 : 0)
                                                - (videoHint.visible ? videoHint.implicitHeight + 16 : 0)
                                                - footer.implicitHeight - 32)
    spacing: 16
    SplatPageHeader {
        id: header
        title: "Sources"
        subtitle: page.populated
                  ? !page.vm.state.participationSupported
                    ? page.vm.state.sourcesSummary.registered + " registered · Participation unavailable"
                    : page.vm.state.sourcesSummary.registered + " registered · "
                    + page.vm.state.sourcesSummary.included + " included · "
                    + page.vm.state.sourcesSummary.excluded + " excluded"
                  : "Add the photos and videos you want to use."
        Layout.fillWidth: true
        Loader {
            active: page.populated
            sourceComponent: compactActions
        }
    }
    Component {
        id: compactActions
        RowLayout {
            spacing: 8
            SplatButton {
                objectName: "addPhotos"
                text: "Photos"
                iconName: "plus"
                enabled: page.vm.state.canMutate
                onClicked: photos.open()
            }
            SplatButton {
                objectName: "addVideo"
                text: "Video"
                iconName: "plus"
                enabled: page.vm.state.canMutate
                onClicked: videos.open()
            }
            SplatButton {
                objectName: "addFolder"
                text: "Folder"
                iconName: "folder"
                enabled: page.vm.state.canMutate
                onClicked: folders.open()
            }
        }
    }
    SplatCard {
        id: check
        visible: page.populated && !(page.vm.sources.selectedCount > 1 && page.viewportHeight < 600)
        Layout.fillWidth: true
        padding: 12
        implicitHeight: checkContent.implicitHeight + padding * 2
        RowLayout {
            id: checkContent
            width: parent.width
            spacing: 12
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                SplatLabel {
                    objectName: "sourceCheckSummary"
                    text: page.vm.state.participationWarnings.length > 0
                          ? page.vm.state.participationWarnings.join("\n")
                          : page.vm.state.sourceCheckResult + page.vm.state.sourcesSummary.checkMessage
                    font.weight: Font.DemiBold
                    Layout.fillWidth: true
                }
                SplatLabel {
                    text: "Check that SplatForge can still access the original files."
                    color: Theme.secondary
                    font.pixelSize: Theme.small
                    Layout.fillWidth: true
                }
            }
            SplatButton {
                objectName: "checkSourceFiles"
                text: "Check Source Files"
                enabled: page.populated && page.vm.state.canMutate
                onClicked: page.vm.verifySources()
                ToolTip.visible: hovered
                ToolTip.text: "Checks that the original files are still available at their saved locations."
            }
        }
    }
    SplatCard {
        objectName: "sourcesEmptyState"
        visible: !page.populated
        Layout.fillWidth: true
        Layout.preferredHeight: page.listHeight
        Loader {
            anchors.centerIn: parent
            width: Math.min(parent.width, 560)
            active: !page.populated
            sourceComponent: emptyActions
        }
    }
    Component {
        id: emptyActions
        ColumnLayout {
            spacing: 16
            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                spacing: 12
                SplatButton {
                    objectName: "addPhotos"
                    text: "Add Photos"
                    iconName: "plus"
                    kind: "primary"
                    Layout.preferredWidth: 156
                    enabled: page.vm.state.canMutate
                    onClicked: photos.open()
                }
                SplatButton {
                    objectName: "addVideo"
                    text: "Add Video"
                    iconName: "plus"
                    kind: "primary"
                    Layout.preferredWidth: 156
                    enabled: page.vm.state.canMutate
                    onClicked: videos.open()
                }
            }
            SplatButton {
                objectName: "addFolder"
                text: "Add Folder"
                iconName: "folder"
                Layout.alignment: Qt.AlignHCenter
                enabled: page.vm.state.canMutate
                onClicked: folders.open()
            }
            SplatLabel {
                text: "or drop files or a folder here"
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                color: Theme.secondary
            }
            SplatLabel {
                text: "SplatForge keeps your original files in place."
                color: Theme.secondary
                font.pixelSize: Theme.small
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
            }
        }
    }
    SplatCard {
        visible: page.populated
        Layout.fillWidth: true
        Layout.preferredHeight: page.listHeight
        padding: 0
        ColumnLayout {
            anchors.fill: parent
            spacing: 0
            RowLayout {
                Layout.fillWidth: true
                Layout.margins: 8
                Repeater {
                    model: ["Included", "Excluded", "All"]
                    delegate: SplatButton {
                        required property string modelData
                        objectName: "filter" + modelData
                        text: modelData + " " + (modelData === "Included"
                              ? page.vm.state.sourcesSummary.included : modelData === "Excluded"
                              ? page.vm.state.sourcesSummary.excluded
                              : page.vm.state.sourcesSummary.registered)
                        kind: page.vm.state.sourceFilter === modelData ? "primary" : "ghost"
                        enabled: page.vm.state.participationSupported || modelData === "All"
                        onClicked: page.vm.setSourceFilter(modelData)
                        Accessible.name: text + " sources"
                    }
                }
                Item { Layout.fillWidth: true }
                SplatButton {
                    objectName: "sourceListMode"
                    text: "List"
                    kind: page.vm.state.sourceView === "List" ? "primary" : "secondary"
                    onClicked: page.vm.setSourceView("List")
                    Accessible.description: "Show sources as a list"
                }
                SplatButton {
                    objectName: "sourceGridMode"
                    text: "Grid"
                    kind: page.vm.state.sourceView === "Grid" ? "primary" : "secondary"
                    onClicked: page.vm.setSourceView("Grid")
                    Accessible.description: "Show sources as a grid"
                }
                SplatButton {
                    objectName: "sourceDetails"
                    iconName: "info"
                    Accessible.name: "Details"
                    kind: "ghost"
                    enabled: page.vm.sources.selectedId !== ""
                    onClicked: details.open()
                }
                SplatButton {
                    objectName: "sourceParticipation"
                    iconName: page.vm.sources.selected.isIncluded === false ? "refresh" : "exclude"
                    enabled: page.vm.sources.selectedId !== "" && page.vm.state.canMutate
                             && page.vm.state.participationSupported
                    Accessible.name: page.vm.sources.selected.isIncluded === false ? "Restore to processing" : "Exclude from processing"
                    ToolTip.visible: hovered
                    ToolTip.text: Accessible.name + ". Original file stays in place."
                    onClicked: page.vm.setSourceIncluded(page.vm.sources.selectedId,
                                                        page.vm.sources.selected.isIncluded === false)
                }
            }
            Flow {
                objectName: "sourceBatchBar"
                visible: page.vm.sources.selectedCount > 1
                Layout.fillWidth: true
                Layout.leftMargin: 12
                Layout.rightMargin: 12
                Layout.bottomMargin: 8
                spacing: 4
                SplatLabel {
                    text: page.vm.sources.selectedCount + " selected"
                    height: 36
                    verticalAlignment: Text.AlignVCenter
                }
                SplatButton {
                    objectName: "batchCreateGroup"
                    text: "Create Group…"
                    enabled: page.vm.state.canMutate && page.vm.state.groupsSupported
                    onClicked: { groups.mode = "create"; groups.open(); }
                }
                SplatButton {
                    objectName: "batchMoveGroup"
                    text: "Move to Group…"
                    enabled: page.vm.state.canMutate && page.vm.state.groupsSupported
                    onClicked: { groups.mode = "move"; groups.open(); }
                }
                SplatButton {
                    objectName: "batchExclude"
                    text: "Exclude"
                    visible: page.vm.state.sourceFilter !== "Excluded"
                    enabled: page.vm.state.canMutate && page.vm.state.participationSupported
                    onClicked: page.vm.setSelectedIncluded(false)
                }
                SplatButton {
                    objectName: "batchRestore"
                    text: "Restore"
                    visible: page.vm.state.sourceFilter !== "Included"
                    enabled: page.vm.state.canMutate && page.vm.state.participationSupported
                    onClicked: page.vm.setSelectedIncluded(true)
                }
                SplatButton {
                    objectName: "clearSourceSelection"
                    text: "Clear"
                    kind: "ghost"
                    onClicked: page.vm.sources.clearSelection()
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 12
                Layout.rightMargin: 12
                Layout.bottomMargin: 8
                SplatComboBox {
                    objectName: "sourceSectionPicker"
                    model: page.vm.state.sourceSections
                    textRole: "label"
                    valueRole: "value"
                    selectedValue: page.vm.state.sourceSection
                    Layout.preferredWidth: Math.min(340, page.width * 0.42)
                    Accessible.name: "Browse source group or captured device"
                    onActivated: page.vm.setSourceSection(currentValue)
                }
                SplatLabel {
                    objectName: "sourceSectionSummary"
                    text: page.vm.state.sourceSectionSummary
                    color: Theme.secondary
                    font.pixelSize: Theme.small
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    wrapMode: Text.NoWrap
                }
                SplatButton {
                    objectName: "sourceGroups"
                    text: "Groups…"
                    enabled: page.vm.state.canMutate && page.vm.state.groupsSupported
                    onClicked: { groups.mode = "manage"; groups.open(); }
                    Accessible.description: "Create, rename, delete groups or move the selected source"
                }
            }
            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true
                ColumnLayout {
                    anchors.centerIn: parent
                    width: Math.min(parent.width - 32, 520)
                    visible: page.vm.sources.count === 0
                    SplatLabel {
                        objectName: "participationEmptyState"
                        text: page.vm.state.sourceSection !== "" ? "No sources in this group for this filter."
                              : page.vm.state.sourceFilter === "Excluded" ? "No excluded sources."
                              : "All sources are excluded from processing."
                        font.pixelSize: Theme.section
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
                    }
                    SplatLabel {
                        visible: page.vm.state.sourceFilter === "Included" && page.vm.state.sourceSection === ""
                        text: "Restore sources to use them in Prepare Data."
                        color: Theme.secondary
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
                    }
                    SplatButton {
                        objectName: "viewExcluded"
                        visible: page.vm.state.sourceFilter === "Included" && page.vm.state.sourceSection === ""
                        text: "View Excluded"
                        Layout.alignment: Qt.AlignHCenter
                        onClicked: page.vm.setSourceFilter("Excluded")
                    }
                }
                Repeater {
                    model: 2
                    delegate: Loader {
                        required property int index
                        property bool visited: false
                        readonly property bool current: page.populated
                            && page.vm.state.page === 1
                            && (page.vm.state.sourceView === "Grid" ? index === 1 : index === 0)
                        anchors.fill: parent
                        active: visited || current
                        visible: current && page.vm.sources.count > 0
                        onCurrentChanged: { if (current) visited = true; }
                        Component.onCompleted: { if (current) visited = true; }
                        sourceComponent: index === 0 ? listBrowser : gridBrowser
                    }
                }
            }
        }
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
                    padding: 12
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
                    id: source
                    required property var record
                    required property string recordId
                    required property bool sourceSelected
                    width: sources.width
                    height: 76
                    hoverEnabled: true
                    focusPolicy: Qt.StrongFocus
                    objectName: "source-" + recordId
                    Accessible.name: record.filename + ", " + record.description + ", " + record.availability + ", " + (record.participationLabel || "Included")
                    onClicked: page.vm.media.activateSource(recordId)
                    onDoubleClicked: {
                        if (record.type === "photo") page.vm.media.previewSource(recordId);
                        else { page.vm.media.selectSource(source.recordId); details.open(); }
                    }
                    background: Rectangle {
                        color: source.sourceSelected ? Theme.selection :
                               source.hovered ? Theme.hover : "transparent"
                        border.width: source.visualFocus || source.sourceSelected ? 2 : 0
                        border.color: Theme.accent
                    }
                    contentItem: RowLayout {
                        spacing: 16
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            SplatLabel {
                                text: source.record.filename
                                font.weight: Font.DemiBold
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                                wrapMode: Text.NoWrap
                            }
                            SplatLabel {
                                text: (source.record.device || "Unknown device") + " · " + source.record.description
                                color: Theme.secondary
                                font.pixelSize: Theme.small
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                                wrapMode: Text.NoWrap
                            }
                            SplatLabel {
                                visible: source.record.isIncluded === false
                                text: source.record.participationLabel || "Excluded from processing"
                                color: Theme.secondary
                                font.pixelSize: Theme.caption
                            }
                        }
                        SourceAvailability {
                            record: source.record
                            Layout.preferredWidth: implicitWidth
                            Layout.maximumWidth: 172
                        }
                        SourceActions {
                            vm: page.vm
                            record: source.record
                            sourceId: source.recordId
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
                if (currentIndex >= 0) positionViewAtIndex(currentIndex, GridView.Contain);
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
                    if (record.type === "photo") page.vm.media.previewSource(recordId);
                    else { page.vm.media.selectSource(tile.recordId); details.open(); }
                }
                background: Rectangle {
                    color: tile.sourceSelected ? Theme.selection :
                           tile.hovered ? Theme.hover : Theme.surface
                    radius: Theme.radius
                    border.color: tile.visualFocus || tile.sourceSelected ? Theme.accent : Theme.border
                    border.width: tile.visualFocus || tile.sourceSelected ? 2 : 1
                }
                contentItem: ColumnLayout {
                    spacing: 4
                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.minimumHeight: 36
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
    SplatLabel {
        id: videoHint
        visible: page.populated && page.vm.state.sourcesSummary.videos > 0
        text: "Frames from included videos will be extracted during Prepare Data."
        color: Theme.secondary
        font.pixelSize: Theme.small
        Layout.fillWidth: true
    }
    RowLayout {
        id: footer
        Layout.fillWidth: true
        SplatLabel {
            text: page.populated
                  ? "Sources are saved. Prepare Data is not available yet."
                  : "Add photos or videos to get started."
            color: Theme.secondary
            Layout.fillWidth: true
        }
        SplatButton {
            objectName: "sourcesContinue"
            text: "Continue →"
            enabled: false
            Accessible.description: "Prepare Data is not available yet"
        }
    }
    SourceDetailsDialog {
        id: details
        vm: page.vm
    }
    Connections {
        target: page.vm
        function onDialogRequested(name: string) {
            if (name === "closeSourceDetails") { details.close(); groups.close(); }
        }
    }
    SourceGroupsDialog { id: groups; vm: page.vm }
    Shortcut {
        sequence: StandardKey.SelectAll
        enabled: page.vm.state.page === 1 && !details.visible && !groups.visible
                 && page.vm.media.state.previewIndex === 0
        onActivated: page.vm.sources.selectAllVisible()
    }
    Connections {
        target: page.vm.sources
        function onSelectionChanged() {
            if (page.vm.sources.selectedId === "") details.close();
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
}

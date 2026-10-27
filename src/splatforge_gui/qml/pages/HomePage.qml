pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../theme"
import "../components"

ColumnLayout {
    id: page
    required property var vm
    signal newProject
    signal openProject
    spacing: 24
    SplatPageHeader {
        Layout.fillWidth: true
        title: page.vm.state.hasProject ? page.vm.state.project.name : "SplatForge"
        subtitle: page.vm.state.hasProject ? "Project overview" :
                                             "Create a project or open an existing one."
        SplatButton {
            text: "Open Existing Project"
            objectName: "openExistingProject"
            iconName: "folder"
            onClicked: page.openProject()
        }
        SplatButton {
            text: "New Project"
            objectName: "newProject"
            iconName: "plus"
            kind: page.vm.state.hasProject ? "secondary" : "primary"
            onClicked: page.newProject()
        }
    }
    SplatBanner {
        visible: page.vm.state.unresolved
        Layout.fillWidth: true
        text: "Recovery required. An interrupted operation needs your attention before processing can continue."
        action: "Review recovery"
        onActivated: page.vm.navigate(6)
    }
    SplatCard {
        visible: page.vm.state.hasProject
        Layout.fillWidth: true
        implicitHeight: 156
        RowLayout {
            anchors.fill: parent
            spacing: 24
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 10
                SplatLabel {
                    text: "NEXT IN YOUR WORKFLOW"
                    color: Theme.accent
                    font.pixelSize: Theme.caption
                    font.letterSpacing: 1.5
                }
                SplatLabel {
                    text: page.vm.state.project.nextTitle || "Start with your captures"
                    font.pixelSize: Theme.section
                    font.weight: Font.DemiBold
                }
                SplatLabel {
                    text: page.vm.state.project.sourceCount > 0
                          ? "Review your published workflow below. Plan verifies the exact inputs, methods and runtime before execution." :
                            "Add perspective photos or video. Originals stay as read-only references."
                    color: Theme.secondary
                    Layout.fillWidth: true
                }
            }
            SplatButton {
                text: page.vm.state.project.nextAction || "Add sources"
                iconName: "arrow"
                kind: "primary"
                onClicked: page.vm.navigate(page.vm.state.project.nextPage || 1)
            }
        }
    }
    WorkflowStrip {
        visible: page.vm.state.hasProject
        Layout.fillWidth: true
        implicitHeight: 158
        stages: page.vm.state.project.workflow || []
        onActivated: p => page.vm.navigate(p)
    }
    RowLayout {
        visible: page.vm.state.hasProject
        spacing: 16
        MetricCard {
            Layout.fillWidth: true
            label: "Source media"
            value: String(page.vm.state.project.sourceCount || 0)
            detail: "Originals referenced"
        }
        MetricCard {
            Layout.fillWidth: true
            label: "Published artifacts"
            value: String(page.vm.state.project.artifactCount || 0)
            detail: "Immutable project outputs"
        }
        MetricCard {
            Layout.fillWidth: true
            label: "Validation"
            value: (page.vm.state.project.validation || "not_started").replace(/_/g, " ")
            detail: "Latest recorded report"
        }
    }
    SplatCard {
        visible: page.vm.state.hasProject && !!page.vm.state.project.latestId
        Layout.fillWidth: true
        implicitHeight: 100
        RowLayout {
            anchors.fill: parent
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 8
                SplatLabel {
                    text: "LATEST PUBLISHED OUTPUT"
                    color: Theme.muted
                    font.pixelSize: Theme.caption
                    font.letterSpacing: 1
                }
                SplatLabel {
                    text: page.vm.state.project.latestTitle || ""
                    font.pixelSize: Theme.section
                    font.weight: Font.DemiBold
                }
            }
            SplatButton {
                text: "Inspect result"
                iconName: "arrow"
                onClicked: {
                    page.vm.navigate(5);
                    page.vm.inspection.inspectArtifact(page.vm.state.project.latestId);
                }
            }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        SplatLabel {
            text: page.vm.state.hasProject ? "Project location" : "Recent Projects"
            font.pixelSize: Theme.section
            font.weight: Font.DemiBold
            Layout.fillWidth: true
        }
        SplatLabel {
            text: page.vm.state.hasProject ? "LOCAL PROJECT" : "ON THIS MACHINE"
            font.pixelSize: Theme.caption
            color: Theme.muted
            font.letterSpacing: 1
        }
    }
    SplatCard {
        visible: page.vm.state.hasProject
        Layout.fillWidth: true
        implicitHeight: 72
        RowLayout {
            anchors.fill: parent
            SplatLabel {
                text: page.vm.state.project.path || ""
                font.family: Theme.mono
                color: Theme.secondary
                Layout.fillWidth: true
                elide: Text.ElideMiddle
                wrapMode: Text.NoWrap
            }
            SplatButton {
                text: "Copy path"
                kind: "ghost"
                onClicked: page.vm.copyText(page.vm.state.project.path)
            }
        }
    }
    SplatEmptyState {
        visible: !page.vm.state.hasProject && page.vm.state.recents.length === 0
        Layout.fillWidth: true
        implicitHeight: 190
        title: "A fresh perspective starts here"
        detail: "Create your first project, or open an existing SplatForge workspace."
        iconName: "folder"
    }
    ListView {
        visible: !page.vm.state.hasProject && count > 0
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(contentHeight, 360)
        model: page.vm.state.recents
        spacing: 8
        clip: true
        delegate: SplatCard {
            id: recent
            required property var modelData
            width: ListView.view.width
            height: 86
            padding: 16
            RowLayout {
                anchors.fill: parent
                SplatButton {
                    iconName: "folder"
                    kind: "ghost"
                    enabled: false
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    SplatLabel {
                        text: recent.modelData.name
                        font.weight: Font.DemiBold
                    }
                    SplatLabel {
                        text: recent.modelData.available ? recent.modelData.summary + " · "
                                                           + recent.modelData.path :
                                                           "Unavailable · " + recent.modelData.path
                        color: Theme.muted
                        font.pixelSize: Theme.small
                        Layout.fillWidth: true
                        elide: Text.ElideMiddle
                        wrapMode: Text.NoWrap
                    }
                }
                SplatButton {
                    text: "Remove"
                    kind: "ghost"
                    onClicked: page.vm.removeRecent(recent.modelData.path)
                }
                SplatButton {
                    text: "Open"
                    objectName: "openRecentProject"
                    iconName: "arrow"
                    enabled: recent.modelData.available && !page.vm.state.busy
                    onClicked: page.vm.openProject(recent.modelData.path)
                }
            }
        }
    }
}

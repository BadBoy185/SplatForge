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
    RecentProjects {
        vm: page.vm
        Layout.fillWidth: true
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
}

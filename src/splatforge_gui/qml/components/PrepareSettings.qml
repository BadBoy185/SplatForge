pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../theme"

ColumnLayout {
    id: panel
    objectName: "prepareSettings"
    required property var api
    readonly property var formState: api.state
    readonly property var fields: formState.fields || ({})
    readonly property bool sharpest: fields.method === "sharpest_interval"
    readonly property bool videoActive: formState.hasVideo === true
    readonly property bool editable: formState.canEdit === true
    readonly property int activeFilters: sharpest
        ? (fields.min_sharpness_enabled ? 1 : 0) + (videoActive && fields.reject_duplicates ? 1 : 0)
        : 0
    property bool optionsOpen: false
    spacing: Theme.space

    component SettingField: ColumnLayout {
        id: fieldControl
        required property string fieldName
        required property string label
        property bool editable: true
        spacing: Theme.spaceSmall
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        SplatLabel {
            text: fieldControl.label
            color: Theme.secondary
            font.pixelSize: Theme.small
            Layout.fillWidth: true
        }
        SplatTextField {
            objectName: "prepareSetting_" + fieldControl.fieldName
            text: String(panel.fields[fieldControl.fieldName] ?? "")
            enabled: panel.editable && fieldControl.editable
            Accessible.name: fieldControl.label
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            onTextEdited: panel.api.setField(fieldControl.fieldName, text)
        }
    }

    SplatLabel {
        objectName: "prepareSettingsContext"
        text: panel.videoActive
            ? "Settings for the next prepared set"
            : panel.formState.videoCount > 0
              ? "No video has used footage. Photos use no time sampling or video similarity filter."
              : "Photos use no time sampling or video similarity filter. Video settings are retained."
        color: Theme.secondary
        font.pixelSize: Theme.small
        Layout.fillWidth: true
    }
    SplatLabel {
        text: "Frame selection"
        color: Theme.secondary
        font.pixelSize: Theme.small
        Layout.fillWidth: true
    }
    SplatComboBox {
        objectName: "prepareSetting_method"
        model: [
            { label: "Fixed interval", value: "fixed_fps" },
            { label: "Sharpest per interval", value: "sharpest_interval" }
        ]
        textRole: "label"
        valueRole: "value"
        selectedValue: panel.fields.method
        enabled: panel.editable
        Accessible.name: "Frame selection method"
        Layout.fillWidth: true
        onActivated: panel.api.setField("method", currentValue)
    }
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.space
        SettingField {
            fieldName: "interval_seconds"
            label: "One frame every · seconds"
            editable: panel.videoActive
        }
        SettingField {
            fieldName: "candidate_fps"
            label: "Candidate frames / second"
            editable: panel.videoActive
        }
    }
    SplatLabel {
        objectName: "prepareSetting_targetFps"
        text: panel.videoActive
            ? "Target: " + (panel.formState.targetFps || "—") + " fps · "
              + (panel.sharpest ? "Candidates ≥ 2 × target. Compare candidates and keep the sharpest per interval."
                                : "Candidates ≥ target. Uniform sampling from the candidate pool.")
            : "Time controls apply only to video with used footage."
        color: Theme.secondary
        font.pixelSize: Theme.small
        Layout.fillWidth: true
    }
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.space
        ColumnLayout {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            spacing: Theme.spaceSmall
            SplatLabel { text: "Image format"; color: Theme.secondary; font.pixelSize: Theme.small }
            SplatComboBox {
                objectName: "prepareSetting_image_format"
                model: [{ label: "JPEG", value: "jpeg" }, { label: "PNG", value: "png" }]
                textRole: "label"
                valueRole: "value"
                selectedValue: panel.fields.image_format
                enabled: panel.editable
                Accessible.name: "Prepared image format"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                onActivated: panel.api.setField("image_format", currentValue)
            }
        }
        SettingField {
            visible: panel.fields.image_format === "jpeg"
            fieldName: "jpeg_qscale"
            label: "JPEG qscale · 1–31"
        }
        SettingField {
            visible: panel.fields.image_format === "png"
            fieldName: "png_compression_level"
            label: "PNG compression · 0–9"
        }
    }
    SplatLabel {
        text: (panel.fields.image_format === "jpeg" ? "Lower qscale keeps more detail. " : "")
              + "Sampling density does not guarantee reconstruction quality."
        color: Theme.secondary
        font.pixelSize: Theme.small
        Layout.fillWidth: true
    }
    SplatButton {
        objectName: "togglePrepareOptions"
        text: (panel.optionsOpen ? "▾ " : "▸ ") + "Filters and analysis · "
              + (panel.sharpest ? panel.activeFilters + " active" : "inactive for Fixed")
        kind: "ghost"
        Layout.fillWidth: true
        Accessible.name: "Show filters and analysis settings"
        Accessible.expanded: panel.optionsOpen
        onClicked: panel.optionsOpen = !panel.optionsOpen
    }
    ColumnLayout {
        visible: panel.optionsOpen
        Layout.fillWidth: true
        spacing: Theme.space
        SplatLabel {
            visible: !panel.sharpest
            text: "These filters require Sharpest per interval. Fixed interval does not measure image quality."
            color: Theme.secondary
            font.pixelSize: Theme.small
            Layout.fillWidth: true
        }
        SplatCheckBox {
            objectName: "prepareSetting_min_sharpness_enabled"
            text: "Minimum sharpness"
            checked: panel.fields.min_sharpness_enabled === true
            enabled: panel.editable && panel.sharpest
            Layout.fillWidth: true
            onToggled: panel.api.setField("min_sharpness_enabled", checked)
        }
        SettingField {
            fieldName: "min_sharpness"
            label: "Sharpness threshold · nonnegative"
            editable: panel.sharpest && panel.fields.min_sharpness_enabled === true
        }
        SplatLabel {
            text: "Edge variance measures sharpness, not reconstruction suitability. Enter a threshold when enabled."
            color: Theme.secondary
            font.pixelSize: Theme.small
            Layout.fillWidth: true
        }
        SplatCheckBox {
            objectName: "prepareSetting_reject_duplicates"
            text: "Suppress similar video frames"
            checked: panel.fields.reject_duplicates === true
            enabled: panel.editable && panel.sharpest && panel.videoActive
            Layout.fillWidth: true
            onToggled: panel.api.setField("reject_duplicates", checked)
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space
            SettingField {
                fieldName: "duplicate_hamming_threshold"
                label: "dHash distance · 0–64"
                editable: panel.sharpest && panel.videoActive && panel.fields.reject_duplicates === true
            }
            SettingField {
                fieldName: "duplicate_lookback"
                label: "Recent frames · 1–64"
                editable: panel.sharpest && panel.videoActive && panel.fields.reject_duplicates === true
            }
        }
        SplatLabel {
            text: "dHash checks image similarity within each video, never across sources or photos."
            color: Theme.secondary
            font.pixelSize: Theme.small
            Layout.fillWidth: true
        }
        SettingField {
            fieldName: "quality_max_side"
            label: "Analysis proxy maximum side · 64–4096 px"
            editable: panel.sharpest
        }
        SplatLabel {
            text: "Required for Sharpest analysis. This proxy does not set saved image resolution."
            color: Theme.secondary
            font.pixelSize: Theme.small
            Layout.fillWidth: true
        }
    }
}

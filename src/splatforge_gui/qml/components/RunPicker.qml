pragma ComponentBehavior: Bound
import QtQuick

SplatComboBox {
    id: control
    required property var workflow
    required property string inputKind
    model: workflow.state.choices[inputKind]
    textRole: "label"
    valueRole: "value"
    selectedValue: workflow.state.inputs[inputKind]
    onActivated: workflow.chooseInput(inputKind, currentValue)
    Accessible.name: "Published " + inputKind + " run"
}

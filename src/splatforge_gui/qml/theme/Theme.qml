pragma ComponentBehavior: Bound
pragma Singleton
import QtQuick

QtObject {
    id: theme
    property string choice: "System"
    readonly property bool dark: choice === "Dark" || (choice === "System"
                                                       && Application.styleHints.colorScheme
                                                       !== Qt.Light)
    readonly property color background: dark ? "#0b0f14" : "#f0f3f7"
    readonly property color sidebar: dark ? "#0e131a" : "#e8edf3"
    readonly property color surface: dark ? "#131922" : "#ffffff"
    readonly property color raised: dark ? "#18212b" : "#f7f9fc"
    readonly property color hover: dark ? "#1e2935" : "#e4ebf4"
    readonly property color border: dark ? "#26313d" : "#d6dfe9"
    readonly property color strong: dark ? "#354352" : "#afbfce"
    readonly property color text: dark ? "#f2f5f8" : "#182434"
    readonly property color secondary: dark ? "#a7b1bc" : "#526375"
    readonly property color muted: dark ? "#82909f" : "#607286"
    readonly property color accent: dark ? "#429bff" : "#166bcc"
    readonly property color accentHover: dark ? "#5aa9ff" : "#237bde"
    readonly property color accentPressed: dark ? "#2f88e5" : "#1259ac"
    readonly property color accentText: "#ffffff"
    readonly property color selection: dark ? "#182d44" : "#ddeafc"
    readonly property color success: dark ? "#42c982" : "#147947"
    readonly property color warning: dark ? "#e7ac43" : "#92600a"
    readonly property color danger: dark ? "#e57a84" : "#b22c41"
    readonly property string font: Qt.fontFamilies().indexOf("Segoe UI Variable") >= 0
                                   ? "Segoe UI Variable" : "Segoe UI"
    readonly property string mono: "Consolas"
    readonly property int display: 32
    readonly property int title: 26
    readonly property int section: 18
    readonly property int body: 14
    readonly property int small: 12
    readonly property int caption: 11
    readonly property int control: 36
    readonly property int row: 52
    readonly property int radius: 8
    readonly property int cardRadius: 12
    readonly property int space: 8
    readonly property int padding: 24
    readonly property int motion: 160
    function statusColor(status: string): color {
        let s = status.toLowerCase();
        if (["completed", "ready", "pass", "succeeded", "available", "verified"].indexOf(s) >= 0)
            return success;
        if (["fail", "failed", "unavailable", "error"].indexOf(s) >= 0)
            return danger;
        if (["warn", "warning", "stale", "interrupted"].indexOf(s) >= 0)
            return warning;
        if (["running", "stopping"].indexOf(s) >= 0)
            return accent;
        return muted;
    }
}

pragma ComponentBehavior: Bound
import QtQuick
import QtMultimedia

// Transient editor/transport state only. Saved ranges always come from api.state.
Item {
    id: session
    required property var api
    required property var player
    property bool active: false
    property bool trimMode: false
    property var usage: api.state
    readonly property var extent: usage.timeline || ({available: false, ranges: []})
    readonly property bool mapped: Boolean(extent.available)
    readonly property var playableRanges: mapped ? extent.ranges.filter(r => r.end > r.start) : []
    property string contextKey: ""
    property string signature: ""
    property int selectedIndex: -1
    property string startText: ""
    property string endText: ""
    property real startMs: NaN
    property real endMs: NaN
    property bool usedOnly: false
    property bool playIntent: false
    property real pendingSeek: -1
    property real seekOriginPosition: -1
    property bool scrubbing: false
    property real scrubPosition: 0
    property bool resumeAfterScrub: false
    property string playbackError: ""
    property var gesture: null
    readonly property bool rangeReady: startText !== "" && endText !== ""
    readonly property bool canPlay: !usedOnly || (mapped && playableRanges.length > 0)
    readonly property real displayPosition: scrubbing ? scrubPosition : player.position
    readonly property string playReason: usedOnly && !mapped ? extent.reason || "Time mapping is unavailable."
        : usedOnly && usage.restricted && usage.intervals.length === 0 ? "No used ranges. Include a range or use the entire clip."
        : usedOnly && playableRanges.length === 0 ? "The used ranges are shorter than the player's millisecond precision." : ""
    objectName: "videoTrimSession"

    function refresh() {
        if (!extent) return; // Initial property bindings are installed in declaration order.
        const key = usage.contextKey + ":" + usage.sourceId;
        if (key !== contextKey) {
            contextKey = key;
            pause();
            usedOnly = false;
            gesture = null;
            scrubbing = false;
            resumeAfterScrub = false;
            scrubPosition = 0;
            playbackError = "";
        }
        const next = key + ":" + JSON.stringify([usage.restricted, usage.intervals, extent]);
        if (signature === next)
            return;
        signature = next; // Conversion slots notify synchronously; guard before calling them.
        gesture = null;
        selectRange(-1);
        if (usedOnly && playIntent) {
            pause(); // Editing never leaves playback running against an obsolete range set.
        }
    }
    onUsageChanged: refresh()
    onExtentChanged: refresh()
    Component.onCompleted: refresh()
    onActiveChanged: { if (!active) { pause(); cancelGesture(); } }
    onTrimModeChanged: { if (!trimMode) { usedOnly = false; cancelGesture(); } }
    onUsedOnlyChanged: { pause(); playbackError = ""; }

    function projectRange() {
        if (!mapped) { startMs = NaN; endMs = NaN; return; }
        const a = api.playerPosition(startText);
        const b = api.playerPosition(endText);
        startMs = a === "" ? NaN : Number(a);
        endMs = b === "" ? NaN : Number(b);
    }
    function selectRange(index: int) {
        selectedIndex = index;
        const row = index >= 0 ? usage.intervals[index] : null;
        const full = usage.timeline || ({});
        startText = row ? row.start : full.start || "";
        endText = row ? row.end : full.end || "";
        const positions = index >= 0 && full.ranges ? full.ranges[index] : null;
        startMs = full.available ? positions ? positions.start : full.startPosition : NaN;
        endMs = full.available ? positions ? positions.end : full.endPosition : NaN;
    }
    function exactAt(position: real): string {
        if (!mapped) return "";
        if (position <= extent.startPosition) return extent.start;
        if (position >= extent.endPosition) return extent.end;
        return api.sourceTime(String(Math.round(position)));
    }
    function setBoundary(start: bool, position: real) {
        const value = exactAt(position);
        if (value === "") return;
        if (start) startText = value; else endText = value;
        projectRange();
    }
    function selectAfterEdit(start: string) {
        const index = api.intervalIndex(start);
        if (index >= 0) selectRange(index);
    }
    function applyBounds(): bool {
        const start = startText;
        const ok = selectedIndex >= 0 ? api.updateInterval(selectedIndex, startText, endText) : false;
        if (ok) selectAfterEdit(start);
        return ok;
    }
    function includeRange() {
        const start = startText;
        if (api.addInterval(startText, endText)) selectAfterEdit(start);
    }
    function excludeRange() {
        const start = startText, end = endText;
        if (api.excludeInterval(start, end)) {
            selectedIndex = -1; startText = start; endText = end;
            projectRange(); // Keep the excluded selection available for Include range.
        }
    }
    function beginGesture() {
        pause();
        gesture = {start: startText, end: endText, index: selectedIndex, startMs: startMs, endMs: endMs};
    }
    function finishGesture() {
        if (!gesture) return;
        gesture = null;
        if (selectedIndex >= 0) applyBounds();
    }
    function cancelGesture() {
        if (gesture) {
            const old = gesture;
            gesture = null;
            selectedIndex = old.index;
            startText = old.start; endText = old.end;
            startMs = old.startMs; endMs = old.endMs;
        } else {
            selectRange(selectedIndex);
        }
        if (scrubbing) { scrubbing = false; pause(); }
    }
    function clock(ms: real): string {
        if (!isFinite(ms)) return "—";
        const s = Math.max(0, Math.floor(ms / 1000));
        return Math.floor(s / 60).toString().padStart(2, "0") + ":"
            + (s % 60).toString().padStart(2, "0") + "."
            + Math.floor(ms % 1000).toString().padStart(3, "0");
    }
    function pause() {
        playIntent = false;
        resumeAfterScrub = false;
        scrubbing = false;
        pendingSeek = -1;
        seekDeadline.stop();
        player.pause();
    }
    function seek(position: real, resume: bool) {
        if (!active || !player.seekable) { pause(); return; }
        playbackError = "";
        playIntent = resume;
        player.pause();
        const target = Math.max(0, Math.min(player.duration, Math.round(position)));
        seekOriginPosition = player.position;
        pendingSeek = target; // Arm before setPosition: Qt may notify synchronously.
        seekDeadline.restart();
        player.setPosition(target);
        acknowledgeSeek();
    }
    function acknowledgeSeek() {
        if (pendingSeek < 0 || Math.abs(player.position - pendingSeek) > 80) return;
        if (player.position === seekOriginPosition && pendingSeek !== seekOriginPosition) return;
        if (usedOnly && playIntent) {
            const destination = playableRanges.find(r => pendingSeek >= r.start && pendingSeek < r.end);
            if (!destination || player.position < destination.start || player.position >= destination.end) return;
        }
        pendingSeek = -1;
        seekDeadline.stop();
        if (playIntent && active && !scrubbing) player.play();
    }
    function togglePlay() {
        if (playIntent || player.playbackState === MediaPlayer.PlayingState) { pause(); return; }
        if (!active || !canPlay || player.mediaStatus === MediaPlayer.NoMedia
                || player.mediaStatus === MediaPlayer.LoadingMedia
                || player.mediaStatus === MediaPlayer.InvalidMedia) return;
        playbackError = "";
        playIntent = true;
        if (usedOnly) {
            for (const r of playableRanges) {
                if (player.position >= r.start && player.position < r.end) { player.play(); return; }
                if (player.position < r.start) { seek(r.start, true); return; }
            }
            seek(playableRanges[0].start, true);
        } else if (player.mediaStatus === MediaPlayer.EndOfMedia || (player.duration > 0 && player.position >= player.duration)) {
            seek(0, true);
        } else player.play();
    }
    function positionChanged() {
        if (pendingSeek >= 0) { acknowledgeSeek(); return; }
        if (!active || !usedOnly || !playIntent || scrubbing || player.playbackState !== MediaPlayer.PlayingState) return;
        for (const r of playableRanges) {
            if (player.position >= r.start && player.position < r.end) return;
            if (player.position < r.start) { seek(r.start, true); return; }
        }
        pause();
    }
    function beginScrub(position: real) {
        const resume = playIntent || player.playbackState === MediaPlayer.PlayingState;
        pause(); scrubbing = true; scrubPosition = position; resumeAfterScrub = resume;
    }
    function endScrub() {
        if (!scrubbing) return;
        scrubbing = false;
        // Seeking stays on the original timeline. Used-only constraints apply on Play.
        let target = scrubPosition;
        if (resumeAfterScrub && usedOnly) {
            const next = playableRanges.find(r => target < r.end);
            if (next) target = Math.max(target, next.start);
            else { resumeAfterScrub = false; }
        }
        const resume = resumeAfterScrub;
        resumeAfterScrub = false;
        seek(target, resume);
    }
    Timer {
        id: seekDeadline
        interval: 2500
        onTriggered: {
            session.pause();
            session.playbackError = "The player did not confirm the seek. Press Play to try again.";
        }
    }
    Connections {
        target: session.player
        function onPositionChanged() { session.positionChanged(); }
        function onMediaStatusChanged() {
            if (session.player.mediaStatus === MediaPlayer.EndOfMedia) session.pause();
        }
        function onErrorOccurred() { session.pause(); }
    }
}

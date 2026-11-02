"""Stable-identity frame review; persistence and canonical order belong to the service."""

from fractions import Fraction
from uuid import UUID, uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot


class FrameReviewViewModel(QObject):
    changed = Signal()

    def __init__(self, preparation) -> None:
        super().__init__(preparation)
        self.preparation = preparation
        self.desktop, self.controller = preparation.desktop, preparation.controller
        self._token = ""
        self._run = ""
        self._filter = "selected"
        self._scope = "all"
        self._scopes = []
        self._page = None
        self._selected: set[str] = set()
        self._viewed = ""
        self._loading = self._saving = False
        self._error = self._message = ""
        self.controller.completed.connect(self._completed)
        self.controller.error.connect(self._failed)
        self.desktop.media.changed.connect(self.changed)

    def _items(self) -> dict:
        return {str(item.view_id): item for item in self._page.items} if self._page else {}

    @staticmethod
    def _item(item) -> dict:
        return dict(viewId=str(item.view_id), caption=item.caption,
                    autoSelected=item.auto_selected, decision=item.decision,
                    included=item.included, reason=item.reason, autoReason=item.auto_reason,
                    nextId=str(item.next_view_id) if item.next_view_id else "",
                    previousId=str(item.previous_view_id) if item.previous_view_id else "",
                    provenance=FrameReviewViewModel._provenance(getattr(item, "provenance", None)))

    @staticmethod
    def _provenance(value) -> dict:
        if value is None:
            return {}
        timestamp = value.timestamp
        time = "Not recorded" if value.media_type == "video" else "Not applicable — photo"
        exact = "Not recorded"
        if timestamp is not None and value.media_type == "video":
            seconds = timestamp.pts * Fraction(timestamp.time_base.numerator,
                                               timestamp.time_base.denominator)
            milliseconds = round(abs(seconds) * 1000)
            hours, remainder = divmod(milliseconds, 3600000)
            minutes, remainder = divmod(remainder, 60000)
            whole, fraction = divmod(remainder, 1000)
            time = f"{'−' if seconds < 0 else ''}{hours:02}:{minutes:02}:{whole:02}.{fraction:03}"
            exact = (f"PTS {timestamp.pts} · time base {timestamp.time_base.numerator}/"
                     f"{timestamp.time_base.denominator}")
        score = value.automatic_score
        score_label = (f"{score.numerator}/{score.denominator}" if score is not None
                       else "Not recorded")
        checked = value.source_checked_at
        check = (str(value.source_check).replace("_", " ") if value.source_check
                 else "No recorded check")
        if checked:
            check += " · " + checked.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        dimensions = (f"{value.width} × {value.height}"
                      if value.width is not None and value.height is not None else "Not recorded")
        stream = value.stream_index if value.stream_index is not None else "Not recorded"
        states = {
            "same_source": "Current inventory matches the prepared source identity.",
            "revision_mismatch": "Current inventory has a different source revision.",
            "not_in_inventory": "Prepared source is no longer in the current inventory.",
            "unavailable": "Current inventory evidence is unavailable.",
        }
        return dict(
            sourceName=value.source_name, mediaType=value.media_type,
            pathAtPreparation=value.path_at_preparation or "Not recorded",
            currentLocator=value.current_locator or "Not available",
            currentSourceState=states.get(value.current_source_state, "Not recorded"),
            sourceCheck=check, originalTime=time,
            dimensions=dimensions,
            device=value.device_label or "Unknown device",
            group=value.current_group_label or "Ungrouped", automaticScore=score_label,
            technical=(f"Source UUID: {value.source_id}\nSource revision: {value.source_revision}"
                       f"\nVisual stream: {stream}\n{exact}"),
        )

    @Property("QVariantMap", notify=changed)
    def state(self) -> dict:
        page, items = self._page, self._items()
        viewed = items.get(self._viewed)
        ready = bool(page and self._run and not self._loading and not self._saving
                     and self.preparation._active and self.desktop.state["canMutate"]
                     and not self.controller.dirty and not self.preparation._settings.has_unsaved)
        return dict(
            filter=self._filter, loading=self._loading, saving=self._saving,
            scope=self._scope, scopeLabel=next((v["label"] for v in self._scopes
                                              if v["key"] == self._scope), "All sources"),
            scopes=self._scopes,
            canEdit=ready,
            canEditViewed=bool(ready and viewed
                               and self.desktop.media.state["previewStatus"] == "Ready"),
            error=self._error, message=self._message,
            selectedIds=sorted(self._selected), selectedCount=len(self._selected),
            viewedId=self._viewed, viewed=self._item(viewed) if viewed else {},
            items={key: self._item(value) for key, value in items.items()},
            total=page.total if page else 0, offset=page.offset if page else 0,
            count=len(items), selectedTotal=page.selected_count if page else 0,
            rejectedTotal=page.rejected_count if page else 0,
            manualTotal=page.manual_count if page else 0,
            candidateTotal=page.candidate_count if page else 0,
            scopeCountsAvailable=bool(page and getattr(page, "scope_candidate_count", None)
                                      is not None),
            scopeCandidateTotal=getattr(page, "scope_candidate_count", None),
            scopeAutoSelectedTotal=getattr(page, "scope_auto_selected_count", None),
            scopeSelectedTotal=getattr(page, "scope_selected_count", None),
            scopeRejectedTotal=getattr(page, "scope_rejected_count", None),
            scopeManualTotal=getattr(page, "scope_manual_count", None),
            effectiveRun=str(page.effective_run_id) if page and page.effective_run_id else "",
            canPrevious=bool(ready and page.offset > 0),
            canNext=bool(ready and page.offset + len(items) < page.total),
        )

    def reset(self) -> None:
        self._token = uuid4().hex
        self._run, self._viewed = "", ""
        self._filter = "selected"
        self._scope, self._scopes = "all", []
        self._page = None
        self._selected.clear()
        self._loading = self._saving = False
        self._error = self._message = ""
        self.changed.emit()

    def deactivate(self) -> None:
        self._token = uuid4().hex
        self._loading = False
        self._selected.clear()
        self._viewed = ""
        self.desktop.media.closeReviewFrame()
        self.changed.emit()

    def invalidate(self) -> None:
        """Revoke readers when source/project intent starts changing elsewhere."""
        self.deactivate()
        self._page = None
        self.desktop.media.clearGallery()
        self.changed.emit()

    def set_run(self, run: str) -> None:
        if self._saving:
            return
        changed = run != self._run
        if changed:
            self._scope, self._scopes = "all", []
        self._run = run
        self._load(0 if changed or self._page is None else self._page.offset)

    def _load(self, offset: int, anchor: str = "", *, preview: bool = False) -> None:
        if not self.preparation._active or not self._run or self.controller.mutating:
            return
        token, root, run, filter_name, scope = (
            uuid4().hex, self.controller.root, UUID(self._run), self._filter, self._scope,
        )
        self._token = token
        self._loading, self._error = True, ""
        self._page = None
        self._selected.clear()
        self._viewed = ""
        self.desktop.media.clearGallery()

        def read(facade):
            try:
                page = facade.service("frame_review").page(
                    root, run, filter=filter_name, scope=scope, offset=offset, limit=100,
                    anchor_view_id=UUID(anchor) if anchor else None,
                )
                return token, page, "", anchor if preview else ""
            except Exception as exc:
                return token, None, str(exc), ""

        self.controller.submit("frame_review_page", read, request_token=token)
        self.changed.emit()

    @Slot(str)
    def setFilter(self, value: str) -> None:
        if value in {"selected", "rejected", "all"} and not self._saving:
            self._filter = value
            self._message = "Batch selection applies only to this page."
            self._load(0)

    @Slot(str)
    def setScope(self, value: str) -> None:
        if (self._saving or value == self._scope
                or not any(option["key"] == value for option in self._scopes)):
            return
        self._scope = value
        self._message = "View scope only. Batch selection applies only to the current page."
        self._load(0)

    @Slot()
    def previousPage(self) -> None:
        if self.state["canPrevious"]:
            self._load(max(0, self._page.offset - 100))

    @Slot()
    def nextPage(self) -> None:
        if self.state["canNext"]:
            self._load(self._page.offset + 100)

    @Slot(str, bool)
    def select(self, identity: str, selected: bool) -> None:
        if not self.state["canEdit"] or identity not in self._items():
            return
        if selected:
            self._selected.add(identity)
        else:
            self._selected.discard(identity)
        self.changed.emit()

    @Slot()
    def selectPage(self) -> None:
        if self.state["canEdit"]:
            self._selected = set(self._items())
            self.changed.emit()

    @Slot()
    def clearSelection(self) -> None:
        self._selected.clear()
        self.changed.emit()

    @Slot(str)
    def view(self, identity: str) -> None:
        if not self.state["canEdit"] or identity not in self._items():
            return
        self._viewed = identity
        self.desktop.media.showReviewFrame(identity)
        self.changed.emit()

    @Slot()
    def close(self) -> None:
        if self._saving:
            return
        self._viewed = ""
        self.desktop.media.closeReviewFrame()
        self.changed.emit()

    @Slot(int)
    def step(self, direction: int) -> None:
        if not self.state["canEdit"]:
            return
        item = self._items().get(self._viewed)
        identity = (item.next_view_id if direction > 0 else item.previous_view_id) if item else None
        if identity:
            if str(identity) in self._items():
                self.view(str(identity))
            else:
                self._load(self._page.offset, str(identity), preview=True)

    @Slot(str, str)
    def applyFrame(self, identity: str, decision: str) -> None:
        if identity == self._viewed and not self.state["canEditViewed"]:
            return
        self._apply((identity,), decision, advance=identity == self._viewed)

    @Slot(str)
    def applyBatch(self, decision: str) -> None:
        self._apply(tuple(sorted(self._selected)), decision)

    def _apply(self, identities: tuple[str, ...], decision: str, *, advance=False) -> None:
        if (not self.state["canEdit"] or decision not in {"automatic", "exclude", "include"}
                or not identities or not set(identities).issubset(self._items())):
            return
        page = self._page
        viewed = self._items().get(self._viewed)
        anchor = self._viewed
        if advance and decision == "exclude" and viewed:
            neighbor = viewed.next_view_id or viewed.previous_view_id
            anchor = str(neighbor) if neighbor else ""
        token, root, run, filter_name, scope = (
            uuid4().hex, self.controller.root, UUID(self._run), self._filter, self._scope,
        )
        self._token = token
        self._saving, self._error, self._message = True, "", "Saving frame decisions…"
        self.desktop.media.closeReviewFrame()
        self.desktop.media.gallery.set_active(False)
        ids = tuple(UUID(identity) for identity in identities)

        def save(facade):
            try:
                service = facade.service("frame_review")
                service.apply(root, run, ids, decision,
                              expected_project_id=page.project_id,
                              expected_revision=page.project_revision,
                              expected_review_digest=page.review_digest)
                confirmed = service.page(root, run, filter=filter_name, scope=scope,
                                         offset=page.offset,
                                         limit=100, anchor_view_id=UUID(anchor) if anchor else None)
                return token, confirmed, "", anchor
            except Exception as exc:
                return token, None, str(exc), ""

        if not self.controller.apply_frame_review(save, self.preparation._readers_ready,
                                                  request_token=token):
            self._saving = False
            self._message = ""
            self._error = "The project is busy. Wait for active work to finish, then retry."
            self.desktop.media.gallery.set_active(True)
        self.changed.emit()

    def _completed(self, name, value) -> None:
        if name not in {"frame_review_page", "frame_review_apply"}:
            return
        token, page, error, anchor = value
        if token != self._token or not self.preparation._active:
            return
        document = self.controller.overview.document if self.controller.overview else None
        if (page and name == "frame_review_page" and
                (not document or page.project_id != document.project_id
                 or page.project_revision != document.revision or str(page.run_id) != self._run)):
            page, error = None, "Project changed while frames were loading. Reload saved sets."
        self._loading = self._saving = False
        self.desktop.media.gallery.set_active(True)
        self._error = error
        if error:
            self._page = None
            self._viewed = ""
            self._selected.clear()
            self.desktop.media.clearGallery()
            self._message = ("Save was not confirmed. Reload saved sets before retrying."
                             if name == "frame_review_apply" else
                             "Prepared frames could not be loaded. Reload saved sets to retry.")
        else:
            self._page = page
            self._scopes = [dict(key=v.key, label=v.label, kind=v.kind,
                                 sourceCount=v.source_count, candidateCount=v.candidate_count,
                                 selectedCount=v.selected_count, rejectedCount=v.rejected_count,
                                 caption=f"{v.label} · {v.candidate_count} candidates")
                            for v in getattr(page, "scopes", ())]
            self._selected.clear()
            self._viewed = ""
            self.desktop.media.setReviewGallery(self._run, page.offset, page.items)
            if anchor in self._items():
                self._viewed = anchor
                self.desktop.media.showReviewFrame(anchor)
            self._message = ("Frame decisions saved." if name == "frame_review_apply"
                             else "Batch selection applies only to this page.")
        self.changed.emit()

    def _failed(self, error) -> None:
        # Service results and executor/factory failures share the same correlation.
        if (error.stage not in {"frame_review_page", "frame_review_apply"}
                or getattr(error, "request_token", None) != self._token):
            return
        if self.preparation._active:
            self._loading = self._saving = False
            self._page = None
            self._selected.clear()
            self._viewed = ""
            self._error = error.message
            self.desktop.media.clearGallery()
            self.desktop.media.gallery.set_active(True)
            self.changed.emit()

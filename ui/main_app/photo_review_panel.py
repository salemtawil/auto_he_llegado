from __future__ import annotations

import threading
import tkinter as tk

import customtkinter as ctk

from services.photo_review_service import PhotoCandidateRecord, PhotoReviewService, PhotoReviewSnapshot
from ui.theme import (
    ACCENT,
    ACCENT_HOVER,
    BORDER,
    CARD_ALT_BG,
    CARD_BG,
    ERROR,
    NEUTRAL_BUTTON,
    NEUTRAL_BUTTON_HOVER,
    SUCCESS,
    TEXT_MUTED,
    TEXT_PRIMARY,
    WARNING,
)


class PhotoReviewPanel(ctk.CTkFrame):
    STATUS_OPTIONS = ["pending", "approved", "rejected", "deleted", "all"]
    DISPLAY_BATCH_SIZE = 180

    def __init__(
        self,
        master,
        *,
        review_service: PhotoReviewService | None = None,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._review_service = review_service or PhotoReviewService()
        self._snapshot: PhotoReviewSnapshot | None = None
        self._images: list[tk.PhotoImage] = []
        self._selected_candidate_ids: set[str] = set()
        self._is_loading = False
        self._render_generation = 0
        self._display_limit = self.DISPLAY_BATCH_SIZE
        self._rendered_candidates: list[PhotoCandidateRecord] = []

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build_header()
        self._build_summary()
        self._build_grid()
        self.refresh()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(
            self,
            fg_color=CARD_BG,
            corner_radius=18,
            border_width=1,
            border_color=BORDER,
        )
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=0)
        header.grid_columnconfigure(2, weight=0)

        ctk.CTkLabel(
            header,
            text="Revision de fotos",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=(16, 12), pady=(14, 4), sticky="w")

        ctk.CTkLabel(
            header,
            text="Aprueba las fotos que pasan al pool o elimina las que no sirven.",
            text_color=TEXT_MUTED,
            justify="left",
        ).grid(row=1, column=0, padx=(16, 12), pady=(0, 14), sticky="w")

        self.status_menu = ctk.CTkOptionMenu(
            header,
            values=self.STATUS_OPTIONS,
            command=lambda _value: self._reset_filter_and_refresh(),
            width=140,
        )
        self.status_menu.set("pending")
        self.status_menu.grid(row=0, column=1, rowspan=2, padx=(12, 8), pady=14, sticky="e")

        self.refresh_button = ctk.CTkButton(
            header,
            text="Refrescar",
            command=self.refresh,
            height=36,
            corner_radius=12,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        )
        self.refresh_button.grid(row=0, column=2, rowspan=2, padx=(8, 16), pady=14, sticky="e")

        bulk_actions = ctk.CTkFrame(header, fg_color="transparent")
        bulk_actions.grid(row=2, column=0, columnspan=3, padx=16, pady=(0, 14), sticky="ew")
        bulk_actions.grid_columnconfigure(4, weight=1)

        self.select_visible_button = ctk.CTkButton(
            bulk_actions,
            text="Seleccionar visibles",
            command=self._select_visible_pending,
            height=32,
            corner_radius=10,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        )
        self.select_visible_button.grid(row=0, column=0, padx=(0, 8), sticky="w")

        self.clear_selection_button = ctk.CTkButton(
            bulk_actions,
            text="Limpiar seleccion",
            command=self._clear_selection,
            height=32,
            corner_radius=10,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        )
        self.clear_selection_button.grid(row=0, column=1, padx=(0, 8), sticky="w")

        self.approve_selected_button = ctk.CTkButton(
            bulk_actions,
            text="Aprobar seleccionadas",
            command=lambda: self._run_bulk_action("approve"),
            height=32,
            corner_radius=10,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            state="disabled",
        )
        self.approve_selected_button.grid(row=0, column=2, padx=(0, 8), sticky="w")

        self.delete_selected_button = ctk.CTkButton(
            bulk_actions,
            text="Eliminar seleccionadas",
            command=lambda: self._run_bulk_action("delete"),
            height=32,
            corner_radius=10,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
            state="disabled",
        )
        self.delete_selected_button.grid(row=0, column=3, sticky="w")

        self.bulk_progress_label = ctk.CTkLabel(
            bulk_actions,
            text="",
            text_color=TEXT_MUTED,
            anchor="e",
        )
        self.bulk_progress_label.grid(row=0, column=5, padx=(12, 0), sticky="e")

        self.bulk_progress_bar = ctk.CTkProgressBar(bulk_actions, height=8, corner_radius=999)
        self.bulk_progress_bar.grid(row=1, column=0, columnspan=6, pady=(10, 0), sticky="ew")
        self.bulk_progress_bar.set(0)
        self.bulk_progress_bar.grid_remove()

        self.load_more_button = ctk.CTkButton(
            bulk_actions,
            text="Mostrar mas",
            command=self._show_more_candidates,
            height=32,
            corner_radius=10,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        )
        self.load_more_button.grid(row=2, column=0, padx=(0, 8), pady=(10, 0), sticky="w")
        self.load_more_button.grid_remove()

    def _build_summary(self) -> None:
        summary = ctk.CTkFrame(self, fg_color="transparent")
        summary.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        for column in range(4):
            summary.grid_columnconfigure(column, weight=1)
        self.pending_box = self._summary_box(summary, "Pendientes", "--", WARNING, column=0)
        self.approved_box = self._summary_box(summary, "Aprobadas", "--", SUCCESS, column=1)
        self.rejected_box = self._summary_box(summary, "Rechazadas", "--", ERROR, column=2)
        self.status_box = self._summary_box(summary, "Estado", "Sin cargar", TEXT_MUTED, column=3)

    def _summary_box(self, master, title: str, value: str, color, *, column: int):
        box = ctk.CTkFrame(
            master,
            fg_color=CARD_BG,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
        )
        box.grid(row=0, column=column, padx=(0 if column == 0 else 8, 0), sticky="ew")
        ctk.CTkLabel(
            box,
            text=title,
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=11, weight="bold"),
        ).grid(row=0, column=0, padx=12, pady=(10, 0), sticky="w")
        value_label = ctk.CTkLabel(
            box,
            text=value,
            text_color=color,
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        value_label.grid(row=1, column=0, padx=12, pady=(0, 10), sticky="w")
        return value_label

    def _build_grid(self) -> None:
        self.scroll = ctk.CTkScrollableFrame(
            self,
            fg_color=CARD_ALT_BG,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
        )
        self.scroll.grid(row=2, column=0, sticky="nsew")
        for column in range(3):
            self.scroll.grid_columnconfigure(column, weight=1)

    def refresh(self) -> None:
        if self._is_loading:
            return
        status = self.status_menu.get()
        self._is_loading = True
        self.refresh_button.configure(state="disabled", text="Cargando...")
        self.status_box.configure(text="Cargando")
        threading.Thread(target=lambda: self._refresh_worker(status), daemon=True).start()

    def _refresh_worker(self, status: str) -> None:
        try:
            snapshot = self._review_service.list_review_snapshot(
                status=status,
                limit=None,
            )
            self.after(0, lambda: self._apply_snapshot(snapshot))
        except Exception as exc:
            self.after(0, lambda error=exc: self._show_error(error))

    def _apply_snapshot(self, snapshot: PhotoReviewSnapshot) -> None:
        self._snapshot = snapshot
        self._selected_candidate_ids.clear()
        self._display_limit = self.DISPLAY_BATCH_SIZE
        self._is_loading = False
        self.refresh_button.configure(state="normal", text="Refrescar")
        self.bulk_progress_label.configure(text="")
        self.bulk_progress_bar.grid_remove()
        self.pending_box.configure(text=str(snapshot.pending_count))
        self.approved_box.configure(text=str(snapshot.approved_count))
        self.rejected_box.configure(text=str(snapshot.rejected_count))
        self.status_box.configure(text=self._status_summary(snapshot))
        self._sync_bulk_buttons()
        self._render_candidates(snapshot.candidates)

    def _status_summary(self, snapshot: PhotoReviewSnapshot) -> str:
        status = self.status_menu.get()
        rendered = min(len(snapshot.candidates), self._display_limit)
        if status == "pending":
            return f"{rendered}/{len(snapshot.candidates)} pendientes"
        return f"{rendered}/{len(snapshot.candidates)} fotos"

    def _render_candidates(self, candidates: list[PhotoCandidateRecord]) -> None:
        self._render_generation += 1
        generation = self._render_generation
        for child in self.scroll.winfo_children():
            child.destroy()
        self._images.clear()
        visible_candidates = candidates[: self._display_limit]
        self._rendered_candidates = list(visible_candidates)
        self._update_load_more_button(len(candidates), len(visible_candidates))
        if not candidates:
            ctk.CTkLabel(
                self.scroll,
                text="No hay fotos para este filtro.",
                text_color=TEXT_MUTED,
            ).grid(row=0, column=0, padx=16, pady=16, sticky="w")
            return

        for index, candidate in enumerate(visible_candidates):
            row = index // 3
            column = index % 3
            self._candidate_card(candidate).grid(
                row=row,
                column=column,
                padx=8,
                pady=8,
                sticky="nsew",
            )
        threading.Thread(
            target=lambda current_generation=generation, current_candidates=list(visible_candidates): self._thumbnail_loader_worker(
                current_candidates,
                current_generation,
            ),
            daemon=True,
        ).start()
        self._sync_bulk_buttons()

    def _candidate_card(self, candidate: PhotoCandidateRecord) -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            self.scroll,
            fg_color=CARD_BG,
            corner_radius=12,
            border_width=1,
            border_color=BORDER,
        )
        card.grid_columnconfigure(0, weight=1)
        card._candidate_id = candidate.id
        selected_var = tk.BooleanVar(value=candidate.id in self._selected_candidate_ids)

        image_label = ctk.CTkLabel(card, text="Cargando miniatura...", text_color=TEXT_MUTED, height=150)
        image_label.grid(row=0, column=0, padx=10, pady=(10, 8), sticky="ew")

        checkbox = ctk.CTkCheckBox(
            card,
            text="Seleccionar",
            variable=selected_var,
            command=lambda current=candidate, var=selected_var: self._toggle_candidate_selection(current, var),
            checkbox_width=18,
            checkbox_height=18,
            text_color=TEXT_PRIMARY,
            state="normal" if candidate.status == "pending" else "disabled",
        )
        checkbox.grid(row=1, column=0, padx=10, pady=(0, 6), sticky="w")

        meta = (
            f"{candidate.status} | frame {candidate.frame_index}\n"
            f"{candidate.timestamp_seconds:.1f}s | blur {candidate.blur_score or 0:.1f} | luz {candidate.brightness_score or 0:.1f}"
        )
        ctk.CTkLabel(
            card,
            text=meta,
            text_color=TEXT_MUTED,
            justify="left",
            font=ctk.CTkFont(size=11),
        ).grid(row=2, column=0, padx=10, pady=(0, 8), sticky="w")

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(row=3, column=0, padx=10, pady=(0, 10), sticky="ew")
        actions.grid_columnconfigure(0, weight=1)
        actions.grid_columnconfigure(1, weight=1)
        enabled_state = "normal" if candidate.status == "pending" else "disabled"

        ctk.CTkButton(
            actions,
            text="Aprobar",
            command=lambda current=candidate: self._run_action("approve", current),
            height=32,
            corner_radius=10,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            state=enabled_state,
        ).grid(row=0, column=0, padx=(0, 6), sticky="ew")

        ctk.CTkButton(
            actions,
            text="Eliminar",
            command=lambda current=candidate: self._run_action("delete", current),
            height=32,
            corner_radius=10,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
            state=enabled_state,
        ).grid(row=0, column=1, padx=(6, 0), sticky="ew")
        return card

    def _thumbnail_loader_worker(self, candidates: list[PhotoCandidateRecord], generation: int) -> None:
        for candidate in candidates:
            if generation != self._render_generation:
                return
            try:
                thumbnail_path = self._review_service.get_thumbnail_path(candidate)
            except Exception:
                self.after(0, lambda current_id=candidate.id, current_generation=generation: self._apply_thumbnail_error(current_id, current_generation))
                continue
            self.after(
                0,
                lambda current_id=candidate.id, current_path=thumbnail_path, current_generation=generation: self._apply_thumbnail(
                    current_id,
                    current_path,
                    current_generation,
                ),
            )

    def _apply_thumbnail(self, candidate_id: str, thumbnail_path, generation: int) -> None:
        if generation != self._render_generation:
            return
        card = self._find_candidate_card(candidate_id)
        if card is None:
            return
        try:
            image = tk.PhotoImage(file=str(thumbnail_path))
            self._images.append(image)
            label = card.grid_slaves(row=0, column=0)[0]
            label.configure(image=image, text="")
        except Exception:
            self._apply_thumbnail_error(candidate_id, generation)

    def _apply_thumbnail_error(self, candidate_id: str, generation: int) -> None:
        if generation != self._render_generation:
            return
        card = self._find_candidate_card(candidate_id)
        if card is None:
            return
        try:
            label = card.grid_slaves(row=0, column=0)[0]
            label.configure(text="Sin miniatura", image=None, text_color=TEXT_MUTED)
        except Exception:
            return

    def _find_candidate_card(self, candidate_id: str):
        for child in self.scroll.winfo_children():
            if getattr(child, "_candidate_id", None) == candidate_id:
                return child
        return None

    def _run_action(self, action: str, candidate: PhotoCandidateRecord) -> None:
        self.status_box.configure(text="Procesando")
        threading.Thread(
            target=lambda: self._action_worker(action, candidate),
            daemon=True,
        ).start()

    def _toggle_candidate_selection(self, candidate: PhotoCandidateRecord, selected_var) -> None:
        if candidate.status != "pending":
            selected_var.set(False)
            return
        if selected_var.get():
            self._selected_candidate_ids.add(candidate.id)
        else:
            self._selected_candidate_ids.discard(candidate.id)
        self._sync_bulk_buttons()

    def _select_visible_pending(self) -> None:
        snapshot = self._snapshot
        if snapshot is None:
            return
        self._selected_candidate_ids = {
            candidate.id
            for candidate in self._rendered_candidates
            if candidate.status == "pending"
        }
        self._render_candidates(snapshot.candidates)

    def _clear_selection(self) -> None:
        self._selected_candidate_ids.clear()
        if self._snapshot is not None:
            self._render_candidates(self._snapshot.candidates)
        self._sync_bulk_buttons()

    def _sync_bulk_buttons(self) -> None:
        count = len(self._selected_candidate_ids)
        state = "normal" if count else "disabled"
        self.approve_selected_button.configure(
            state=state,
            text=f"Aprobar seleccionadas ({count})" if count else "Aprobar seleccionadas",
        )
        self.delete_selected_button.configure(
            state=state,
            text=f"Eliminar seleccionadas ({count})" if count else "Eliminar seleccionadas",
        )

    def _run_bulk_action(self, action: str) -> None:
        candidate_ids = list(self._selected_candidate_ids)
        if not candidate_ids:
            return
        self._apply_bulk_progress(0, len(candidate_ids), action)
        self.approve_selected_button.configure(state="disabled")
        self.delete_selected_button.configure(state="disabled")
        threading.Thread(
            target=lambda: self._bulk_action_worker(action, candidate_ids),
            daemon=True,
        ).start()

    def _bulk_action_worker(self, action: str, candidate_ids: list[str]) -> None:
        try:
            total = len(candidate_ids)
            progress = lambda done, count: self.after(0, lambda current_done=done, current_count=count: self._apply_bulk_progress(current_done, current_count, action))
            if action == "approve":
                approve_many = getattr(self._review_service, "approve_candidates", None)
                if callable(approve_many):
                    approve_many(candidate_ids, progress_callback=progress)
                else:
                    for index, candidate_id in enumerate(candidate_ids, start=1):
                        self._review_service.approve_candidate(candidate_id)
                        progress(index, total)
            else:
                reject_many = getattr(self._review_service, "reject_candidates", None)
                if callable(reject_many):
                    reject_many(candidate_ids, delete_remote=True, progress_callback=progress)
                else:
                    for index, candidate_id in enumerate(candidate_ids, start=1):
                        self._review_service.reject_candidate(candidate_id, delete_remote=True)
                        progress(index, total)
            self.after(0, self.refresh)
        except Exception as exc:
            self.after(0, lambda error=exc: self._show_error(error))

    def _action_worker(self, action: str, candidate: PhotoCandidateRecord) -> None:
        try:
            if action == "approve":
                self._review_service.approve_candidate(candidate.id)
            else:
                self._review_service.reject_candidate(candidate.id, delete_remote=True)
            self.after(0, self.refresh)
        except Exception as exc:
            self.after(0, lambda error=exc: self._show_error(error))

    def _show_error(self, exc: Exception) -> None:
        self._is_loading = False
        self.refresh_button.configure(state="normal", text="Refrescar")
        self.status_box.configure(text="Error")
        for child in self.scroll.winfo_children():
            child.destroy()
        ctk.CTkLabel(
            self.scroll,
            text=f"No se pudo cargar la revision: {exc}",
            text_color=ERROR,
            justify="left",
            wraplength=720,
        ).grid(row=0, column=0, padx=16, pady=16, sticky="w")

    def _reset_filter_and_refresh(self) -> None:
        self._selected_candidate_ids.clear()
        self._display_limit = self.DISPLAY_BATCH_SIZE
        self.refresh()

    def _apply_bulk_progress(self, done: int, total: int, action: str) -> None:
        verb = "Aprobando" if action == "approve" else "Eliminando"
        self.bulk_progress_label.configure(text=f"{verb}: {done}/{total}")
        self.status_box.configure(text=f"{done}/{total}")
        self.bulk_progress_bar.grid(row=1, column=0, columnspan=6, pady=(10, 0), sticky="ew")
        self.bulk_progress_bar.set(0 if total <= 0 else max(0.0, min(done / total, 1.0)))

    def _show_more_candidates(self) -> None:
        if self._snapshot is None:
            return
        self._display_limit += self.DISPLAY_BATCH_SIZE
        self.status_box.configure(text=self._status_summary(self._snapshot))
        self._render_candidates(self._snapshot.candidates)

    def _update_load_more_button(self, total: int, visible: int) -> None:
        if total > visible:
            self.load_more_button.configure(text=f"Mostrar mas ({visible}/{total})")
            self.load_more_button.grid()
        else:
            self.load_more_button.grid_remove()

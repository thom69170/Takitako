"""Interface graphique Tkinter : brancher un lecteur, lire une carte
conducteur, consulter et exporter les donnees decodees.
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import export, pcsc, tacho_reader
from .models import DriverCardData


class TakitakoApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Takitako - Lecteur de carte conducteur")
        self.geometry("900x600")
        self.minsize(700, 450)

        self.card_data: DriverCardData | None = None
        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None

        self._build_widgets()
        self._refresh_readers()
        self.after(100, self._poll_queue)
        self.after(1500, self._auto_refresh_readers)

    # -- construction de l'interface -----------------------------------
    def _build_widgets(self) -> None:
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")

        ttk.Label(top, text="Lecteur :").pack(side="left")
        self.reader_var = tk.StringVar()
        self.reader_combo = ttk.Combobox(top, textvariable=self.reader_var, state="readonly", width=45)
        self.reader_combo.pack(side="left", padx=6)

        ttk.Button(top, text="Actualiser", command=self._refresh_readers).pack(side="left", padx=2)
        self.read_button = ttk.Button(top, text="Lire la carte", command=self._start_read)
        self.read_button.pack(side="left", padx=10)

        self.status_var = tk.StringVar(value="Pret.")
        ttk.Label(self, textvariable=self.status_var, padding=(8, 0)).pack(fill="x")

        self.holder_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.holder_var, padding=(8, 4), font=("", 10, "bold")).pack(fill="x")

        # Tableau des activites
        columns = ("date", "heure", "activite", "poste", "equipage", "distance")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=18)
        headers = {
            "date": "Date",
            "heure": "Heure",
            "activite": "Activite",
            "poste": "Poste",
            "equipage": "Equipage",
            "distance": "Distance jour (km)",
        }
        for col in columns:
            self.tree.heading(col, text=headers[col])
            self.tree.column(col, width=120, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=8, pady=4)

        scrollbar = ttk.Scrollbar(self.tree, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side="right", fill="y")

        # Journal
        log_frame = ttk.LabelFrame(self, text="Journal", padding=4)
        log_frame.pack(fill="x", padx=8, pady=4)
        self.log_text = tk.Text(log_frame, height=6, state="disabled", wrap="word")
        self.log_text.pack(fill="x")

        # Export
        bottom = ttk.Frame(self, padding=8)
        bottom.pack(fill="x")
        self.export_ddd_btn = ttk.Button(
            bottom, text="Exporter .ddd (brut)", command=self._export_ddd, state="disabled"
        )
        self.export_csv_btn = ttk.Button(
            bottom, text="Exporter CSV (activites)", command=self._export_csv, state="disabled"
        )
        self.export_json_btn = ttk.Button(
            bottom, text="Exporter JSON (complet)", command=self._export_json, state="disabled"
        )
        self.export_ddd_btn.pack(side="left", padx=4)
        self.export_csv_btn.pack(side="left", padx=4)
        self.export_json_btn.pack(side="left", padx=4)

    # -- lecteurs ---------------------------------------------------------
    def _refresh_readers(self) -> None:
        try:
            names = pcsc.list_reader_names()
        except Exception as exc:  # pragma: no cover - depend du pilote PC/SC installe
            names = []
            self._log(f"Impossible de lister les lecteurs : {exc}")
        self.reader_combo["values"] = names
        if names and not self.reader_var.get():
            self.reader_var.set(names[0])
        if not names:
            self.status_var.set("Aucun lecteur PC/SC detecte. Branche ton lecteur et clique sur Actualiser.")

    def _auto_refresh_readers(self) -> None:
        """Detecte automatiquement les lecteurs branches/debranches, sans
        que l'utilisateur ait besoin de cliquer sur Actualiser. Suspendu
        pendant une lecture en cours pour ne pas changer le lecteur sous
        le pied d'une operation en cours.
        """
        if not (self._worker and self._worker.is_alive()):
            try:
                names = pcsc.list_reader_names()
            except Exception:
                names = []

            current_values = list(self.reader_combo["values"])
            if names != current_values:
                self.reader_combo["values"] = names
                selected = self.reader_var.get()
                if selected not in names:
                    self.reader_var.set(names[0] if names else "")
                    if names:
                        self.status_var.set(f"Lecteur detecte : {names[0]}")
                    elif selected:
                        self.status_var.set("Lecteur debranche.")
                elif len(names) == 1 and not selected:
                    self.reader_var.set(names[0])

        self.after(1500, self._auto_refresh_readers)

    # -- lecture de la carte -----------------------------------------------
    def _start_read(self) -> None:
        reader_name = self.reader_var.get()
        if not reader_name:
            messagebox.showwarning("Takitako", "Selectionne d'abord un lecteur.")
            return
        if self._worker and self._worker.is_alive():
            return

        self.read_button.config(state="disabled")
        self._clear_results()
        self.status_var.set("Lecture en cours...")
        self._worker = threading.Thread(target=self._read_worker, args=(reader_name,), daemon=True)
        self._worker.start()

    def _read_worker(self, reader_name: str) -> None:
        def progress(message: str) -> None:
            self._queue.put(("progress", message))

        try:
            card = tacho_reader.read_driver_card(reader_name, progress=progress)
            self._queue.put(("done", card))
        except pcsc.TachoReaderError as exc:
            self._queue.put(("error", str(exc)))
        except Exception as exc:  # filet de securite pour toute erreur inattendue
            self._queue.put(("error", f"Erreur inattendue : {exc}"))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "progress":
                    self._log(payload)
                    self.status_var.set(payload)
                elif kind == "done":
                    self._on_read_done(payload)
                elif kind == "error":
                    self._on_read_error(payload)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _on_read_done(self, card: DriverCardData) -> None:
        self.card_data = card
        self.read_button.config(state="normal")

        if card.holder:
            self.holder_var.set(
                f"{card.holder.first_names} {card.holder.surname} "
                f"(carte n° {card.identification.card_number if card.identification else '?'})"
            )
        else:
            self.holder_var.set("Titulaire non identifie (voir journal)")

        for day in card.daily_activities:
            if not day.changes:
                self.tree.insert(
                    "", "end",
                    values=(day.date.isoformat(), "", "", "", "", day.distance_km),
                )
                continue
            for change in day.changes:
                self.tree.insert(
                    "", "end",
                    values=(
                        day.date.isoformat(),
                        change.time_str,
                        change.activity,
                        "2nd conducteur" if change.slot_co_driver else "conducteur",
                        "oui" if change.crew else "non",
                        day.distance_km,
                    ),
                )

        for err in card.read_errors:
            self._log(f"[attention] {err}")

        n_days = len(card.daily_activities)
        self.status_var.set(f"Lecture terminee : {n_days} jour(s) d'activite decode(s).")

        has_data = bool(card.raw_files)
        state = "normal" if has_data else "disabled"
        self.export_ddd_btn.config(state=state)
        self.export_csv_btn.config(state="normal" if card.daily_activities else "disabled")
        self.export_json_btn.config(state=state)

    def _on_read_error(self, message: str) -> None:
        self.read_button.config(state="normal")
        self.status_var.set("Echec de la lecture.")
        self._log(f"[erreur] {message}")
        messagebox.showerror("Takitako", message)

    def _clear_results(self) -> None:
        self.card_data = None
        self.holder_var.set("")
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")
        self.export_ddd_btn.config(state="disabled")
        self.export_csv_btn.config(state="disabled")
        self.export_json_btn.config(state="disabled")

    def _log(self, message: str) -> None:
        self.log_text.config(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    # -- export -------------------------------------------------------------
    def _export_ddd(self) -> None:
        self._export(export.write_raw_dump, [("Fichier tachygraphe brut", "*.ddd")], ".ddd")

    def _export_csv(self) -> None:
        self._export(export.write_activity_csv, [("CSV", "*.csv")], ".csv")

    def _export_json(self) -> None:
        self._export(export.write_json, [("JSON", "*.json")], ".json")

    def _export(self, writer, filetypes, default_ext) -> None:
        if not self.card_data:
            return
        path = filedialog.asksaveasfilename(defaultextension=default_ext, filetypes=filetypes)
        if not path:
            return
        try:
            writer(self.card_data, path)
            self._log(f"Exporte : {path}")
        except Exception as exc:
            messagebox.showerror("Takitako", f"Echec de l'export : {exc}")


def main() -> None:
    app = TakitakoApp()
    app.mainloop()

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

        # Tableau des activites, regroupe par jour (un noeud repliable par
        # journee avec un resume, les changements d'activite en dessous).
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=8, pady=4)

        columns = ("heure", "activite", "poste", "equipage")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="tree headings", height=18)
        self.tree.heading("#0", text="Journee")
        self.tree.column("#0", width=420, anchor="w")
        headers = {
            "heure": "Heure",
            "activite": "Activite",
            "poste": "Poste",
            "equipage": "Equipage",
        }
        for col in columns:
            self.tree.heading(col, text=headers[col])
            self.tree.column(col, width=120, anchor="center")

        # Couleurs par type d'activite, pour reperer visuellement la journee
        # d'un coup d'oeil (meme repliee : le resume reprend ces couleurs).
        self.tree.tag_configure("jour", font=("", 9, "bold"), background="#e8e8e8")
        self.tree.tag_configure("CONDUITE", foreground="#8a1f1f")
        self.tree.tag_configure("TRAVAIL", foreground="#8a5a1f")
        self.tree.tag_configure("DISPONIBILITE", foreground="#1f5a8a")
        self.tree.tag_configure("REPOS", foreground="#1f7a3d")

        vscroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=vscroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vscroll.pack(side="right", fill="y")

        controls = ttk.Frame(self, padding=(8, 0))
        controls.pack(fill="x")
        ttk.Button(controls, text="Tout deplier", command=lambda: self._set_all_open(True)).pack(side="left", padx=2)
        ttk.Button(controls, text="Tout replier", command=lambda: self._set_all_open(False)).pack(side="left", padx=2)

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
            totals = self._activity_totals_minutes(day.changes)
            summary = " · ".join(
                f"{label} {m // 60}h{m % 60:02d}" for label, m in totals.items() if m
            )
            label = f"{day.date.isoformat()}  ({day.distance_km} km)"
            if summary:
                label += f"  —  {summary}"
            day_id = self.tree.insert("", "end", text=label, values=("", "", "", ""), tags=("jour",), open=False)

            for change in day.changes:
                self.tree.insert(
                    day_id, "end",
                    text="",
                    values=(
                        change.time_str,
                        change.activity,
                        "2nd conducteur" if change.slot_co_driver else "conducteur",
                        "oui" if change.crew else "non",
                    ),
                    tags=(change.activity,),
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

    @staticmethod
    def _activity_totals_minutes(changes) -> dict[str, int]:
        """Duree cumulee (minutes) par activite au sein d'une journee, en
        mesurant l'ecart entre chaque changement et le suivant (le dernier
        va jusqu'a minuit). Purement indicatif : reste correct uniquement
        si les horodatages de la journee sont tous coherents (voir
        limitations connues du decodeur d'activite dans le README).
        """
        totals = {"CONDUITE": 0, "TRAVAIL": 0, "DISPONIBILITE": 0, "REPOS": 0}
        for i, change in enumerate(changes):
            end = changes[i + 1].time_minutes if i + 1 < len(changes) else 24 * 60
            duration = max(end - change.time_minutes, 0)
            totals[change.activity] = totals.get(change.activity, 0) + duration
        return totals

    def _set_all_open(self, open_: bool) -> None:
        for item in self.tree.get_children(""):
            self.tree.item(item, open=open_)

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

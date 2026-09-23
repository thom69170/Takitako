"""Interface graphique Tkinter : brancher un lecteur, lire une carte
conducteur, consulter et exporter les donnees decodees.
"""
from __future__ import annotations

import datetime as dt
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import compliance, export, local_view, pcsc, tacho_reader
from .local_view import ActivitySegment
from .models import DriverCardData

ACTIVITY_COLORS = {
    "CONDUITE": "#f39c12",
    "TRAVAIL": "#27ae60",
    "DISPONIBILITE": "#8e44ad",
    "REPOS": "#dce6f0",
}
ACTIVITY_TEXT_COLORS = {
    "CONDUITE": "#3a2a00",
    "TRAVAIL": "#ffffff",
    "DISPONIBILITE": "#ffffff",
    "REPOS": "#7a8ca0",
}

# Libelle affiche dans la legende : la disponibilite est une categorie
# reglementaire distincte du repos (elle ne compte pas comme temps de repos
# journalier/hebdomadaire), une confusion frequente vu de l'exterieur.
ACTIVITY_LEGEND_LABELS = {
    "CONDUITE": "Conduite",
    "TRAVAIL": "Travail",
    "DISPONIBILITE": "Disponibilite (≠ repos reglementaire)",
    "REPOS": "Repos",
}

SEVERITY_COLORS = {"infraction": "#c0392b", "info": "#7f8c8d"}

NIGHT_START = dt.time(22, 0)
NIGHT_END = dt.time(6, 0)

PERIOD_PRESETS = ["Tout", "Aujourd'hui", "7 derniers jours", "30 derniers jours", "Ce mois-ci", "Mois dernier"]


class TakitakoApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Takitako - Lecteur de carte conducteur")
        self.geometry("1100x760")
        self.minsize(820, 540)

        self.card_data: DriverCardData | None = None
        self.segments: list[ActivitySegment] = []
        self.by_local_day: dict[dt.date, list[ActivitySegment]] = {}
        self.infractions: list[compliance.Infraction] = []

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

        # Barre d'export et journal : ancres en bas de la fenetre (side="bottom"),
        # donc toujours visibles quelle que soit la taille de la fenetre.
        bottom = ttk.Frame(self, padding=8)
        bottom.pack(side="bottom", fill="x")
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

        log_frame = ttk.LabelFrame(self, text="Journal", padding=4)
        log_frame.pack(side="bottom", fill="x", padx=8, pady=4)
        self.log_text = tk.Text(log_frame, height=6, state="disabled", wrap="word")
        self.log_text.pack(fill="x")

        notebook = ttk.Notebook(self)
        notebook.pack(side="top", fill="both", expand=True, padx=8, pady=4)

        table_tab = ttk.Frame(notebook)
        timeline_tab = ttk.Frame(notebook)
        dashboard_tab = ttk.Frame(notebook)
        infractions_tab = ttk.Frame(notebook)
        notebook.add(dashboard_tab, text="Tableau de bord")
        notebook.add(timeline_tab, text="Carte chrono")
        notebook.add(table_tab, text="Tableau")
        notebook.add(infractions_tab, text="Infractions")

        notebook.bind("<<NotebookTabChanged>>", lambda e: self._redraw_timeline() if self.card_data else None)

        self._build_table_tab(table_tab)
        self._build_timeline_tab(timeline_tab)
        self._build_dashboard_tab(dashboard_tab)
        self._build_infractions_tab(infractions_tab)

    # -- onglet Tableau : activites regroupees par jour --------------------
    def _build_table_tab(self, table_tab: ttk.Frame) -> None:
        tree_frame = ttk.Frame(table_tab)
        tree_frame.pack(fill="both", expand=True)

        controls = ttk.Frame(table_tab, padding=(0, 4))
        controls.pack(fill="x", side="bottom")
        ttk.Button(controls, text="Tout deplier", command=lambda: self._set_all_open(True)).pack(side="left", padx=2)
        ttk.Button(controls, text="Tout replier", command=lambda: self._set_all_open(False)).pack(side="left", padx=2)

        columns = ("heure", "activite", "poste", "equipage")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="tree headings", height=18)
        self.tree.heading("#0", text="Journee")
        self.tree.column("#0", width=420, anchor="w")
        headers = {"heure": "Heure (locale)", "activite": "Activite", "poste": "Poste", "equipage": "Equipage"}
        for col in columns:
            self.tree.heading(col, text=headers[col])
            self.tree.column(col, width=120, anchor="center")

        self.tree.tag_configure("jour", font=("", 9, "bold"), background="#e8e8e8")
        self.tree.tag_configure("CONDUITE", foreground="#8a5a00")
        self.tree.tag_configure("TRAVAIL", foreground="#0d3d20")
        self.tree.tag_configure("DISPONIBILITE", foreground="#4a1f6e")
        self.tree.tag_configure("REPOS", foreground="#7a8ca0")

        vscroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=vscroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vscroll.pack(side="right", fill="y")

    # -- onglet Carte chrono : frise pleine largeur par jour, style tableau
    # de bord tachygraphe (blocs colores, axe horaire, semaines alternees).
    def _build_timeline_tab(self, timeline_tab: ttk.Frame) -> None:
        timeline_container = ttk.Frame(timeline_tab)
        timeline_container.pack(fill="both", expand=True)

        legend = ttk.Frame(timeline_tab, padding=(0, 4))
        legend.pack(fill="x", side="bottom")
        for label in ("CONDUITE", "TRAVAIL", "DISPONIBILITE", "REPOS"):
            swatch = tk.Canvas(legend, width=14, height=14, highlightthickness=0)
            swatch.create_rectangle(0, 0, 14, 14, fill=ACTIVITY_COLORS[label], outline="#999999")
            swatch.pack(side="left", padx=(8, 2))
            ttk.Label(legend, text=ACTIVITY_LEGEND_LABELS[label]).pack(side="left")
        ttk.Label(legend, text="   |   Trait rouge = infraction detectee", foreground="#c0392b").pack(side="left")

        self.timeline_canvas = tk.Canvas(timeline_container, background="white", highlightthickness=0)
        timeline_vscroll = ttk.Scrollbar(
            timeline_container, orient="vertical", command=self.timeline_canvas.yview
        )
        self.timeline_canvas.configure(yscrollcommand=timeline_vscroll.set)
        self.timeline_canvas.pack(side="left", fill="both", expand=True)
        timeline_vscroll.pack(side="right", fill="y")
        self.timeline_canvas.bind(
            "<Configure>", lambda event: self._redraw_timeline() if self.card_data else None
        )

    # -- onglet Tableau de bord : KPI sur une periode choisie ---------------
    def _build_dashboard_tab(self, dashboard_tab: ttk.Frame) -> None:
        period_bar = ttk.Frame(dashboard_tab, padding=8)
        period_bar.pack(fill="x")
        ttk.Label(period_bar, text="Periode :").pack(side="left")
        self.period_var = tk.StringVar(value=PERIOD_PRESETS[0])
        period_combo = ttk.Combobox(
            period_bar, textvariable=self.period_var, values=PERIOD_PRESETS, state="readonly", width=20
        )
        period_combo.pack(side="left", padx=6)
        period_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_dashboard())

        stats = ttk.Frame(dashboard_tab, padding=8)
        stats.pack(fill="x")

        self.service_var = tk.StringVar(value="--")
        service_card = ttk.LabelFrame(stats, text="TEMPS DE SERVICE (conduite + travail + disponibilite)")
        service_card.pack(side="left", fill="both", expand=True, padx=(0, 6))
        ttk.Label(service_card, textvariable=self.service_var, font=("", 22, "bold")).pack(padx=12, pady=8)

        self.infractions_var = tk.StringVar(value="--")
        infr_card = ttk.LabelFrame(stats, text="INFRACTIONS SUR LA PERIODE")
        infr_card.pack(side="left", fill="both", expand=True, padx=(6, 0))
        self.infractions_label = ttk.Label(infr_card, textvariable=self.infractions_var, font=("", 22, "bold"))
        self.infractions_label.pack(padx=12, pady=8)

        bars_frame = ttk.Frame(dashboard_tab, padding=8)
        bars_frame.pack(fill="x")
        self.kpi_vars: dict[str, tk.StringVar] = {}
        for activity in ("CONDUITE", "TRAVAIL", "DISPONIBILITE", "REPOS"):
            row = ttk.Frame(bars_frame, padding=(0, 3))
            row.pack(fill="x")
            swatch = tk.Canvas(row, width=16, height=16, highlightthickness=0)
            swatch.create_rectangle(0, 0, 16, 16, fill=ACTIVITY_COLORS[activity], outline="#999999")
            swatch.pack(side="left", padx=(0, 6))
            ttk.Label(row, text=ACTIVITY_LEGEND_LABELS[activity], width=32, anchor="w").pack(side="left")
            var = tk.StringVar(value="--")
            self.kpi_vars[activity] = var
            ttk.Label(row, textvariable=var, font=("", 11, "bold")).pack(side="left")

        ttk.Label(
            dashboard_tab,
            text=(
                "\"Temps de service\" = somme conduite + travail + disponibilite (definition simplifiee, "
                "pas le calcul officiel d'amplitude). \"Heures de nuit\" = chevauchement avec la plage "
                f"{NIGHT_START.strftime('%Hh%M')}-{NIGHT_END.strftime('%Hh%M')} (convention, pas une regle unique)."
            ),
            wraplength=700, foreground="#666666", padding=8, justify="left",
        ).pack(fill="x")

    # -- onglet Infractions : table detaillee -------------------------------
    def _build_infractions_tab(self, infractions_tab: ttk.Frame) -> None:
        ttk.Label(
            infractions_tab,
            text=(
                "Detection partielle (conduite continue 4h30/45min, conduite journaliere 9h/10h, "
                "repos journalier 9h/11h). Ne remplace pas un controle reglementaire homologue - "
                "voir le README pour la liste des regles non verifiees."
            ),
            wraplength=900, foreground="#666666", padding=8, justify="left",
        ).pack(fill="x")

        columns = ("date", "debut", "fin", "type", "severite", "message")
        self.infractions_tree = ttk.Treeview(infractions_tab, columns=columns, show="headings", height=18)
        headers = {
            "date": "Date", "debut": "Debut", "fin": "Fin", "type": "Regle",
            "severite": "Gravite", "message": "Detail",
        }
        widths = {"date": 90, "debut": 60, "fin": 60, "type": 140, "severite": 80, "message": 480}
        for col in columns:
            self.infractions_tree.heading(col, text=headers[col])
            self.infractions_tree.column(col, width=widths[col], anchor="w")
        self.infractions_tree.tag_configure("infraction", foreground=SEVERITY_COLORS["infraction"])
        self.infractions_tree.tag_configure("info", foreground=SEVERITY_COLORS["info"])

        vscroll = ttk.Scrollbar(infractions_tab, orient="vertical", command=self.infractions_tree.yview)
        self.infractions_tree.configure(yscroll=vscroll.set)
        self.infractions_tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=4)
        vscroll.pack(side="right", fill="y", pady=4)

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
                        change.local_time_str(day.date),
                        change.activity,
                        "2nd conducteur" if change.slot_co_driver else "conducteur",
                        "oui" if change.crew else "non",
                    ),
                    tags=(change.activity,),
                )

        for err in card.read_errors:
            self._log(f"[attention] {err}")

        # Vue en heure locale (segments continus) partagee par la
        # chronologie, le tableau de bord et la detection d'infractions.
        self.segments = compliance.prepare(local_view.build_segments(card.daily_activities))
        self.by_local_day = local_view.group_by_local_day(self.segments)
        self.infractions = compliance.check_all(self.segments) if self.segments else []
        self._populate_infractions_tree()

        n_days = len(card.daily_activities)
        n_hard = sum(1 for i in self.infractions if i.severity == "infraction")
        self.status_var.set(
            f"Lecture terminee : {n_days} jour(s) d'activite decode(s), {n_hard} infraction(s) detectee(s)."
        )

        has_data = bool(card.raw_files)
        state = "normal" if has_data else "disabled"
        self.export_ddd_btn.config(state=state)
        self.export_csv_btn.config(state="normal" if card.daily_activities else "disabled")
        self.export_json_btn.config(state=state)

        self._redraw_timeline()
        self._refresh_dashboard()

    # -- Carte chrono ---------------------------------------------------------
    def _redraw_timeline(self) -> None:
        canvas = self.timeline_canvas
        canvas.delete("all")
        if not self.by_local_day:
            return

        width = canvas.winfo_width()
        if width < 50:
            return

        days = sorted(self.by_local_day.keys())
        full_days = _fill_day_gaps(days)

        label_width, margin = 150, 10
        timeline_x0 = label_width
        timeline_width = max(width - label_width - margin, 100)
        row_height, header_height = 34, 26
        total_height = header_height + len(full_days) * row_height

        for h in range(0, 25, 2):
            x = timeline_x0 + timeline_width * h / 24
            canvas.create_line(x, header_height, x, total_height, fill="#eeeeee")
            canvas.create_text(x, header_height - 11, text=f"{h % 24:02d}:00", font=("", 7), fill="#666666")

        y = header_height
        for day in full_days:
            week = day.isocalendar()[1]
            row_bg = "#eaf3fc" if week % 2 == 0 else "#ffffff"
            canvas.create_rectangle(0, y, width, y + row_height, fill=row_bg, outline="")
            canvas.create_text(
                8, y + row_height / 2, text=local_view.format_fr_date(day), anchor="w", font=("", 8)
            )

            for seg in self.by_local_day.get(day, []):
                start_m = seg.start.hour * 60 + seg.start.minute
                end_minutes = start_m + (seg.end - seg.start).total_seconds() / 60
                end_minutes = min(end_minutes, 24 * 60)
                x1 = timeline_x0 + timeline_width * start_m / 1440
                x2 = timeline_x0 + timeline_width * end_minutes / 1440
                if x2 <= x1:
                    continue
                color = ACTIVITY_COLORS.get(seg.activity, "#999999")
                outline = "#c0392b" if seg.is_suspect else ""
                canvas.create_rectangle(x1, y + 2, x2, y + row_height - 2, fill=color, outline=outline, width=2)
                seg_width = x2 - x1
                if seg_width >= 46:
                    text = ACTIVITY_LEGEND_LABELS[seg.activity].split(" ")[0]
                elif seg_width >= 16:
                    text = ACTIVITY_LEGEND_LABELS[seg.activity][0] + "."
                else:
                    text = None
                if text:
                    canvas.create_text(
                        (x1 + x2) / 2, y + row_height / 2, text=text, font=("", 8),
                        fill=ACTIVITY_TEXT_COLORS.get(seg.activity, "#000000"),
                    )

            y += row_height

        # Marqueurs d'infraction : trait rouge vertical a l'heure de debut.
        for inf in self.infractions:
            if inf.severity != "infraction":
                continue
            day = inf.start.date()
            if day not in full_days:
                continue
            row_index = full_days.index(day)
            row_y = header_height + row_index * row_height
            minutes = inf.start.hour * 60 + inf.start.minute
            x = timeline_x0 + timeline_width * minutes / 1440
            canvas.create_line(x, row_y, x, row_y + row_height, fill="#c0392b", width=2)

        canvas.configure(scrollregion=(0, 0, width, y + 10))

    # -- Tableau de bord ---------------------------------------------------
    def _period_range(self) -> tuple[dt.date, dt.date] | None:
        """Retourne (debut, fin inclus) selon le preset choisi, ou None
        pour 'Tout'."""
        if not self.by_local_day:
            return None
        preset = self.period_var.get()
        all_days = sorted(self.by_local_day.keys())
        today = dt.datetime.now().date()
        if preset == "Aujourd'hui":
            return today, today
        if preset == "7 derniers jours":
            return today - dt.timedelta(days=6), today
        if preset == "30 derniers jours":
            return today - dt.timedelta(days=29), today
        if preset == "Ce mois-ci":
            return today.replace(day=1), today
        if preset == "Mois dernier":
            first_this_month = today.replace(day=1)
            last_month_end = first_this_month - dt.timedelta(days=1)
            return last_month_end.replace(day=1), last_month_end
        return all_days[0], all_days[-1]

    def _refresh_dashboard(self) -> None:
        if not self.by_local_day:
            return
        period = self._period_range()
        if period is None:
            return
        start, end = period

        totals = {"CONDUITE": dt.timedelta(), "TRAVAIL": dt.timedelta(), "DISPONIBILITE": dt.timedelta(), "REPOS": dt.timedelta()}
        night = dt.timedelta()
        for day, segs in self.by_local_day.items():
            if not (start <= day <= end):
                continue
            for seg in segs:
                if seg.is_suspect:
                    continue
                duration = seg.end - seg.start
                if seg.activity in totals:
                    totals[seg.activity] += duration
                night += _night_overlap(seg)

        for activity, var in self.kpi_vars.items():
            var.set(_fmt_hm(totals[activity]))

        service = totals["CONDUITE"] + totals["TRAVAIL"] + totals["DISPONIBILITE"]
        self.service_var.set(f"{_fmt_hm(service)}  (dont {_fmt_hm(night)} de nuit)")

        n_infractions = sum(
            1 for i in self.infractions if i.severity == "infraction" and start <= i.start.date() <= end
        )
        self.infractions_var.set(str(n_infractions))
        self.infractions_label.configure(foreground="#c0392b" if n_infractions else "#27ae60")

    def _populate_infractions_tree(self) -> None:
        for item in self.infractions_tree.get_children():
            self.infractions_tree.delete(item)
        for inf in self.infractions:
            self.infractions_tree.insert(
                "", "end",
                values=(
                    inf.start.strftime("%d/%m/%Y"),
                    inf.start.strftime("%H:%M"),
                    inf.end.strftime("%H:%M"),
                    inf.rule,
                    "Infraction" if inf.severity == "infraction" else "Info",
                    inf.message,
                ),
                tags=(inf.severity,),
            )

    @staticmethod
    def _activity_totals_minutes(changes) -> dict[str, int]:
        """Duree cumulee (minutes) par activite au sein d'une journee, en
        mesurant l'ecart entre chaque changement et le suivant (le dernier
        va jusqu'a minuit). Purement indicatif.
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
        self.segments = []
        self.by_local_day = {}
        self.infractions = []
        self.holder_var.set("")
        for item in self.tree.get_children():
            self.tree.delete(item)
        for item in self.infractions_tree.get_children():
            self.infractions_tree.delete(item)
        self.timeline_canvas.delete("all")
        self.service_var.set("--")
        self.infractions_var.set("--")
        for var in self.kpi_vars.values():
            var.set("--")
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


def _fill_day_gaps(days: list[dt.date]) -> list[dt.date]:
    """Complete les jours manquants entre le premier et le dernier jour
    connu, pour afficher une frise continue (jours sans donnees = ligne
    vide) plutot que de sauter directement au jour suivant utilise."""
    if not days:
        return []
    full = []
    cursor = days[0]
    while cursor <= days[-1]:
        full.append(cursor)
        cursor += dt.timedelta(days=1)
    return full


def _night_overlap(seg: ActivitySegment) -> dt.timedelta:
    """Chevauchement d'un segment avec la plage de nuit (22h-6h), toutes
    nuits traversees confondues."""
    total = dt.timedelta()
    cursor = seg.start
    while cursor < seg.end:
        day = cursor.date()
        night_start_today = dt.datetime.combine(day, NIGHT_START, tzinfo=seg.start.tzinfo)
        night_end_tomorrow = dt.datetime.combine(day, NIGHT_END, tzinfo=seg.start.tzinfo) + dt.timedelta(days=1)
        overlap_start = max(seg.start, night_start_today)
        overlap_end = min(seg.end, night_end_tomorrow)
        if overlap_end > overlap_start:
            total += overlap_end - overlap_start
        cursor = dt.datetime.combine(day, dt.time.min, tzinfo=seg.start.tzinfo) + dt.timedelta(days=1)
    return total


def _fmt_hm(td: dt.timedelta) -> str:
    total_minutes = int(td.total_seconds() // 60)
    sign = "-" if total_minutes < 0 else ""
    total_minutes = abs(total_minutes)
    return f"{sign}{total_minutes // 60}h{total_minutes % 60:02d}"


def main() -> None:
    app = TakitakoApp()
    app.mainloop()

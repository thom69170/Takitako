import datetime as dt

from takitako import compliance
from takitako.local_view import ActivitySegment

TZ = dt.timezone(dt.timedelta(hours=1))


def seg(day: dt.date, h1: int, m1: int, h2: int, m2: int, activity: str, next_day: bool = False) -> ActivitySegment:
    start = dt.datetime(day.year, day.month, day.day, h1, m1, tzinfo=TZ)
    end_day = day + dt.timedelta(days=1) if next_day else day
    end = dt.datetime(end_day.year, end_day.month, end_day.day, h2, m2, tzinfo=TZ)
    return ActivitySegment(start, end, activity, crew=False, slot_co_driver=False)


def test_continuous_driving_under_limit_no_infraction():
    day = dt.date(2026, 1, 5)
    segments = [
        seg(day, 6, 0, 10, 0, "CONDUITE"),  # 4h, sous la limite
        seg(day, 10, 0, 10, 45, "DISPONIBILITE"),  # pause 45 min
        seg(day, 10, 45, 12, 0, "CONDUITE"),
    ]
    prepared = compliance.prepare(segments)
    infractions = [i for i in compliance.check_all(prepared) if i.rule == "conduite_continue"]
    assert infractions == []


def test_continuous_driving_over_limit_flagged():
    day = dt.date(2026, 1, 5)
    segments = [
        seg(day, 6, 0, 11, 0, "CONDUITE"),  # 5h sans pause -> depasse 4h30
    ]
    prepared = compliance.prepare(segments)
    infractions = [i for i in compliance.check_all(prepared) if i.rule == "conduite_continue"]
    assert len(infractions) == 1
    assert infractions[0].severity == "infraction"


def test_short_break_does_not_reset_continuous_driving():
    day = dt.date(2026, 1, 5)
    segments = [
        seg(day, 6, 0, 10, 0, "CONDUITE"),  # 4h
        seg(day, 10, 0, 10, 10, "DISPONIBILITE"),  # seulement 10 min : ne compte pas
        seg(day, 10, 10, 11, 0, "CONDUITE"),  # +50 min -> total conduite 4h50 sans vraie pause
    ]
    prepared = compliance.prepare(segments)
    infractions = [i for i in compliance.check_all(prepared) if i.rule == "conduite_continue"]
    assert len(infractions) == 1


def test_daily_driving_absolute_limit():
    day = dt.date(2026, 1, 5)
    # blocs de conduite separes par des pauses valides, total 11h > 10h dans la journee
    segments = []
    t = 0
    for _ in range(6):
        segments.append(seg(day, t // 60, t % 60, (t + 110) // 60, (t + 110) % 60, "CONDUITE"))
        t += 110
        segments.append(seg(day, t // 60, t % 60, (t + 45) // 60, (t + 45) % 60, "DISPONIBILITE"))
        t += 45
    prepared = compliance.prepare(segments)
    infractions = [i for i in compliance.check_all(prepared) if i.rule == "conduite_journaliere"]
    assert len(infractions) == 1
    assert infractions[0].severity == "infraction"


def test_daily_rest_too_short_flagged_as_infraction():
    day = dt.date(2026, 1, 5)
    # repos de 5h chevauchant la nuit (23h -> 4h)
    segments = [seg(day, 23, 0, 4, 0, "REPOS", next_day=True)]
    prepared = compliance.prepare(segments)
    infractions = [i for i in compliance.check_all(prepared) if i.rule == "repos_journalier"]
    assert len(infractions) == 1
    assert infractions[0].severity == "infraction"


def test_daily_rest_reduced_is_info_not_infraction():
    day = dt.date(2026, 1, 5)
    # repos de 10h chevauchant la nuit : reduit mais autorise
    segments = [seg(day, 20, 0, 6, 0, "REPOS", next_day=True)]
    prepared = compliance.prepare(segments)
    infractions = [i for i in compliance.check_all(prepared) if i.rule == "repos_journalier"]
    assert len(infractions) == 1
    assert infractions[0].severity == "info"


def test_daily_rest_normal_not_flagged():
    day = dt.date(2026, 1, 5)
    segments = [seg(day, 20, 0, 8, 0, "REPOS", next_day=True)]  # 12h
    prepared = compliance.prepare(segments)
    infractions = [i for i in compliance.check_all(prepared) if i.rule == "repos_journalier"]
    assert infractions == []


def test_midday_break_not_confused_with_daily_rest():
    """Une longue pause en pleine journee (hors plage nocturne) ne doit
    pas etre prise pour une tentative de repos journalier insuffisant."""
    day = dt.date(2026, 1, 5)
    segments = [seg(day, 12, 0, 16, 0, "REPOS")]  # 4h, mais en plein apres-midi
    prepared = compliance.prepare(segments)
    infractions = [i for i in compliance.check_all(prepared) if i.rule == "repos_journalier"]
    assert infractions == []


def test_long_unbroken_driving_marked_suspect_not_infraction():
    """Un segment de conduite de plusieurs heures sans le moindre
    changement est une donnee suspecte (trou probable), pas comptabilise
    comme de la conduite continue ni comme conduite journaliere."""
    day = dt.date(2026, 1, 5)
    segments = [seg(day, 0, 0, 12, 0, "CONDUITE")]  # 12h d'affilee, aucun changement
    prepared = compliance.prepare(segments)
    assert prepared[0].is_suspect is True

    infractions = compliance.check_all(prepared)
    rules = {i.rule for i in infractions}
    assert "conduite_continue" not in rules
    assert "conduite_journaliere" not in rules
    assert "donnee_suspecte" in rules


def test_adjacent_same_activity_segments_merge_before_suspect_check():
    """Deux segments adjacents de meme activite, individuellement courts,
    qui forment ensemble un bloc implausiblement long doivent etre
    fusionnes puis marques suspects (et pas evalues independamment)."""
    day = dt.date(2026, 1, 5)
    segments = [
        seg(day, 0, 0, 13, 0, "TRAVAIL"),
        seg(day, 13, 0, 12, 0, "TRAVAIL", next_day=True),  # total 25h
    ]
    prepared = compliance.prepare(segments)
    assert len(prepared) == 1
    assert prepared[0].is_suspect is True


def test_normal_activity_not_marked_suspect():
    day = dt.date(2026, 1, 5)
    segments = [seg(day, 8, 0, 12, 0, "TRAVAIL")]
    prepared = compliance.prepare(segments)
    assert prepared[0].is_suspect is False

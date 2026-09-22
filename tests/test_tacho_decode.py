import datetime as dt

import pytest

from takitako import tacho_decode
from takitako.tacho_decode import DecodeError


def bcd_byte(value: int) -> int:
    tens, units = divmod(value, 10)
    return (tens << 4) | units


def test_decode_bcd_datef_valid():
    # 2024-09-15
    raw = bytes([bcd_byte(20), bcd_byte(24), bcd_byte(9), bcd_byte(15)])
    assert tacho_decode.decode_bcd_datef(raw) == dt.date(2024, 9, 15)


def test_decode_bcd_datef_empty_is_none():
    assert tacho_decode.decode_bcd_datef(bytes(4)) is None


def test_decode_bcd_datef_too_short_raises():
    with pytest.raises(DecodeError):
        tacho_decode.decode_bcd_datef(bytes(2))


def test_decode_time_real_epoch_zero_is_none():
    assert tacho_decode.decode_time_real(bytes(4)) is None


def test_decode_time_real_known_timestamp():
    # 2024-01-01T00:00:00Z == 1704067200
    raw = (1704067200).to_bytes(4, "big")
    result = tacho_decode.decode_time_real(raw)
    assert result == dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)


@pytest.mark.parametrize(
    "slot,crew,activity_code,minutes,expected_label",
    [
        (0, 0, 0b00, 0, "REPOS"),
        (0, 0, 0b01, 90, "DISPONIBILITE"),
        (1, 1, 0b10, 480, "TRAVAIL"),
        (0, 0, 0b11, 1439, "CONDUITE"),
    ],
)
def test_decode_activity_change_info(slot, crew, activity_code, minutes, expected_label):
    raw = (slot << 15) | (crew << 14) | (activity_code << 12) | minutes
    got_slot, got_crew, got_activity, got_minutes = tacho_decode.decode_activity_change_info(raw)
    assert got_slot == bool(slot)
    assert got_crew == bool(crew)
    assert got_activity == expected_label
    assert got_minutes == minutes


def test_activity_entry_time_str():
    from takitako.models import ActivityEntry

    entry = ActivityEntry(slot_co_driver=False, crew=False, activity="CONDUITE", time_minutes=125)
    assert entry.time_str == "02:05"


def _build_daily_record(date: dt.date, distance_km: int, changes_raw: list[int]) -> bytes:
    changes_bytes = b"".join(v.to_bytes(2, "big") for v in changes_raw)
    record_length = 12 + len(changes_bytes)
    midnight = dt.datetime(date.year, date.month, date.day, tzinfo=dt.timezone.utc)
    date_bytes = int(midnight.timestamp()).to_bytes(4, "big")
    header = (
        (0).to_bytes(2, "big")  # previous record length (non utilise par le decodeur)
        + record_length.to_bytes(2, "big")
        + date_bytes
        + (1).to_bytes(2, "big")  # presence counter
        + distance_km.to_bytes(2, "big")
    )
    return header + changes_bytes


def test_decode_driver_activity_data_linear_scan():
    day1_changes = [(0b00 << 12) | 0, (0b11 << 12) | 480, (0b00 << 12) | 1000]
    day2_changes = [(0b11 << 12) | 360]

    day1 = _build_daily_record(dt.date(2024, 3, 1), 250, day1_changes)
    day2 = _build_daily_record(dt.date(2024, 3, 2), 180, day2_changes)

    buffer = bytes(4) + day1 + day2  # 4 octets de pointeurs (ignores par le scan lineaire)

    records = tacho_decode.decode_driver_activity_data(buffer)

    assert len(records) == 2
    assert records[0].date == dt.date(2024, 3, 1)
    assert records[0].distance_km == 250
    assert len(records[0].changes) == 3
    assert records[0].changes[1].activity == "CONDUITE"
    assert records[0].changes[1].time_minutes == 480

    assert records[1].date == dt.date(2024, 3, 2)
    assert records[1].distance_km == 180


def test_decode_driver_activity_data_too_short_raises():
    with pytest.raises(DecodeError):
        tacho_decode.decode_driver_activity_data(bytes(2))


def _build_card_identification(card_number: str, issue: dt.datetime) -> bytes:
    data = bytearray(65)
    data[0] = 33  # France (code numerique fictif pour le test)
    data[1:17] = card_number.encode("ascii").ljust(16, b" ")
    data[17] = 0  # code page
    data[18:53] = b"AUTORITE TEST".ljust(35, b" ")
    ts = int(issue.timestamp()).to_bytes(4, "big")
    data[53:57] = ts
    data[57:61] = ts
    data[61:65] = ts
    return bytes(data)


def test_decode_card_identification():
    issue = dt.datetime(2022, 5, 1, tzinfo=dt.timezone.utc)
    raw = _build_card_identification("1234567890123456", issue)
    result = tacho_decode.decode_card_identification(raw)
    assert result.card_number == "1234567890123456"
    assert result.issuing_authority_name == "AUTORITE TEST"
    assert result.issue_date == issue

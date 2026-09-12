#!/usr/bin/env python3

import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests


FLEET_DIR = os.getenv("IZI_BOX_FLEET_DIR", "/root/fleet")
DB_PATH = os.getenv("IZI_BOX_DB_PATH", "/root/fleet/izi_box.db")
MOSCOW = ZoneInfo("Europe/Moscow")

RULE_15 = "0d4e04da8f234d70ba9d614ad0da68a5"
RULE_7 = "77f3edd9cbce49dc9ef413b026b4453b"
RULE_4 = "84862601590a4271b93bd25cf74bbc04"
RULE_ZERO = "ba272ae44a2c4f589465a497f108f5bc"
SAFE_BASE_RULES = {RULE_15, RULE_7, RULE_4}

PROFILE_URL = "https://fleet-api.taxi.yandex.net/v2/parks/contractors/driver-profile"
PROFILES_URL = "https://fleet-api.taxi.yandex.net/v1/parks/driver-profiles/list"
ORDERS_URL = "https://fleet-api.taxi.yandex.net/v1/parks/orders/list"

PROFILE_SYNC_MINUTES = 60
ORDER_SYNC_MINUTES = 15
APPLY_CHANGES = os.getenv("IZI_BOX_APPLY", "0").strip() == "1"


def now():
    return datetime.now(MOSCOW)


def parse_dt(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    sys.path.insert(0, os.path.dirname(__file__))
    import izi_box

    izi_box.init_db()


def get_meta(key):
    with connect() as conn:
        row = conn.execute(
            "SELECT value FROM izi_box_meta WHERE key = ?",
            (key,),
        ).fetchone()
    return row["value"] if row else None


def set_meta(key, value):
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO izi_box_meta(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def due(key, minutes):
    last = parse_dt(get_meta(key))
    if not last:
        return True
    return now() - last.astimezone(MOSCOW) >= timedelta(minutes=minutes)


def fleet_settings():
    if FLEET_DIR not in sys.path:
        sys.path.insert(0, FLEET_DIR)

    import auto_disable_10 as fleet

    headers = dict(fleet.official_headers)
    park_id = headers.get("X-Park-ID") or getattr(fleet, "PARK_ID", None)

    if not park_id:
        raise RuntimeError("Fleet PARK ID не найден")

    return headers, park_id


def normalize_phone(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 11 and digits[0] in "78":
        return "+7" + digits[1:]
    if len(digits) == 10 and digits[0] == "9":
        return "+7" + digits
    return None


def extract_phone(phones):
    for item in phones or []:
        if isinstance(item, (str, int)):
            phone = normalize_phone(item)
            if phone:
                return phone
        elif isinstance(item, dict):
            for key in ("phone", "number", "value"):
                phone = normalize_phone(item.get(key))
                if phone:
                    return phone
    return None


def profile_phones(profile):
    result = []

    for key in ("phone", "phone_number"):
        phone = normalize_phone(profile.get(key))
        if phone:
            result.append(phone)

    for item in profile.get("phones") or []:
        if isinstance(item, (str, int)):
            phone = normalize_phone(item)
        elif isinstance(item, dict):
            phone = normalize_phone(
                item.get("number") or item.get("phone") or item.get("value")
            )
        else:
            phone = None

        if phone:
            result.append(phone)

    return list(set(result))


def full_name(profile):
    return " ".join(
        part.strip()
        for part in (
            str(profile.get("last_name") or ""),
            str(profile.get("first_name") or ""),
            str(profile.get("middle_name") or ""),
        )
        if part.strip()
    ) or "Курьер"


def sync_couriers(headers, park_id):
    if not due("couriers_synced_at", PROFILE_SYNC_MINUTES):
        return

    print("[IZI BOX] Обновляем список курьеров", flush=True)
    profiles = []
    offset = 0
    limit = 1000

    while True:
        response = requests.post(
            PROFILES_URL,
            headers=headers,
            json={
                "query": {"park": {"id": park_id}},
                "limit": limit,
                "offset": offset,
            },
            timeout=30,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"profiles HTTP {response.status_code}: {response.text[:500]}"
            )

        page = response.json().get("driver_profiles", [])
        profiles.extend(page)

        if len(page) < limit:
            break

        offset += limit

    synced_at = now().isoformat()

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE courier_cache SET active = 0")

        for item in profiles:
            profile = item.get("driver_profile") or {}
            contractor_id = str(profile.get("id") or "").strip()

            if not contractor_id:
                continue

            phone = extract_phone(profile.get("phones"))
            fire_date = profile.get("fire_date")
            active = 0 if fire_date else 1

            conn.execute(
                """
                INSERT INTO courier_cache(
                    contractor_id, phone, full_name, work_rule_id,
                    work_status, fire_date, active, synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(contractor_id) DO UPDATE SET
                    phone = excluded.phone,
                    full_name = excluded.full_name,
                    work_rule_id = excluded.work_rule_id,
                    work_status = excluded.work_status,
                    fire_date = excluded.fire_date,
                    active = excluded.active,
                    synced_at = excluded.synced_at
                """,
                (
                    contractor_id,
                    phone,
                    full_name(profile),
                    profile.get("work_rule_id"),
                    profile.get("work_status"),
                    fire_date,
                    active,
                    synced_at,
                ),
            )

    set_meta("couriers_synced_at", synced_at)
    print(f"[IZI BOX] Курьеров в кэше: {len(profiles)}", flush=True)


def finish_lookup(row, status, contractor_id=None, name=None, error=None):
    with connect() as conn:
        conn.execute(
            """
            UPDATE phone_lookups SET
                status = ?, contractor_id = ?, full_name = ?,
                checked_at = ?, attempts = attempts + 1,
                next_try_at = NULL, last_error = ?
            WHERE id = ?
            """,
            (
                status,
                contractor_id,
                name,
                now().isoformat(),
                error,
                row["id"],
            ),
        )


def retry_lookup(row, error, minutes=2):
    with connect() as conn:
        conn.execute(
            """
            UPDATE phone_lookups SET
                attempts = attempts + 1,
                next_try_at = ?, last_error = ?
            WHERE id = ? AND status = 'pending'
            """,
            ((now() + timedelta(minutes=minutes)).isoformat(), error, row["id"]),
        )


def process_phone_lookup(headers, park_id):
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM phone_lookups
            WHERE status = 'pending'
              AND (next_try_at IS NULL OR next_try_at <= ?)
            ORDER BY requested_at
            LIMIT 1
            """,
            (now().isoformat(),),
        ).fetchone()

    if not row:
        return

    payload = {
        "query": {
            "park": {"id": park_id},
            "text": row["phone"],
        },
        "limit": 10,
        "offset": 0,
    }

    try:
        response = requests.post(
            PROFILES_URL,
            headers=headers,
            json=payload,
            timeout=30,
        )
    except Exception as exc:
        retry_lookup(row, repr(exc))
        return

    if response.status_code == 429:
        retry_lookup(row, "Fleet HTTP 429", minutes=2)
        print("[IZI BOX] Поиск телефона отложен из-за 429", flush=True)
        return

    if response.status_code != 200:
        retry_lookup(row, f"Fleet HTTP {response.status_code}", minutes=5)
        return

    exact = []
    for item in response.json().get("driver_profiles") or []:
        profile = item.get("driver_profile") or {}
        if row["phone"] in profile_phones(profile):
            exact.append(profile)

    if not exact:
        finish_lookup(row, "not_found", error="NOT_FOUND")
        return

    active = [profile for profile in exact if not profile.get("fire_date")]

    if len(active) > 1:
        finish_lookup(row, "ambiguous", error="AMBIGUOUS")
        return

    if not active:
        finish_lookup(row, "inactive", error="INACTIVE")
        return

    profile = active[0]
    contractor_id = str(profile.get("id") or "").strip()
    name = full_name(profile)
    synced_at = now().isoformat()

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO courier_cache(
                contractor_id, phone, full_name, work_rule_id,
                work_status, fire_date, active, synced_at
            ) VALUES (?, ?, ?, ?, ?, NULL, 1, ?)
            ON CONFLICT(contractor_id) DO UPDATE SET
                phone = excluded.phone,
                full_name = excluded.full_name,
                work_rule_id = excluded.work_rule_id,
                work_status = excluded.work_status,
                fire_date = NULL,
                active = 1,
                synced_at = excluded.synced_at
            """,
            (
                contractor_id,
                row["phone"],
                name,
                profile.get("work_rule_id"),
                profile.get("work_status"),
                synced_at,
            ),
        )
        conn.execute(
            """
            UPDATE phone_lookups SET
                status = 'found', contractor_id = ?, full_name = ?,
                checked_at = ?, attempts = attempts + 1,
                next_try_at = NULL, last_error = NULL
            WHERE id = ?
            """,
            (contractor_id, name, synced_at, row["id"]),
        )

    print(f"[IZI BOX] Телефон найден, lookup_id={row['id']}", flush=True)


def sync_orders(headers, park_id):
    with connect() as conn:
        binding_count = conn.execute("SELECT COUNT(*) FROM bindings").fetchone()[0]

    if not binding_count:
        print("[IZI BOX] Привязок пока нет, заказы не запрашиваем", flush=True)
        return

    current = now()
    current_week = (current - timedelta(days=current.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    scan_week = get_meta("orders_scan_week_start")
    cursor = get_meta("orders_scan_cursor")

    if not scan_week:
        if not due("orders_synced_at", ORDER_SYNC_MINUTES):
            return

        scan_week = current_week.isoformat()
        period_end = current.isoformat()

        with connect() as conn:
            conn.execute("DELETE FROM order_scan_items")
            conn.execute(
                "INSERT INTO izi_box_meta(key, value) VALUES ('orders_scan_week_start', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (scan_week,),
            )
            conn.execute(
                "INSERT INTO izi_box_meta(key, value) VALUES ('orders_scan_period_end', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (period_end,),
            )
            conn.execute(
                "INSERT INTO izi_box_meta(key, value) VALUES ('orders_scan_pages', '0') "
                "ON CONFLICT(key) DO UPDATE SET value = '0'"
            )

        cursor = None
        print(f"[IZI BOX] Начат снимок заказов с {scan_week}", flush=True)
    elif scan_week != current_week.isoformat():
        with connect() as conn:
            conn.execute("DELETE FROM order_scan_items")
            conn.execute(
                "DELETE FROM izi_box_meta WHERE key LIKE 'orders_scan_%'"
            )
        print("[IZI BOX] Старый снимок сброшен после смены недели", flush=True)
        return

    period_end = get_meta("orders_scan_period_end") or current.isoformat()
    payload = {
        "query": {
            "park": {
                "id": park_id,
                "order": {
                    "ended_at": {"from": scan_week, "to": period_end},
                    "statuses": ["complete"],
                },
            }
        },
        "limit": 500,
    }

    if cursor:
        payload["cursor"] = cursor

    response = requests.post(
        ORDERS_URL,
        headers=headers,
        json=payload,
        timeout=30,
    )

    if response.status_code == 429:
        print("[IZI BOX] Orders 429; страница отложена до следующего запуска", flush=True)
        return

    if response.status_code != 200:
        raise RuntimeError(
            f"orders HTTP {response.status_code}: {response.text[:500]}"
        )

    data = response.json()
    orders = data.get("orders", [])
    next_cursor = data.get("cursor")
    pages = int(get_meta("orders_scan_pages") or 0) + 1

    with connect() as conn:
        for order in orders:
            if order.get("status") != "complete":
                continue
            driver = order.get("driver_profile") or {}
            contractor_id = str(driver.get("id") or "").strip()
            order_id = str(order.get("id") or "").strip()
            if contractor_id and order_id:
                conn.execute(
                    "INSERT OR IGNORE INTO order_scan_items(week_start, contractor_id, order_id) "
                    "VALUES (?, ?, ?)",
                    (scan_week, contractor_id, order_id),
                )

        conn.execute(
            "INSERT INTO izi_box_meta(key, value) VALUES ('orders_scan_pages', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(pages),),
        )

        if next_cursor and next_cursor != cursor:
            conn.execute(
                "INSERT INTO izi_box_meta(key, value) VALUES ('orders_scan_cursor', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (next_cursor,),
            )
            print(f"[IZI BOX] Страница заказов {pages} сохранена", flush=True)
            return

        updated_at = now().isoformat()
        bindings = conn.execute("SELECT contractor_id FROM bindings").fetchall()

        for row in bindings:
            contractor_id = row["contractor_id"]
            count = conn.execute(
                "SELECT COUNT(*) FROM order_scan_items "
                "WHERE week_start = ? AND contractor_id = ?",
                (scan_week, contractor_id),
            ).fetchone()[0]
            conn.execute(
                """
                INSERT INTO weekly_progress(
                    contractor_id, week_start, completed_orders, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(contractor_id, week_start) DO UPDATE SET
                    completed_orders = excluded.completed_orders,
                    updated_at = excluded.updated_at
                """,
                (
                    contractor_id,
                    current_week.date().isoformat(),
                    int(count),
                    updated_at,
                ),
            )

        conn.execute(
            "INSERT INTO izi_box_meta(key, value) VALUES ('orders_synced_at', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (updated_at,),
        )
        conn.execute("DELETE FROM order_scan_items")
        conn.execute("DELETE FROM izi_box_meta WHERE key LIKE 'orders_scan_%'")

    print(f"[IZI BOX] Снимок заказов готов, страниц: {pages}", flush=True)


def get_profile(headers, contractor_id):
    response = requests.get(
        PROFILE_URL,
        headers=headers,
        params={"contractor_profile_id": contractor_id},
        timeout=30,
    )
    if response.status_code != 200:
        return None, f"GET profile HTTP {response.status_code}: {response.text[:500]}"
    return response.json(), None


def pick(source, keys, keep_empty=False):
    result = {}
    for key in keys:
        if key not in source or source[key] is None:
            continue
        if not keep_empty and source[key] == "":
            continue
        result[key] = source[key]
    return result


def replace_comment(old_comment, line):
    kept = [
        item for item in str(old_comment or "").splitlines()
        if not item.strip().startswith("[ИЗИ БОКС]")
    ]
    kept.append(line)
    return "\n".join(item for item in kept if item.strip()).strip()


def build_payload(source, target_rule, comment):
    account = source.get("account") or {}
    person = source.get("person") or {}
    profile = source.get("profile") or {}
    provider = source.get("order_provider") or {}

    account_update = pick(
        account,
        ["balance_limit", "payment_service_id", "block_orders_on_balance_below_limit"],
        keep_empty=True,
    )
    account_update["work_rule_id"] = target_rule

    person_update = {
        "full_name": pick(
            person.get("full_name") or {},
            ["first_name", "middle_name", "last_name"],
            keep_empty=True,
        )
    }

    contact = pick(
        person.get("contact_info") or {},
        ["address", "email", "phone"],
        keep_empty=True,
    )
    if contact:
        person_update["contact_info"] = contact

    driver_license = pick(
        person.get("driver_license") or {},
        ["birth_date", "country", "expiry_date", "issue_date", "number"],
    )
    if driver_license:
        person_update["driver_license"] = driver_license

    experience = pick(
        person.get("driver_license_experience") or {},
        ["total_since_date"],
    )
    if experience:
        person_update["driver_license_experience"] = experience

    tin = person.get("tax_identification_number")
    if tin:
        person_update["tax_identification_number"] = tin

    profile_update = pick(
        profile,
        ["hire_date", "work_status", "fire_date", "comment", "feedback"],
        keep_empty=True,
    )
    profile_update["comment"] = comment

    payload = {
        "account": account_update,
        "person": person_update,
        "profile": profile_update,
        "order_provider": {
            "platform": bool(provider.get("platform")),
            "partner": bool(provider.get("partner")),
        },
    }

    if source.get("car_id"):
        payload["car_id"] = source["car_id"]
    return payload


def put_rule(headers, contractor_id, source, target_rule, comment):
    response = requests.put(
        PROFILE_URL,
        headers=headers,
        params={"contractor_profile_id": contractor_id},
        json=build_payload(source, target_rule, comment),
        timeout=30,
    )

    if response.status_code not in (200, 204):
        return False, f"PUT HTTP {response.status_code}: {response.text[:500]}"

    time.sleep(3)
    verified, error = get_profile(headers, contractor_id)
    if error:
        return False, error

    final_rule = (verified.get("account") or {}).get("work_rule_id")
    if final_rule != target_rule:
        return False, f"Проверка не подтвердила правило: {final_rule}"
    return True, None


def audit(conn, row, event, details=""):
    conn.execute(
        """
        INSERT INTO audit_log(created_at, contractor_id, vk_user_id, event, details)
        VALUES (?, ?, ?, ?, ?)
        """,
        (now().isoformat(), row["contractor_id"], row["vk_user_id"], event, details),
    )


def mark_review(row, error):
    with connect() as conn:
        conn.execute(
            "UPDATE rewards SET status = 'manual_review', last_error = ? WHERE id = ?",
            (error, row["id"]),
        )
        audit(conn, row, "manual_review", error)


def activate_one_reward(headers):
    with connect() as conn:
        row = conn.execute(
            """
            SELECT r.* FROM rewards r
            WHERE r.status = 'pending'
              AND NOT EXISTS (
                  SELECT 1 FROM rewards active
                  WHERE active.contractor_id = r.contractor_id
                    AND active.status = 'active'
              )
            ORDER BY r.drawn_at
            LIMIT 1
            """
        ).fetchone()

    if not row:
        return

    if not APPLY_CHANGES:
        print(
            f"[IZI BOX] PREVIEW: reward_id={row['id']} ожидает включения IZI_BOX_APPLY=1",
            flush=True,
        )
        return

    profile, error = get_profile(headers, row["contractor_id"])
    if error:
        print(f"[IZI BOX] Активация отложена: {error}", flush=True)
        return

    current_rule = (profile.get("account") or {}).get("work_rule_id")

    if current_rule not in SAFE_BASE_RULES:
        mark_review(row, f"Небезопасное исходное правило: {current_rule}")
        return

    applied_at = now()
    expires_at = applied_at + timedelta(days=int(row["duration_days"]))
    old_comment = (profile.get("profile") or {}).get("comment") or ""
    comment = replace_comment(
        old_comment,
        f"[ИЗИ БОКС] {row['reward_title']} до {expires_at.strftime('%d.%m.%Y %H:%M')} МСК",
    )

    if current_rule != row["target_rule_id"]:
        ok, error = put_rule(
            headers,
            row["contractor_id"],
            profile,
            row["target_rule_id"],
            comment,
        )
        if not ok:
            print(f"[IZI BOX] PUT отложен: {error}", flush=True)
            return

    with connect() as conn:
        conn.execute(
            """
            UPDATE rewards SET
                original_rule_id = ?, status = 'active', applied_at = ?,
                expires_at = ?, last_error = NULL
            WHERE id = ? AND status = 'pending'
            """,
            (current_rule, applied_at.isoformat(), expires_at.isoformat(), row["id"]),
        )
        audit(conn, row, "reward_activated", f"{current_rule}->{row['target_rule_id']}")

    print(f"[IZI BOX] Приз активирован reward_id={row['id']}", flush=True)


def restore_one_reward(headers):
    current_time = now().isoformat()

    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM rewards
            WHERE status = 'active' AND expires_at <= ?
            ORDER BY expires_at
            LIMIT 1
            """,
            (current_time,),
        ).fetchone()

    if not row:
        return

    profile, error = get_profile(headers, row["contractor_id"])
    if error:
        print(f"[IZI BOX] Возврат отложен: {error}", flush=True)
        return

    current_rule = (profile.get("account") or {}).get("work_rule_id")
    target_rule = row["target_rule_id"]
    original_rule = row["original_rule_id"]

    if current_rule == original_rule or original_rule == target_rule:
        changed = False
    elif current_rule != target_rule:
        mark_review(
            row,
            f"Правило изменено вручную: ожидалось {target_rule}, сейчас {current_rule}",
        )
        return
    else:
        old_comment = (profile.get("profile") or {}).get("comment") or ""
        comment = replace_comment(
            old_comment,
            f"[ИЗИ БОКС] Завершён {now().strftime('%d.%m.%Y %H:%M')} МСК",
        )
        ok, error = put_rule(
            headers,
            row["contractor_id"],
            profile,
            original_rule,
            comment,
        )
        if not ok:
            print(f"[IZI BOX] Возврат PUT отложен: {error}", flush=True)
            return
        changed = True

    with connect() as conn:
        conn.execute(
            """
            UPDATE rewards SET status = 'completed', restored_at = ?, last_error = NULL
            WHERE id = ? AND status = 'active'
            """,
            (now().isoformat(), row["id"]),
        )
        audit(conn, row, "reward_completed", f"restored={changed}; rule={original_rule}")

    print(f"[IZI BOX] Приз завершён reward_id={row['id']}", flush=True)


def main():
    init_db()
    headers, park_id = fleet_settings()

    # Один запуск выполняет только одну Fleet-задачу. Возврат комиссии имеет
    # наивысший приоритет, затем включение приза, привязка телефона и только
    # после этого одна страница недельных заказов.
    with connect() as conn:
        overdue_reward = conn.execute(
            "SELECT 1 FROM rewards WHERE status = 'active' AND expires_at <= ? LIMIT 1",
            (now().isoformat(),),
        ).fetchone()
        pending_reward = conn.execute(
            "SELECT 1 FROM rewards WHERE status = 'pending' LIMIT 1"
        ).fetchone()
        pending_lookup = conn.execute(
            """
            SELECT 1 FROM phone_lookups
            WHERE status = 'pending'
              AND (next_try_at IS NULL OR next_try_at <= ?)
            LIMIT 1
            """,
            (now().isoformat(),),
        ).fetchone()

    if overdue_reward:
        try:
            restore_one_reward(headers)
        except Exception as exc:
            print(f"[IZI BOX] Ошибка возврата: {exc!r}", flush=True)
        return

    if pending_reward:
        try:
            activate_one_reward(headers)
        except Exception as exc:
            print(f"[IZI BOX] Ошибка активации: {exc!r}", flush=True)
        return

    if pending_lookup:
        try:
            process_phone_lookup(headers, park_id)
        except Exception as exc:
            print(f"[IZI BOX] Ошибка поиска телефона: {exc!r}", flush=True)
        return

    try:
        sync_orders(headers, park_id)
    except Exception as exc:
        print(f"[IZI BOX] Ошибка синхронизации заказов: {exc!r}", flush=True)


if __name__ == "__main__":
    main()

from __future__ import annotations
import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

import aiohttp


class InvalidCredsError(Exception):
    """Ошибка неверных учетных данных."""


class ParseError(Exception):
    """Ошибка парсинга данных журнала."""


class JournalParser:
    """Асинхронный парсер электронного журнала edu-tpi.donstu.ru на основе реального API."""

    BASE_URL = "https://edu-tpi.donstu.ru"
    AUTH_URL = f"{BASE_URL}/api/tokenauth"
    FP_URL = f"{BASE_URL}/api/UserInfo/Devices/RandomIdentity"
    JOURNALS_URL = f"{BASE_URL}/api/Journals/JournalList"
    JOURNAL_URL = f"{BASE_URL}/api/Journals/Journal"

    def parse_iso_date(self, s: str) -> date:
        """Парсит ISO дату из journalDates."""
        s = s.replace("T000000", "T00:00:00")
        return datetime.fromisoformat(s).date()

    def find_student_row(
        self,
        journal_data: list[dict[str, Any]],
        *,
        student_id: int | None = None,
        fio: str | None = None,
        full_name: str | None = None,
    ) -> dict[str, Any]:
        """
        Ищет строку студента в journalData.
        Если параметры не указаны, возвращает первую строку (предполагаем одного студента).
        """
        for row in journal_data:
            if student_id is not None and str(row.get("id")) == str(student_id):
                return row
            if fio is not None and row.get("fio") == fio:
                return row
            if full_name is not None and row.get("fullName") == full_name:
                return row
        if student_id is None and fio is None and full_name is None and journal_data:
            return journal_data[0]
        msg = "Студент не найден в journalData"
        raise ParseError(msg)

    def get_student_lessons_last_days_from_journal(
        self,
        journal_json: dict[str, Any],
        *,
        days: int = 730,
        student_id: int | None = None,
        fio: str | None = None,
        full_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Парсит занятия студента из одного журнала за последние `days` дней.
        Возвращает list[dict] {lesson_date:date, hour_number:int, display_value:str, kind:str}.
        """
        data = journal_json["data"]

        journal_vals: list[dict[str, Any]] = data["journalVal"]
        journal_data: list[dict[str, Any]] = data["journalData"]
        journal_dates: list[dict[str, Any]] = data["journalDates"]

        val_by_id: dict[int, dict[str, Any]] = {
            int(v["id"]): v
            for v in journal_vals  # id значения -> объект значения
        }

        student_row = self.find_student_row(
            journal_data,
            student_id=student_id,
            fio=fio,
            full_name=full_name,
        )

        today = datetime.now(timezone.utc).date()
        cutoff = today - timedelta(days=days)

        lessons: list[dict[str, Any]] = []

        for jd in journal_dates:
            d = self.parse_iso_date(jd["date"])
            if d < cutoff:
                continue

            date_id = jd["dateID"]
            key = str(date_id)
            raw_cell = student_row.get(key)
            if raw_cell is None:
                continue

            try:
                value_id = int(raw_cell)
            except (TypeError, ValueError):
                continue

            val_obj = val_by_id.get(value_id)
            if val_obj is None:
                continue

            is_mark = bool(val_obj.get("isMark"))
            is_pass = bool(val_obj.get("isPass"))

            kind = "оценка" if is_mark else "посещаемость" if is_pass else ""

            display_value = val_obj.get("value") or ""

            lessons.append(
                {
                    "lesson_date": d,
                    "hour_number": int(jd["hourNumber"]),
                    "display_value": display_value,
                    "kind": kind,
                }
            )

        lessons.sort(key=lambda x: (x["lesson_date"], x["hour_number"]))
        return lessons

    async def parse_grades(self, username: str, password: str) -> list[dict[str, Any]]:  # noqa: C901, PLR0915
        """
        Парсит оценки: list[{'subject': {'code': str, 'name': str, 'teacher': str},
                             'grades': [{'date': str (iso), 'value': str, 'type': str, 'comment': str}]}]
        """
        timeout = aiohttp.ClientTimeout(total=60)

        # Получить fingerprint
        async with aiohttp.ClientSession(timeout=timeout) as session, session.get(self.FP_URL) as resp:
            resp.raise_for_status()
            fp_json = await resp.json()
            fp = fp_json["data"]["randomIdentity"]

        # Получить token
        token_data = {
            "fingerprint": fp,
            "userName": username,
            "password": password,
        }
        http_ok = 200
        async with aiohttp.ClientSession(timeout=timeout) as session:  # noqa: SIM117
            async with session.post(self.AUTH_URL, json=token_data) as resp:
                if resp.status != http_ok:
                    msg = f"Auth failed: status {resp.status}"
                    raise InvalidCredsError(msg)
                try:
                    token_json = await resp.json()
                except json.JSONDecodeError as e:
                    msg = "Invalid auth response"
                    raise InvalidCredsError(msg) from e
                if "data" not in token_json or "accessToken" not in token_json["data"]:
                    msg = "No accessToken in auth response"
                    raise InvalidCredsError(msg)
                token = token_json["data"]["accessToken"]

        headers = {"Authorization": f"Bearer {token}"}
        async with aiohttp.ClientSession(
            headers=headers,
            timeout=timeout,  # Client с токеном
        ) as client:
            # Определить учебный год
            now = datetime.now(timezone.utc)
            september = 9
            http_unauthorized = 401
            year = f"{now.year}-{now.year + 1}" if now.month >= september else f"{now.year - 1}-{now.year}"

            parsed_data: list[dict[str, Any]] = []

            # Для обоих семестров
            for sem in [1, 2]:
                params = {
                    "prepID": "undefined",
                    "groupID": "undefined",
                    "typeJournal": "1",
                    "year": year,
                    "sem": str(sem),
                }
                async with client.get(self.JOURNALS_URL, params=params) as resp:
                    if resp.status == http_unauthorized:
                        msg = "Invalid token"
                        raise InvalidCredsError(msg)
                    resp.raise_for_status()
                    journals_json = await resp.json()

                journals = journals_json["data"]["returnList"]

                for j in journals:
                    await asyncio.sleep(1)  # Rate limit

                    journal_id = int(j["id"])

                    # Получить журнал
                    j_params = {"journalID": str(journal_id)}
                    async with client.get(self.JOURNAL_URL, params=j_params) as resp:
                        if resp.status == http_unauthorized:
                            msg = "Invalid token"
                            raise InvalidCredsError(msg)
                        resp.raise_for_status()
                        journal_json = await resp.json()

                    data = journal_json.get("data")
                    if not data:
                        continue

                    info = data.get("journalInfo", {})
                    discipline = (info.get("dis") or j.get("dis") or "").strip()
                    (info.get("type") or j.get("type") or "").strip()
                    teacher_name = (info.get("teacherName") or j.get("prepodName") or "").strip()

                    if not discipline:
                        continue

                    # Парсинг уроков (первый студент)
                    lessons = self.get_student_lessons_last_days_from_journal(journal_json, days=730)

                    grades = [
                        {
                            "date": lesson["lesson_date"].isoformat(),
                            "value": lesson["display_value"],
                            "type": lesson["kind"],
                            "comment": "",
                        }
                        for lesson in lessons
                    ]

                    if grades:
                        parsed_data.append(
                            {
                                "subject": {
                                    "code": str(journal_id),
                                    "name": discipline,
                                    "teacher": teacher_name,
                                },
                                "grades": grades,
                            }
                        )

            if not parsed_data:
                msg = "Не найдены предметы или оценки"
                raise ParseError(msg)

            return parsed_data

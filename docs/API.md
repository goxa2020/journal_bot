# API edu-tpi

**Версия:** 1.0 · **Дата:** 18.11.2026
**Источник:** ответы реального API, зафиксированные в [archive/technical-bot-architecture.md](archive/technical-bot-architecture.md),
и реализация в [bot/integrations/edu_tpi.py](../bot/integrations/edu_tpi.py) (в фазе 2
заменила `services/api_client.py` и `services/journal_parser.py`).

> API неофициальный и не документирован. Всё ниже — наблюдения, а не контракт.
> При расхождении с живыми ответами правится этот файл и тестовые фикстуры в `tests/fixtures/edu_tpi/`.

## 1. Общие правила

| Параметр | Значение |
|---|---|
| База | `https://edu-tpi.donstu.ru` |
| Формат | JSON, `Content-Type: application/json` |
| Авторизация | `Authorization: Bearer <accessToken>` |
| Срок жизни токена | `expiresIn` **минут** (типично 10080 = 7 дней) |
| Лимит запросов | не опубликован; держим ≤ 1 запроса/с на токен |
| Время | даты приходят без часового пояса; часовой пояс приложения — Europe/Moscow |

Заголовки для защищённых методов:

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Правила использования

1. Один `accessToken` — один студент. Токен живёт 7 дней, повторный вход не нужен, если он в кеше.
2. Запрос деталей журнала — самый тяжёлый вызов (в ответе вся группа). Кешировать на 15 минут.
3. `journalData` содержит не только запросившего студента — это и есть основа группового кеша.
4. Параметры `prepID` и `groupID` в списке журналов принимаются как строка `"undefined"` —
   сервер сам определяет студента по токену.
5. Учебный год определяется по дате: с сентября `YYYY-(YYYY+1)`, до сентября `(YYYY-1)-YYYY`.
   Запрашивается только текущий семестр: следующий ещё не начался, а его журналы пустые.
   Оценки прошлых семестров уже лежат в БД.

---

## 2. Fingerprint

`GET /api/UserInfo/Devices/RandomIdentity`

Обязателен при входе: привязывает токен к «устройству».

**Ответ**

```json
{
  "data": {
    "randomIdentity": "9f1c2e7a-4b3d-4f5e-8a6b-1c2d3e4f5a6b"
  },
  "state": 1
}
```

| Поле | Тип | Использование |
|---|---|---|
| `data.randomIdentity` | string | передаётся в теле `POST /tokenauth` |

Ошибки: `5xx` → retry; структура без `data.randomIdentity` → `ParseError`.

---

## 3. Вход

`POST /api/tokenauth`

**Тело**

```json
{
  "userName": "student@donstu.ru",
  "password": "secret",
  "fingerprint": "randomIdentity из шага 2"
}
```

**Ответ (успех)**

```json
{
  "data": {
    "userName": "Максимов Г.К.",
    "accessToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "expiresIn": 10080.0,
    "id": -22069
  },
  "state": 1
}
```

| Поле | Тип | Использование |
|---|---|---|
| `data.accessToken` | string | `Bearer`-токен для всех защищённых методов |
| `data.expiresIn` | number | срок жизни **в минутах**; TTL кеша = `expiresIn * 60 − 300` |
| `data.id` | int | ID пользователя edu-tpi, совпадает с `user.userID` |
| `data.userName` | string | краткое ФИО, для логов не нужно |

**Критично для реализации:** ключ называется `accessToken` (camelCase), а не
`access_token` (исправлено в фазе 0, задача 0.1).

**Ошибки**

| Ответ | Причина | Действие клиента |
|---|---|---|
| `200`, но нет `data.accessToken` | неверный формат ответа или отказ | `EduAuthError` |
| `400/401/403` | неверный логин или пароль | `EduAuthError`, без retry |
| `5xx`, таймаут | сбой сервера | `EduUnavailableError`, retry 3× |

---

## 4. Информация о пользователе / проверка токена

`GET /api/tokenauth` с `Authorization: Bearer <token>`

**Ответ**

```json
{
  "state": 1,
  "data": {
    "userName": "student@donstu.ru",
    "user": {
      "userID": -22069,
      "groupID": 3273,
      "group": "584 ис-3",
      "fio": "Максимов Г.К.",
      "fullName": "Максимов Георгий Константинович"
    }
  }
}
```

| Поле | Куда сохраняем |
|---|---|
| `user.userID` | `users.edu_user_id` — ключ строки в `journalData` |
| `user.groupID` | `users.group_id` — ключ группового кеша |
| `user.group` | `users.group_name` |
| `user.fio` | `users.full_name` (краткая форма, для сообщений) |
| `user.fullName` | не храним, используется для сопоставления при необходимости |

Этот же вызов — способ проверить валидность токена без повторного входа.
`401` → токен недействителен: переавторизоваться по сохранённым данным.

---

## 5. Список журналов

`GET /api/Journals/JournalList`

**Параметры**

| Параметр | Значение | Примечание |
|---|---|---|
| `prepID` | `undefined` | определяется по токену |
| `groupID` | `undefined` | определяется по токену |
| `typeJournal` | `1` | журнал успеваемости |
| `year` | `2025-2026` | учебный год |
| `sem` | `1` или `2` | запрашиваются оба |

**Ответ**

```json
{
  "data": {
    "returnList": [
      {
        "id": 27919,
        "groupName": "584 ис-3",
        "dis": "Программирование",
        "type": "Лек",
        "year": "2025-2026",
        "prepodName": "Иванов И.И.",
        "dateCount": 16,
        "maxDateCount": 26.0,
        "passes": 0
      }
    ],
    "fillingProcent": 67
  }
}
```

| Поле | Использование |
|---|---|
| `id` | `journals.id`, ключ запроса деталей |
| `dis` | `journals.name` |
| `type` | `journals.type` (`Лек`/`Пр`/`Лаб`) |
| `prepodName` | `journals.teacher_name` |
| `groupName` | для проверки, что группа совпадает |
| `dateCount`, `maxDateCount`, `passes`, `fillingProcent` | **не используем** — считаем из БД |

Пустой `returnList` — нормальная ситуация (нет журналов в семестре), не ошибка.

---

## 6. Детали журнала

`GET /api/Journals/Journal?journalID=<id>`

**Ответ**

```json
{
  "data": {
    "isSubGroup": false,
    "journalID": 27919,
    "journalVal": [
      {"id": 6,  "value": "",  "isMark": false, "isPass": false},
      {"id": 7,  "value": "Н", "isMark": false, "isPass": true},
      {"id": 10, "value": "4", "numberValue": 4.0, "isMark": true}
    ],
    "journalData": [
      {
        "id": "22069",
        "fio": "Максимов Г.К.",
        "fullName": "Максимов Георгий Константинович",
        "346734": "10",
        "346950": "6"
      }
    ],
    "journalDates": [
      {"dateID": 346734, "date": "2024-09-30T00:00:00", "hourNumber": 1},
      {"dateID": 346950, "date": "2024-10-07T00:00:00", "hourNumber": 2}
    ],
    "journalLegend": {
      "   ": "Студент отсутствовал",
      "Н  ": "Студент отсутствовал",
      "Б  ": "Болезнь",
      "О  ": "Опоздал",
      "У  ": "Уважительная причина"
    },
    "journalInfo": {
      "dis": "Программирование",
      "type": "Лек",
      "teacherName": "Иванов И.И.",
      "year": "2024-2025"
    }
  }
}
```

### 6.1 Как связаны массивы

```
journalDates[].dateID        ── ключ колонки в строке студента
journalData[0]["346734"]     ── id значения из journalVal ("10")
journalVal[id=10]            ── {value, numberValue, isMark, isPass}
journalDates[].hourNumber    ── номер пары в этот день
```

Алгоритм для одного студента:

1. Найти строку в `journalData` по `id == users.edu_user_id` (fallback: `fio`, `fullName`).
2. Для каждой `journalDates` взять `studentRow[str(dateID)]` — если ключа нет, занятия не было.
3. Полученный id найти в словаре `journalVal` — это значение и флаги.
4. Сохранить `(date, hourNumber, value, numberValue, isMark, isPass, is_valid_pass)`.

### 6.2 Подвохи

| Подвох | Следствие |
|---|---|
| `journalData` содержит **всю группу** (или подгруппу при `isSubGroup: true`) | один запрос закрывает всех участников группы — используем для группового кеша |
| `value` приходит с хвостовыми пробелами (`"Н  "`) | обязательный `strip()` перед сохранением, иначе диф оценок всегда «новая» |
| `dateID` одинаков у всех студентов | **не может быть PK** таблицы `grades` (см. §2.1 ROADMAP) |
| `isSubGroup: true` | в ответе только подгруппа; кеш различается по хешу списка студентов |
| `date` иногда приходит как `...T000000` | в парсере есть замена на `T00:00:00` |
| `journalVal` содержит служебные записи (пустые, `isMark=false`, `isPass=false`) | сохранять не нужно, но и падать нельзя |
| порядок студентов в `journalData` не гарантирован | искать по `id`, а не по индексу |
| архивный журнал: `200`, `state: -2`, `data: null` | не ошибка схемы: пропускаем журнал (`EduEmptyJournalError`), синхронизация продолжается |

### 6.3 Флаги и легенда

| Значение | `isMark` | `isPass` | `is_valid_pass` | Смысл |
|---|---|---|---|---|
| `1`…`5` | true | false | false | оценка, `number_value` = 1–5 |
| `Н` | false | true | false | пропуск |
| `О` | false | true | false | опоздал |
| `У` | false | true | **true** | уважительная причина |
| `Б` | false | true | **true** | болезнь |
| пусто | false | false | false | нет занятия / не отмечено |

`is_valid_pass` API отдельным флагом не отдаёт — выводим из значения (`У`, `Б`).
Таблица отражает ожидаемое поведение; при расхождении доверяем флагам `isMark`/`isPass`
из `journalVal`, а не выводу по строке.
`journalLegend` кешируется глобально (`journal_legend:global`, 30 дней) и используется
в легенде таблицы оценок.

---

## 7. Ошибки и стратегия

| Код/ситуация | Исключение | Retry | Действие |
|---|---|---|---|
| `200` с неожиданной структурой | `ParseError` | нет | лог, алерт админу, `sync_logs.status=failed` |
| `200`, `state: -2`, `data: null` | `EduEmptyJournalError` | нет | журнал пропускается, синхронизация не падает |
| `400/401/403` на входе | `EduAuthError` | нет | «логин или пароль неверны» |
| `401` на защищённом методе | `EduTokenExpired` | 1 раз | переавторизация по сохранённым данным |
| `401` после переавторизации | `EduAuthError` | нет | сбросить токен, попросить войти заново |
| `429` | `EduRateLimitError` | 3× | пауза больше обычной, `Retry-After` если есть |
| `5xx`, таймаут | `EduUnavailableError` | 3× | 60/120/240 с |

Общий таймаут запроса — 60 с. Соединения не переиспользуются между задачами Celery.

---

## 8. Соответствие клиенту

| Метод `EduTpiClient` (целевой) | Эндпоинт | Реализация (фаза 2) |
|---|---|---|
| `get_fingerprint()` | `GET /api/UserInfo/Devices/RandomIdentity` | ✅ `bot/integrations/edu_tpi.py` |
| `authorize(login, password)` | `POST /api/tokenauth` | ✅ `TokenInfo` |
| `get_user_info(token)` | `GET /api/tokenauth` | ✅ `EduUser` |
| `list_journals(token, year, sem)` | `GET /api/Journals/JournalList` | ✅ `JournalBrief` |
| `get_journal(token, journal_id)` | `GET /api/Journals/Journal` | ✅ `JournalPayload` |
| `parse_lessons(payload, edu_user_id)` | — (локально) | ✅ `JournalPayload.lessons_for` |

Рефакторинг задачи 2.2 выполнен: один клиент, запросы отдельно от разбора, ответы —
типизированные объекты `bot/integrations/models.py`.

---

## 9. Ручная проверка

```bash
# 1. fingerprint
curl -s https://edu-tpi.donstu.ru/api/UserInfo/Devices/RandomIdentity

# 2. токен
curl -s -X POST https://edu-tpi.donstu.ru/api/tokenauth \
  -H 'Content-Type: application/json' \
  -d '{"userName":"LOGIN","password":"PASSWORD","fingerprint":"FP"}'

# 3. кто я
curl -s https://edu-tpi.donstu.ru/api/tokenauth -H 'Authorization: Bearer TOKEN'

# 4. журналы семестра
curl -s -G https://edu-tpi.donstu.ru/api/Journals/JournalList \
  -H 'Authorization: Bearer TOKEN' \
  --data-urlencode 'prepID=undefined' --data-urlencode 'groupID=undefined' \
  --data-urlencode 'typeJournal=1' --data-urlencode 'year=2025-2026' --data-urlencode 'sem=1'

# 5. журнал
curl -s -G https://edu-tpi.donstu.ru/api/Journals/Journal \
  -H 'Authorization: Bearer TOKEN' --data-urlencode 'journalID=27919'
```

Ответы **не коммитить**: в них ФИО и оценки других студентов. Для тестов сохранять только
обезличенные фрагменты в `tests/fixtures/edu_tpi/`.

---

## 10. Чек-лист при изменении API

1. Сохранить обезличенный ответ в `tests/fixtures/edu_tpi/`.
2. Обновить этот файл: поле, тип, что делаем.
3. Поправить парсер и добавить/обновить тест.
4. Прогнать `pytest tests/unit/test_edu_tpi_client.py`.
5. Проверить на реальном аккаунте `/sync` и `/grades`.
6. Отметить в [ROADMAP.md](ROADMAP.md), если задача меняет объём.

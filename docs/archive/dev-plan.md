# 📋 План разработки Telegram-бота для edu-tpi журнала
## Состояние на: 13.12.2025

**Частично реализовано:**
- 🟡 Authentication - есть основа, нужна доработка
- 🟡 Cache (Redis) - инфраструктура, нужно интегрировать
- 🟡 API client для edu-tpi - есть парсер, нужна полная интеграция
- 🟡 FSM (Finite State Machine) - нужна реализация для авторизации

**Отсутствует (Tier 1 - критично):**
- ❌ **Celery workers** - главный компонент архитектуры v4.0
- ❌ **Celery tasks** - все фоновые задачи
- ❌ **Celery scheduler** - периодические задачи (6ч, 5мин, и т.д.)
- ❌ **Notification service** - отправка уведомлений
- ❌ **Delayed notifications** - отложенные и групповые уведомления
- ❌ **Watch mode** - режим ожидания оценок
- ❌ **Export service** - экспорт в Excel/PDF
- ❌ **Handlers основные** - /start, /login, /logout, /grades, /stats, /sync, /settings
- ❌ **Callback handlers** - для inline кнопок
- ❌ **Inline keyboards** - все кнопки по архитектуре интерфейса
- ❌ **Localization** - i18n (ru/en)
- ❌ **Statistics service** - вычисление статистики
- ❌ **Rate limiting middleware** - защита от спама
- ❌ **Prometheus metrics** - метрики для Celery
- ❌ **Sentry integration** - логирование ошибок

**Отсутствует (Tier 2 - функциональное):**
- ❌ **Admin panel** - Flask-Admin интеграция
- ❌ **Flower** - UI для мониторинга Celery
- ❌ **Grafana dashboards** - визуализация метрик
- ❌ **Docker compose с Prometheus** - мониторинг

---

## 📈 Фазы разработки и приоритизация

### **Фаза 1: Критическая инфраструктура (неделя 1-2)**
Без этого бот не будет работать вообще.

| № | Задача | Статус | Время | Приоритет |
|---|--------|--------|-------|-----------|
| 1.1 | **Celery Setup** - конфиг, broker, backend | ❌ | 2h | 🔴 КРИТИЧНО |
| 1.2 | **Celery tasks** - базовая структура sync_user_task | ❌ | 3h | 🔴 КРИТИЧНО |
| 1.3 | **Celery scheduler** (APScheduler) - регистрация периодических задач | ❌ | 2h | 🔴 КРИТИЧНО |
| 1.4 | **AuthService** - полная реализация + encryption | ⚠️ Частично | 4h | 🔴 КРИТИЧНО |
| 1.5 | **GradeSyncService** - основной алгоритм синхронизации | ⚠️ Частично | 6h | 🔴 КРИТИЧНО |
| 1.6 | **FSM для авторизации** - /login, ввод логина/пароля, сохранение | ❌ | 3h | 🔴 КРИТИЧНО |
| **Фаза 1 Итого** | | | **~20h** | |

---

### **Фаза 2: Основной интерфейс (неделя 2-3)**
Основные команды и inline кнопки по архитектуре v1.0.

| № | Задача | Статус | Время | Приоритет |
|---|--------|--------|-------|-----------|
| 2.1 | **Command handlers** (/start, /login, /logout) | ❌ | 2h | 🔴 КРИТИЧНО |
| 2.2 | **Command handlers** (/grades, /stats, /sync, /settings, /help) | ❌ | 4h | 🔴 КРИТИЧНО |
| 2.3 | **Inline keyboards** - главное меню, навигация | ❌ | 3h | 🔴 КРИТИЧНО |
| 2.4 | **Callback handlers** - обработка нажатий на кнопки | ❌ | 4h | 🔴 КРИТИЧНО |
| 2.5 | **Grades display** - таблица оценок (edit_message) | ❌ | 5h | 🔴 КРИТИЧНО |
| 2.6 | **Settings menu** - уведомления, профиль | ❌ | 3h | 🔴 КРИТИЧНО |
| **Фаза 2 Итого** | | | **~21h** | |

---

### **Фаза 3: Уведомления и режимы (неделя 3-4)**
Все виды уведомлений по архитектуре v4.0.

| № | Задача | Статус | Время | Приоритет |
|---|--------|--------|-------|-----------|
| 3.1 | **NotificationService** - базовая отправка | ❌ | 2h | 🔴 КРИТИЧНО |
| 3.2 | **Grade notifications** - уведомление о новой оценке | ❌ | 2h | 🔴 КРИТИЧНО |
| 3.3 | **Delayed notifications** - отложенные (ночь до утра) | ❌ | 3h | 🔴 КРИТИЧНО |
| 3.4 | **Grouped notifications** - группировка ночных оценок | ❌ | 2h | 🔴 КРИТИЧНО |
| 3.5 | **Watch mode** - режим ожидания (30 мин, синхр каждые 5 мин) | ❌ | 4h | 🔴 КРИТИЧНО |
| 3.6 | **Monthly digest** - месячный дайджест с графиками | ❌ | 4h | 🟡 ВАЖНО |
| **Фаза 3 Итого** | | | **~17h** | |

---

### **Фаза 4: Экспорт и расширенные возможности (неделя 4-5)**

| № | Задача | Статус | Время | Приоритет |
|---|--------|--------|-------|-----------|
| 4.1 | **ExportService** - экспорт в Excel | ❌ | 3h | 🟡 ВАЖНО |
| 4.2 | **StatisticsService** - вычисление статистики | ❌ | 4h | 🟡 ВАЖНО |
| 4.3 | **DictionaryService** - легенда, справочники | ❌ | 2h | 🟡 ВАЖНО |
| 4.4 | **Localization (i18n)** - ru/en | ❌ | 3h | 🟡 ВАЖНО |
| 4.5 | **Export button callback** - экспорт из интерфейса | ❌ | 2h | 🟡 ВАЖНО |
| **Фаза 4 Итого** | | | **~14h** | |

---

### **Фаза 5: Мониторинг и безопасность (неделя 5-6)**

| № | Задача | Статус | Время | Приоритет |
|---|--------|--------|-------|-----------|
| 5.1 | **Rate limiting middleware** - защита от спама | ❌ | 2h | 🟡 ВАЖНО |
| 5.2 | **Prometheus metrics** - интеграция celery-prometheus-exporter | ❌ | 2h | 🟡 ВАЖНО |
| 5.3 | **Sentry integration** - логирование ошибок | ❌ | 1h | 🟡 ВАЖНО |
| 5.4 | **Flower setup** - UI для Celery | ❌ | 1h | 🟡 ВАЖНО |
| 5.5 | **Docker-compose обновление** - Prometheus, Redis | ❌ | 2h | 🟡 ВАЖНО |
| **Фаза 5 Итого** | | | **~8h** | |

---

### **Фаза 6: Админ панель и доп. инструменты (неделя 6-7)**

| № | Задача | Статус | Время | Приоритет |
|---|--------|--------|-------|-----------|
| 6.1 | **Flask-Admin setup** - интеграция с проектом | ❌ | 2h | 🟢 ЖЕЛАТЕЛЬНО |
| 6.2 | **Admin views** - Users, Grades, Subjects, SyncLogs | ❌ | 3h | 🟢 ЖЕЛАТЕЛЬНО |
| 6.3 | **Grafana dashboards** - Performance, Celery, Sync метрики | ❌ | 4h | 🟢 ЖЕЛАТЕЛЬНО |
| **Фаза 6 Итого** | | | **~9h** | |

---

### **Фаза 7: Тестирование и оптимизация (неделя 7-8)**

| № | Задача | Статус | Время | Приоритет |
|---|--------|--------|-------|-----------|
| 7.1 | **Unit tests** - сервисы (AuthService, JournalParser, GradeSyncService) | ❌ | 6h | 🟡 ВАЖНО |
| 7.2 | **Integration tests** - полные сценарии авторизации и синхронизации | ❌ | 5h | 🟡 ВАЖНО |
| 7.3 | **Performance testing** - нагрузочное тестирование | ❌ | 3h | 🟡 ВАЖНО |
| 7.4 | **UI тестирование** - проверка интерфейса на реальном боте | ❌ | 4h | 🟡 ВАЖНО |
| 7.5 | **Bug fixes и оптимизация** - по результатам тестирования | ❌ | 5h | 🟡 ВАЖНО |
| **Фаза 7 Итого** | | | **~23h** | |

---

## 🎯 Детальный план по компонентам

### **1️⃣ CELERY SETUP (Фаза 1.1)**

**Файлы для создания:**
- `bot/celery_app.py` - конфигурация Celery
- `bot/celery_config.py` - параметры (broker, backend, TTL и т.д.)
- `bot/celery_tasks.py` - регистрация всех tasks

**Что реализовать:**
```
✓ Celery app инициализация
✓ Redis broker конфигурация (база 1)
✓ Redis backend для результатов (база 2)
✓ JSON сериализация
✓ Timezone: Europe/Moscow
✓ Task acknowledgement: Late
✓ Worker prefetch: 1
✓ Timeout: 300 сек
✓ Soft timeout: 270 сек
```

**Зависимости:** celery, redis, flower

**Тестирование:**
- Убедиться, что Celery подключается к Redis
- Проверить создание простой задачи

---

### **2️⃣ CELERY TASKS (Фаза 1.2-1.3)**

**Критичные tasks:**

```python
@app.task(priority=9)
def sync_user_manual_task(user_id):
    """Ручная синхронизация. Вызывается из /sync"""
    # Вызов GradeSyncService.sync_user_grades()
    # Отправка результата пользователю через Bot API
    # Retry: до 3 попыток

@app.task(priority=9)
def sync_user_after_login_task(user_id):
    """Синхронизация после авторизации"""
    # Вызов GradeSyncService.sync_user_grades()

@app.task(priority=5)
def sync_watch_mode_users_task():
    """Синхронизация пользователей в режиме ожидания. Каждые 5 мин"""
    # Получить users с watch_mode_expires_at > now()
    # Для каждого: GradeSyncService.sync_user_grades()
    # Отправить уведомления

@app.task(priority=5)
def send_delayed_notification_task(user_id, grade_data):
    """Отложенное уведомление с countdown"""
    # Отправить через Bot API

@app.task(priority=5)
def send_night_accumulated_notifications_task():
    """Отправка накопленных ночных уведомлений"""
    # Получить из Redis notifications:night:*
    # Сформировать сообщение
    # Отправить через Bot API

@app.task(priority=1)
def sync_all_users_task():
    """Автоматическая синхронизация. Каждые 6 часов"""
    # Получить всех users
    # Групировать по group_id
    # Итеративная обработка подгрупп
    # Отправить метрики в Prometheus

@app.task(priority=1)
def send_monthly_digests_task():
    """Месячные дайджесты. 31 число, 12:00"""
    # Получить users с monthly_digest_enabled=True
    # Генерация отчётов
    # Отправка через Bot API

@app.task(priority=1)
def cleanup_old_logs_task():
    """Очистка старых логов. Каждые 2 дня, 3:00"""
    # Удалить логи старше 30 дней

@app.task(priority=1)
def cleanup_expired_watch_mode_task():
    """Очистка истекшего режима ожидания. Каждый час"""
    # Удалить records где watch_mode_expires_at < now()
    # Очистить Redis keys

@app.task(priority=1)
def collect_metrics_task():
    """Сбор метрик. Каждый час"""
    # Подсчёт активных пользователей
    # Среднее время синхронизации
    # Отправка в Prometheus
```

**BackgroundScheduler (APScheduler):**
- Запуск в bot/__main__.py при старте бота
- Регистрация всех периодических tasks
- Не блокирует main thread (используется background executor)

---

### **3️⃣ AUTHENTICATION & FSM (Фаза 1.4-1.6)**

**Файлы для доработки:**
- `bot/core/auth_service.py` - AuthService (доработать)
- `bot/handlers/message/auth_fsm.py` - NEW, FSM для /login
- `bot/core/encryption.py` - Encryption service

**AuthService должен иметь:**
```python
class AuthService:
    async def get_fingerprint(token: str) -> str:
        """Получить fingerprint"""

    async def authorize(username: str, password: str) -> AuthToken:
        """Авторизация пользователя"""

    async def get_user_info(token: str) -> UserInfo:
        """Получить информацию о пользователе"""

    async def validate_token(token: str) -> bool:
        """Проверить валидность токена"""

    async def refresh_token_if_needed(user_id: int) -> str:
        """Обновить токен если нужно"""
```

**FSM для /login:**
```
State: WaitingForEmail
  -> User вводит email
  -> Валидация (format check)
  -> State: WaitingForPassword

State: WaitingForPassword
  -> User вводит пароль
  -> Валидация (не пусто)
  -> State: AuthorizingUser
  -> Celery task: sync_user_after_login_task

State: AuthorizingUser
  -> Показать "⏳ Авторизация запущена..."
  -> После task: "✅ Авторизация успешна!"
  -> Показать результаты синхронизации
  -> Переход на главное меню
```

---

### **4️⃣ MAIN HANDLERS (Фаза 2.1-2.2)**

**Создать:**
- `bot/handlers/commands/start.py` - /start (онбординг)
- `bot/handlers/commands/login.py` - /login (FSM, уже в message/auth_fsm.py)
- `bot/handlers/commands/logout.py` - /logout
- `bot/handlers/commands/grades.py` - /grades
- `bot/handlers/commands/stats.py` - /stats
- `bot/handlers/commands/sync.py` - /sync
- `bot/handlers/commands/settings.py` - /settings
- `bot/handlers/commands/help.py` - /help

**Каждый handler должен:**
- Проверять аутентификацию пользователя
- Отправлять сообщение с inline кнопками
- Обрабатывать ошибки

**Примеры:**

```python
# /start
@router.message(Command("start"))
async def cmd_start(message: Message):
    if is_authenticated(user_id):
        # Главное меню
    else:
        # Онбординг

# /login (через FSM)
# Обработано в FSM

# /logout
@router.message(Command("logout"))
async def cmd_logout(message: Message):
    # Удалить токен из Redis
    # Удалить зашифрованные данные
    # Очистить настройки
    # Ответить с главным меню

# /grades
@router.message(Command("grades"))
async def cmd_grades(message: Message):
    # Получить оценки из БД
    # Сформировать таблицу
    # Отправить с inline кнопками

# /sync
@router.message(Command("sync"))
async def cmd_sync(message: Message):
    # Отправить Celery task sync_user_manual_task
    # Ответить "⏳ Синхронизация запущена..."
    # (Task отправит результат пользователю)
```

---

### **5️⃣ INLINE KEYBOARDS (Фаза 2.3)**

**Создать:**
- `bot/keyboards/main_menu.py` - главное меню
- `bot/keyboards/grades_menu.py` - таблица оценок с кнопками
- `bot/keyboards/settings_menu.py` - меню настроек
- `bot/keyboards/common.py` - общие кнопки (◀️ Назад, и т.д.)

**Структура:**

```python
# main_menu.py
def get_main_menu_keyboard():
    """Главное меню"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Оценки", callback_data="grades")],
        [InlineKeyboardButton(text="📈 Статистика", callback_data="stats")],
        [InlineKeyboardButton(text="👁 Режим ожидания", callback_data="watch")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings")],
        [InlineKeyboardButton(text="📥 Экспорт", callback_data="export")],
        [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="sync_btn")],
    ])

# grades_menu.py
def get_grades_keyboard(subjects: List[Subject]):
    """Кнопки для выбора предмета"""
    buttons = []
    for subject in subjects:
        buttons.append([
            InlineKeyboardButton(text=subject.name, callback_data=f"subject_{subject.id}")
        ])
    buttons.append([
        InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu"),
        InlineKeyboardButton(text="🔄 Обновить", callback_data="sync_grades"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
```

---

### **6️⃣ CALLBACK HANDLERS (Фаза 2.4)**

**Создать:**
- `bot/handlers/callback/main_menu.py`
- `bot/handlers/callback/grades.py`
- `bot/handlers/callback/settings.py`
- `bot/handlers/callback/common.py`

**Главное - EDIT MESSAGE вместо новых сообщений:**

```python
# common.py - обработка "Назад"
@router.callback_query(F.data == "main_menu")
async def callback_main_menu(query: CallbackQuery):
    message_text = get_main_menu_text()  # Получить текст главного меню
    keyboard = get_main_menu_keyboard()

    # EDIT вместо новой отправки!
    await query.message.edit_text(
        text=message_text,
        reply_markup=keyboard
    )

# grades.py - нажатие на предмет
@router.callback_query(F.data.startswith("subject_"))
async def callback_subject(query: CallbackQuery):
    subject_id = int(query.data.split("_")[1])
    grades_list = await get_grades(user_id, subject_id)

    text = format_subject_details(grades_list, subject_id)
    keyboard = get_subject_back_keyboard()

    await query.message.edit_text(text, reply_markup=keyboard)

# settings.py - включение уведомлений
@router.callback_query(F.data == "notifications_on")
async def callback_notifications_on(query: CallbackQuery):
    # Обновить в БД
    await enable_notifications(user_id)
    # Toast notification
    await query.answer("✅ Уведомления включены")
    # EDIT сообщение
    await show_notification_settings(query.message, user_id)
```

---

### **7️⃣ GRADES DISPLAY TABLE (Фаза 2.5)**

**Файл:**
- `bot/utils/formatters.py` - форматирование таблицы

**Форматирование таблицы:**

```python
def format_grades_table(grades_dict: Dict) -> str:
    """
    Формирует монотекстовую таблицу оценок

    grades_dict: {
        subject_id: {
            name: "Программирование",
            dates: [("30.09", 27919), ...],
            grades: [10, 9, None, ...],
            avg: 9.0
        }
    }
    """
    # Построение ASCII таблицы
    # Ограничение по ширине (86 символов - стандарт Telegram)
    # Обрезание длинных названий с "..."
    # Выравнивание по столбцам

    # Пример вывода:
    # ┌─────────────────────────────────────────────────────────────────────────────────┐
    # │ Предмет           │ 30.09 │ 10.10 │ 20.10 │ 30.10 │ Ср. │
    # ├─────────────────────────────────────────────────────────────────────────────────┤
    # │ Программирование  │  10   │   9   │   9   │  10   │ 9.5 │
    # │ Математика        │   5   │   4   │   5   │   -   │ 4.7 │
    # │ Физика ...        │   -   │   7   │   8   │   6   │ 7.0 │
    # └─────────────────────────────────────────────────────────────────────────────────┘

    return table_str
```

**Использование:**
- В /grades handler при отправке
- При обновлении (edit_message)
- Максимум 10 строк (если больше - показать меню выбора предмета)

---

### **8️⃣ NOTIFICATION SERVICE (Фаза 3.1-3.5)**

**Создать:**
- `bot/services/notification_service.py` - отправка уведомлений

**Функции:**

```python
class NotificationService:
    async def send_grade_notification(
        user_id: int,
        subject: Subject,
        grade_value: str,
        is_night: bool = False
    ):
        """Отправить уведомление о новой оценке"""
        # Проверить enabled в БД
        # Если ночь (22:00-08:00) и morning_notification_enabled:
        #   - Добавить в Redis notifications:night:{user_id}
        #   - Отправить Celery task с eta=morning_time
        # Иначе:
        #   - Отправить сразу через Bot API

    async def send_delayed_notification_batch(
        user_id: int,
        accumulated_grades: List[GradeNotification]
    ):
        """Отправить накопленные ночные уведомления одним сообщением"""
        # Получить из Redis notifications:night:{user_id}
        # Сформировать сообщение со списком
        # Отправить через Bot API
        # Очистить Redis ключ

    async def send_monthly_digest(
        user_id: int,
        report_data: dict
    ):
        """Отправить месячный дайджест"""
        # Генерация отчёта
        # Форматирование с таблицами и emoji
        # Отправка через Bot API с кнопками

    async def send_error_notification(
        user_id: int,
        error_message: str
    ):
        """Отправить уведомление об ошибке"""
        # "⚠️ Сервис временно недоступен..."
```

**Ночной режим:**
- Проверка текущего времени (22:00-08:00)
- Чтение настройки `morning_notification_enabled` из Users
- Чтение `morning_notification_time` (default: 08:00)
- Отправка задачи в Celery с `eta` = absolute datetime

---

### **9️⃣ WATCH MODE (Фаза 3.5)**

**Файлы:**
- `bot/handlers/callback/watch_mode.py` - callback для режима ожидания
- Доработка GradeSyncService - флаг `watch_mode_expires_at`

**Реализация:**

```python
# Включение режима ожидания
@router.callback_query(F.data == "watch_mode")
async def callback_watch_mode(query: CallbackQuery):
    # Установить в БД: watch_mode_expires_at = now() + 30 минут
    # Установить в Redis: watch_mode:{user_id} с TTL 30 мин
    # Ответ: "✅ Режим ожидания включён, осталось 30 мин"

    # Celery task sync_watch_mode_users_task будет проверять каждые 5 минут
    # и отправлять уведомления о новых оценках

# Выключение режима ожидания
@router.callback_query(F.data == "watch_mode_off")
async def callback_watch_mode_off(query: CallbackQuery):
    # Установить watch_mode_expires_at = NULL
    # Удалить из Redis
    # Ответ: "❌ Режим ожидания выключен"
```

**Scheduler task:**
```python
@periodic_task.on_schedule(run_every=crontab(minute=0))  # Каждый час
def cleanup_expired_watch_mode():
    """Удалить истекшие записи режима ожидания"""
    # DELETE FROM users WHERE watch_mode_expires_at < now()
```

---

### **🔟 EXPORT SERVICE (Фаза 4.1)**

**Создать:**
- `bot/services/export_service.py` - экспорт данных

**Функции:**

```python
class ExportService:
    async def export_to_excel(user_id: int) -> bytes:
        """Экспортировать в Excel"""
        # Получить все оценки пользователя
        # Создать Workbook с листами:
        #   - "Оценки" - таблица всех оценок
        #   - "Статистика" - средние баллы по предметам
        # Форматирование (цвета, границы, выравнивание)
        # Возврат бинарного файла

    async def export_to_pdf(user_id: int) -> bytes:
        """Экспортировать в PDF"""
        # Аналогично Excel
        # Использование reportlab или fpdf2
        # Добавление простых графиков

    async def export_compact_text(user_id: int) -> str:
        """Компактный текст для Telegram"""
        # Минималистичная таблица
        # Для копирования в мессенджер
```

**Интеграция:**
- Export button callback отправляет задачу в Celery
- После готовности файл отправляется пользователю

---

### **1️⃣1️⃣ STATISTICS SERVICE (Фаза 4.2)**

**Создать:**
- `bot/services/statistics_service.py` - вычисление статистики

**Функции:**

```python
class StatisticsService:
    async def get_average_grade(user_id: int) -> float:
        """Средний балл по всем предметам"""

    async def get_average_by_subject(user_id: int, subject_id: int) -> float:
        """Средний балл по конкретному предмету"""

    async def get_attendance_stats(user_id: int) -> dict:
        """Статистика посещаемости"""
        # Процент посещённых занятий
        # Количество пропусков (Н) и уважительных (Б, У)

    async def get_top_subjects(user_id: int, top_n: int = 3) -> List[Subject]:
        """Лучшие предметы по среднему баллу"""

    async def get_attention_subjects(user_id: int) -> List[Subject]:
        """Предметы, требующие внимания (низкий балл)"""

    async def get_grade_dynamics(user_id: int) -> dict:
        """Динамика оценок по неделям/месяцам"""
        # Возврат: {week/month: avg_grade}

    async def get_monthly_report(user_id: int, year: int, month: int) -> dict:
        """Полный месячный отчёт"""
        # Средний балл, динамика по неделям
        # Лучшие и худшие предметы
        # Статус и рекомендации
```

---

### **1️⃣2️⃣ LOCALIZATION (Фаза 4.4)**

**Структура:**
- `bot/locales/ru.json` - русский
- `bot/locales/en.json` - английский

**Использование fluent или gettext:**
- Ключи: `"hello"`, `"grades.empty"`, `"notification.new_grade"`, и т.д.
- Middleware для определения языка пользователя по `message.from_user.language_code`

**Пример:**
```json
{
  "hello": "👋 Привет!",
  "login_prompt": "📧 Введите edu email:",
  "grades_empty": "📊 У вас пока нет оценок",
  "notification.new_grade": "📝 Новая оценка!\n\n{subject}\nДата: {date}\nОценка: {grade}"
}
```

---

### **1️⃣3️⃣ MIDDLEWARE & FILTERS (Фаза 5.1)**

**Rate Limiting:**
```python
class RateLimitMiddleware:
    async def __call__(self, handler, event, data):
        user_id = event.from_user.id
        # Получить count из Redis key "ratelimit:{user_id}"
        # Если count > 30 (за минуту):
        #   - Отправить ошибку
        # Иначе:
        #   - Incrementить counter
        #   - Вызвать handler
        #   - Установить TTL = 60 сек
```

**Auth Filter:**
```python
class AuthenticatedFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        user = await get_user(message.from_user.id)
        return user and user.is_authenticated
```

---

### **1️⃣4️⃣ PROMETHEUS METRICS (Фаза 5.2)**

**Использование celery-prometheus-exporter:**
```bash
pip install celery-prometheus-exporter
```

**В docker-compose.yml добавить:**
```yaml
prometheus:
  image: prom/prometheus
  ports:
    - "9090:9090"
  volumes:
    - ./configs/prometheus.yml:/etc/prometheus/prometheus.yml

celery-exporter:
  image: zerok/celery-prometheus-exporter
  ports:
    - "8888:8888"
  environment:
    - CELERY_BROKER_URL=redis://redis:6379/1
    - CELERY_RESULT_BACKEND=redis://redis:6379/2
```

**Custom metrics для бота:**
```python
from prometheus_client import Counter, Histogram, Gauge

# Счётчики
bot_commands = Counter(
    'bot_commands_total',
    'Total bot commands',
    ['command']
)

sync_tasks = Counter(
    'sync_tasks_total',
    'Total sync tasks',
    ['type', 'status']  # type: manual/auto/watch, status: success/error
)

# Гистограммы
sync_duration = Histogram(
    'sync_duration_seconds',
    'Sync task duration',
    buckets=[1, 5, 10, 30, 60, 300]
)

# Gauge
active_users = Gauge(
    'active_users',
    'Active users in watch mode'
)
```

---

### **1️⃣5️⃣ TESTING (Фаза 7.1-7.4)**

**Структура тестов:**
```
tests/
  ├── unit/
  │   ├── test_auth_service.py
  │   ├── test_journal_parser.py
  │   ├── test_grade_sync.py
  │   └── test_statistics.py
  ├── integration/
  │   ├── test_login_flow.py
  │   ├── test_sync_flow.py
  │   └── test_notifications.py
  └── conftest.py (fixtures)
```

---

### **Docker:**
1. ✅ Использовать multi-stage builds для production
2. ✅ Все env переменные должны быть в .env.example
3. ✅ Использовать Docker Compose для локальной разработки
4. ✅ Healthchecks для критичных сервисов
6. ✅ Использовать .dockerignore для исключения ненужных файлов

---

## 📝 Правила разработки

### **Код:**
1. ✅ Black для форматирования (line-length: 100)
2. ✅ Ruff для линтинга
3. ✅ Type hints везде (Pydantic models, async functions)
4. ✅ Docstrings для всех functions (Google style)
5. ✅ Логирование через `loguru` или встроенный logging
6. ✅ Обработка ошибок с custom exceptions

### **Git:**
1. ✅ Commits по функциям, не по строкам кода
2. ✅ Commit message: `[module] Description` (e.g., `[celery] Add sync_user_task`)
3. ✅ PR для каждой фазы разработки
4. ✅ Pre-commit hooks для форматирования

### **Тестирование:**
1. ✅ Минимум 80% code coverage для critical modules
2. ✅ Все unit tests должны проходить перед merge
3. ✅ Integration tests для ключевых flows

---

## 🚀 Рекомендуемый порядок разработки

```
Неделя 1:
  ✓ Фаза 1 (Celery, AuthService, FSM)
  ✓ PR #1: celery-setup
  ✓ PR #2: auth-service
  ✓ PR #3: fsm-login

Неделя 2:
  ✓ Фаза 2 (Handlers, Keyboards, Callbacks)
  ✓ PR #4: main-handlers
  ✓ PR #5: inline-keyboards
  ✓ PR #6: callback-handlers

Неделя 3:
  ✓ Фаза 3 (Notifications, Watch Mode)
  ✓ PR #7: notification-service
  ✓ PR #8: watch-mode

Неделя 4:
  ✓ Фаза 4 (Export, Statistics, Localization)
  ✓ PR #9: export-service
  ✓ PR #10: statistics-service
  ✓ PR #11: localization

Неделя 5:
  ✓ Фаза 5 (Rate Limiting, Prometheus, Sentry)
  ✓ PR #12: monitoring

Неделя 6:
  ✓ Фаза 6 (Admin, Grafana)
  ✓ PR #13: admin-panel

Неделя 7-8:
  ✓ Фаза 7 (Тестирование, оптимизация)
  ✓ PR #14: tests
```

---

## ✅ Чек-лист перед Production

- [ ] Все тесты проходят (>80% coverage)
- [ ] Celery workers запускаются без ошибок
- [ ] Flower доступен на localhost:5555
- [ ] Prometheus собирает метрики
- [ ] Бот отвечает на /start < 100ms
- [ ] Синхронизация работает (manual + auto + watch_mode)
- [ ] Уведомления отправляются (immediate + delayed + grouped)
- [ ] Режим ожидания включается/выключается
- [ ] Экспорт работает (Excel, PDF)
- [ ] Настройки сохраняются
- [ ] Logout очищает данные
- [ ] Rate limiting работает
- [ ] Sentry ловит ошибки
- [ ] Docker Compose поднимается `docker-compose up -d`
- [ ] Все env переменные в .env.example
- [ ] README обновлен (инструкции по запуску)

---

**Документ подготовлен:** 13.12.2025
**Версия плана:** 1.0
**Статус:** Готов к разработке

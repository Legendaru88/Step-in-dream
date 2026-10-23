# Шаг к мечте: частный комплект с туннелем, 23.10.2026

Распакуйте ZIP полностью. На Windows запустите Docker Desktop и дождитесь готовности.
Откройте папку **step-to-dream**, в которой лежит **docker-compose.yml**.
Перед запуском откройте `.env` в текстовом редакторе и замените только значение `BOT_TOKEN`
новым токеном BotFather. В архиве оставлен старый отозванный токен: владелец подтвердил
перевыпуск, получатель заменяет его у себя. Если новый токен уже внесён, сохраните его.
Передавать новый токен нам, в чат или отчёт не требуется.
OpenRouter и SSH-туннель уже настроены, их ключи менять не нужно.
В адресной строке Проводника напишите **cmd** и нажмите Enter. После замены токена выполните одну команду:

```sh
docker compose --profile telegram up --build -d
```

Оригинальный серверный бот владельца остановлен по результатам предыдущей проверки.
Запускайте только одну копию с новым токеном. Если уже
запустили старый комплект, сначала остановите его: `docker compose --profile telegram down`
**без -v**, затем обновляйте файлы по инструкции ниже. Не запускайте второй poller.

В архиве уже есть `.env` с выделенным OpenRouter API key и старым отозванным BOT_TOKEN и отдельный
SSH-ключ в `secrets/`. Не заменяйте .env пустым шаблоном. Архив частный: не публикуйте его,
.env и secrets, не отправляйте их в чат или Git. Запросы расходуют баланс выделенного ключа.

Команда собирает приложения и SSH sidecar, применяет миграции и запускает бота и API.
Первый build скачивает базовые образы и зависимости; нужен доступ к Docker registry и PyPI/Alpine.
Дождитесь готовности tunnel; откройте Telegram-бота и отправьте /start.
Проверка: `docker compose --profile telegram ps -a` (init: Exited 0, tunnel: healthy).
HTTP API: http://localhost:8000/docs (только localhost, полноценной авторизации нет).

Оба сервиса используют SOCKS внутри Docker: OpenRouter и Telegram API, включая фотографии.
Порт SOCKS на компьютер/интернет не опубликован. Отдельная настройка SSH на Windows не нужна:
ключ монтируется только в tunnel read-only и копируется в tmpfs с mode 600. Host key Koara
закреплён в tunnel/known_hosts; TLS проверяется. Перезапуск SSH после разрыва автоматический.
Для доступа разрешены только openrouter.ai:443 и api.telegram.org:443; DNS выполняется удалённо.

Для проверки без получения сообщений и без polling:

```sh
docker compose up --build -d
docker compose exec api python -m scripts.check_setup --network
```

getMe не читает updates; проверка модели делает один короткий платный запрос.
Если bot уже работает и нужен API-only, сначала `docker compose --profile telegram stop bot`.
Gordon и отдельный запуск Dockerfile для этого комплекта не нужны: запускать нужно Compose.

## Обновление старого комплекта и данные

Новый архив добавляет готовый отдельный SSH-доступ, sidecar, оба прокси и исправленные инструкции.
Фотоотчёты и цели сохранены в исходниках; данные владельца в ZIP не входят.
Перед обновлением работающего старого комплекта сделайте `docker compose exec api python -m scripts.backup`
(если работает только бот, замените api на bot). Скопируйте backups в безопасное место.
Остановите старый комплект: `docker compose --profile telegram down` без -v.
Распакуйте новый архив во временную папку, затем перенесите новые исходники, docs, scripts,
tunnel, secrets, docker-compose.yml и файлы исключений в прежнюю папку проекта.
Не удаляйте backups, существующий .env и volume. Не копируйте архивный .env поверх своего:
он затрёт уже внесённый новый BOT_TOKEN старым отозванным. Сохраните новый BOT_TOKEN,
API_PORT и другие персональные настройки. Если токен ещё старый, замените только BOT_TOKEN
новым из BotFather. При необходимости перенесите выделенный OPENROUTER_API_KEY из архивного
.env отдельно; proxy URL Compose задаёт автоматически. Используйте отдельный SSH-ключ из secrets/.

**Имя папки/Compose project сохраняйте прежним**: volume называется `<project>_goals-data`.
Для старой папки с другим именем задайте прежний project явно: `docker compose -p ПРЕЖНЕЕ_ИМЯ --profile telegram up --build -d`.
Не выбирайте volume серверного проекта tggoals-data: это другой комплект/база.
Если меняете project или машину, сделайте backup и восстановите его по docs/OPERATIONS.md.
Не используйте `down -v`: это удалит цели. Свежая распаковка с новым project создаёт пустую базу.

## Управление

```sh
docker compose --profile telegram ps -a
docker compose logs --tail=100 tunnel bot api
docker compose exec api python -m scripts.check_setup --network
docker compose restart tunnel
docker compose --profile telegram down
```

Не публикуйте полные логи или результат `docker compose config`: там может оказаться .env.
Детали: [START](docs/START.md), [OPERATIONS](docs/OPERATIONS.md),
[возможности](docs/FEATURES.md), [API](docs/API.md), [разработка](docs/DEVELOPMENT.md).

Исходники можно публиковать только без .env, secrets, backups, баз и частного ZIP.
В исходном Git handoff/ содержит шаблоны частного комплекта; серверный docker-compose.yml отдельный.

# cveta2 doctor

Проверяет конфигурацию, ключи S3, подключение ClearML и права на каталоги кэша. Запустите её после [`cveta2 setup`](setup.md) или когда другие команды падают с ошибками конфигурации.

## Примеры

Проверить настройки:

```bash
cveta2 doctor
```

Проверить и выдать группе права на свои файлы в кэше:

```bash
cveta2 doctor --cache
```

Проверить другой личный файл:

```bash
CVETA2_CONFIG=~/alt/config.yaml cveta2 doctor
```

## Синтаксис и аргументы

```text
cveta2 doctor [-h] [--cache]
```

| Аргумент | По умолчанию | Описание |
|---|---|---|
| `--cache` | выкл. | Исправить права в кэше: добавить группе права на чтение и запись (для каталогов ещё и на вход) на всё, чем владеете вы, и назвать владельцев остальных путей. Проверка кэша выполняется даже при `CVETA2_DISABLE_CACHE=true`. |
| `-h`, `--help` | | Показать справку. |

Флага для пути к личному файлу у команды нет. Она читает файл из `CVETA2_CONFIG` или `~/.config/cveta2/config.yaml` и общий файл, выбранный как обычно (см. [Конфигурация](../configuration.md)).

## Как это работает

Команда выполняет четыре проверки по порядку. Обязательна только первая.

1. **Конфигурация (обязательная).**
   - Если личного файла нет, пишет предупреждение `Config file not found: <путь>. Run 'cveta2 setup' or set env variables.` и продолжает с переменными окружения.
   - Читает настройки CVAT так же, как другие команды: значения по умолчанию, личный файл, общий файл, окружение.
   - Проверяет, что задан адрес CVAT и есть и логин, и пароль.
   - Для каждого проекта из `image_cache` сообщает, есть ли каталог. Отсутствие каталога — только предупреждение.
   - К CVAT команда не подключается. Неверный пароль или недоступный сервер она не обнаружит.
2. **Ключи AWS (необязательная).** Просит boto3 найти ключи доступа обычным способом и выводит профиль, регион и первые и последние 4 символа ключа. Сам S3 не запрашивает.
3. **Подключение ClearML (необязательная).** Оно нужно для `verify --bundle`, `upload-dataset` и команд `cveta2 dataset`, которые читают или публикуют версии в ClearML. Проверка читает настройки так же, как ClearML SDK: файл `~/clearml.conf` (если задан `CLEARML_CONFIG_FILE` — только файл из этой переменной) и переменные `CLEARML_API_HOST`, `CLEARML_API_ACCESS_KEY`, `CLEARML_API_SECRET_KEY`, которые важнее файла.
   - Подключение настроено, если есть ключ доступа и секретный ключ (или `CLEARML_AUTH_TOKEN`) и SDK может определить адреса веб-приложения и сервера файлов. Иначе — `не настроен`, и к серверу команда не обращается.
   - Адреса веб-приложения и сервера файлов SDK выводит сам, только если адрес сервера API имеет вид `api.<домен>` или порт 8008. Для другого адреса задайте их явно: `CLEARML_WEB_HOST` и `CLEARML_FILES_HOST` или `api.web_server` и `api.files_server` в файле. Без адреса сервера файлов загрузка в ClearML не работает.
   - Если адрес сервера не задан, SDK использует свой адрес по умолчанию `https://api.clear.ml`; команда помечает его `(адрес SDK по умолчанию)`.
   - Затем команда один раз входит на сервер API ClearML (`<адрес>/auth.login`, как это делает SDK) и ждёт ответа не больше 10 секунд, без повторов. Ключи передаются так же, как в SDK: ключ доступа и секретный ключ — как HTTP Basic, `CLEARML_AUTH_TOKEN` — как Bearer; `~/.netrc` их не заменяет. Проверка сертификата TLS следует настройке SDK: `CLEARML_API_HOST_VERIFY_CERT` или `api.verify_certificate` (`false` отключает проверку, путь к файлу задаёт свои корневые сертификаты). Запрос идёт через библиотеку requests, как у SDK, поэтому без этой настройки сертификаты, прокси и переменные `REQUESTS_CA_BUNDLE` и `CURL_CA_BUNDLE` работают так же, как при загрузке: по умолчанию корневые сертификаты берутся из пакета certifi. Перенаправление на другой адрес не выполняется. Результат — одна строка:
     - `проверено` — сервер принял ключи. Строка называет адреса сервера API и сервера файлов и откуда взяты настройки: путь к файлу или переменные окружения.
     - `ключи отклонены` — сервер ответил HTTP 401 или 403: ключ доступа, секретный ключ или токен неверны или отозваны.
     - `сервер недоступен` — нет соединения, нет ответа за 10 секунд, ошибка TLS, перенаправление, другой код HTTP или ответ не от сервера API ClearML. Причина называется только классом ошибки, например `ConnectionRefusedError` или `SSLCertVerificationError`, без текста ошибки: он может содержать заголовки запроса.
   - Если ключ доступа, секретный ключ или `CLEARML_AUTH_TOKEN` содержит пробелы, переводы строк или символы не из ASCII, команда пишет `ключи некорректны`, называет такое значение (но не выводит его) и к серверу не обращается.
   - Ключи и токены команда не выводит ни в одном из случаев.
4. **Права кэша (необязательная).** Пропускается при `CVETA2_DISABLE_CACHE=true` без `--cache`. Проверяет существующие каталоги: `image_cache.<проект>`, `cache.images_root`, `cache.tasks_root`, корни из `cache.projects` и собственный кэш cveta2 (`$XDG_CACHE_HOME/cveta2` или `~/.cache/cveta2`). Вложенный каталог отдельно не проверяется. Каталог истории ввода `prompt_history` пропускается. Файлам нужны права группы `rw`, каталогам — `rwx`.
   - Без `--cache` только сообщает о нарушениях и их владельцах.
   - С `--cache` добавляет недостающие права группы на пути, владелец которых вы. Пути других пользователей не трогает и называет их владельцев: им нужно запустить `cveta2 doctor --cache` самим.

Каталоги кэша описаны на странице [Изображения и кэши](../images-and-cache.md).

## Результат

Команда ничего не пишет на диск, кроме исправления прав с `--cache`. Итог выводится последней строкой:

```text
doctor: обязательные проверки пройдены
```

или

```text
doctor: обязательные проверки не пройдены
```

Пример вывода для рабочей конфигурации, где у каталога кэша нет прав группы:

```text
doctor: checking configuration …
Config file: /home/alice/.config/cveta2/config.yaml
image_cache: no projects configured (optional)
Config: OK
doctor: AWS — необязательная проверка
doctor: checking AWS credentials …
AWS: credentials OK — profile=default, region=us-east-1, access_key=AKIA…MPLE
doctor: ClearML — необязательная проверка
doctor: checking ClearML configuration …
ClearML: проверено — вход на сервер API https://api.clearml.example.com выполнен; сервер файлов https://files.clearml.example.com, источник: файл /home/alice/clearml.conf
doctor: checking cache group permissions in 1 location(s) …
cache.images_root (/home/alice/data/images): 1 dir(s) and 0 file(s) not group-accessible. Owners: alice (1 items)
  drwxr-xr-x  alice  /home/alice/data/images
1 path(s) you own can be repaired here: run 'cveta2 doctor --cache'
doctor: необязательная проверка кэша не пройдена
doctor: обязательные проверки пройдены
```

С `--cache` для того же каталога (показаны только строки проверки кэша и итог):

```text
doctor: fixing cache group permissions in 1 location(s) …
cache.images_root (/home/alice/data/images): granted group access to 1 path(s)
doctor: обязательные проверки пройдены
```

### Коды завершения

| Код | Когда |
|---|---|
| `0` | Обязательная проверка конфигурации пройдена. Необязательные проверки AWS, ClearML и кэша на код не влияют. |
| `1` | Проверка конфигурации не пройдена: нет логина или пароля, ошибка в личном или общем файле, конфликт переменных окружения с общим файлом. |

## Интерактивный и неинтерактивный режим

Команда ничего не спрашивает и одинаково работает с `CVETA2_NO_INTERACTIVE=true` и без него.

## Частые ошибки

| Сообщение | Причина | Что сделать |
|---|---|---|
| `config: No credentials: provide CVAT_USERNAME + CVAT_PASSWORD` | Нет логина или пароля ни в личном файле, ни в окружении. | Запустите [`cveta2 setup`](setup.md) или задайте `CVAT_USERNAME` и `CVAT_PASSWORD`. |
| `doctor: обязательная проверка конфигурации недоступна: Cannot read configuration <путь>: FileNotFoundError` | Общий файл, на который указывает `CVETA2_PROJECT_CONFIG` или `project_config`, не найден. Проверка кэша в этом случае тоже не выполняется: `doctor: необязательная проверка кэша недоступна: ...`. Код завершения `1`. | Проверьте путь или подключите файл заново: `cveta2 setup --project-config PATH`. |
| `doctor: обязательная проверка конфигурации недоступна: CVAT identity environment overrides conflict with shared project configuration` | `CVAT_HOST` или `CVAT_ORGANIZATION` не совпадают с общим файлом. | Уберите эти переменные. |
| `doctor: обязательная проверка конфигурации недоступна: Shared project policy/identity cannot be stored in personal configuration` | В личном файле с `schema_version: 1` есть `cvat.host`, `cvat.organization` или ключи общего файла. | Удалите эти ключи из личного файла. |
| `doctor: обязательная проверка конфигурации недоступна: Versioned personal configuration requires a shared project_config reference` | В личном файле `schema_version: 1`, но общий файл не выбран. | Подключите общий файл: `cveta2 setup --project-config PATH`. |
| `doctor: обязательная проверка конфигурации недоступна: Ошибка чтения YAML-конфигурации <путь>: ParserError, строка 4, столбец 2.` | Синтаксическая ошибка YAML в личном файле. | Исправьте файл в указанном месте. |
| `doctor: обязательная проверка конфигурации недоступна: Legacy mixed configuration requires verification: cveta2 setup --migrate-config` | Старый формат с ключами общего файла. | Запустите `cveta2 setup --migrate-config`. |
| `AWS: no credentials found. Configure via AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY env vars, ~/.aws/credentials, or an IAM role.` | boto3 не нашёл ключи S3. Код завершения не меняется. | Задайте ключи одним из названных способов. |
| `ClearML: не настроен — не найдены: ключ доступа (CLEARML_API_ACCESS_KEY или api.credentials.access_key), секретный ключ (CLEARML_API_SECRET_KEY или api.credentials.secret_key). ...` | ClearML SDK не нашёл ключи ни в файле настроек, ни в переменных окружения. Если не хватает одного ключа, назван только он. Код завершения не меняется. | Создайте `~/clearml.conf` (например, командой `clearml-init`, она ставится вместе с SDK) или задайте `CLEARML_API_HOST`, `CLEARML_API_ACCESS_KEY` и `CLEARML_API_SECRET_KEY`. |
| `ClearML: не настроен — не найдены: адрес веб-приложения (CLEARML_WEB_HOST или api.web_server), адрес сервера файлов (CLEARML_FILES_HOST или api.files_server). ...` | Адрес сервера API не вида `api.<домен>` и без порта 8008, поэтому SDK не может вывести из него другие адреса. Код завершения не меняется. | Задайте `CLEARML_WEB_HOST` и `CLEARML_FILES_HOST` или `api.web_server` и `api.files_server` в `~/clearml.conf`. |
| `ClearML: ключи отклонены — сервер API <адрес> ответил HTTP 401. Проверьте ключ доступа и секретный ключ (источник: <источник>).` | Сервер API ClearML не принял ключи. Код завершения не меняется. | Создайте новые ключи в веб-приложении ClearML и запишите их в `~/clearml.conf` или в `CLEARML_API_ACCESS_KEY` и `CLEARML_API_SECRET_KEY`. |
| `ClearML: ключи некорректны — <ключ>: есть пробелы, переводы строк или символы не из ASCII. Задайте значение заново (источник: <источник>).` | Значение нельзя отправить в заголовке HTTP, например токен скопирован вместе с переводом строки. Код завершения не меняется. | Задайте значение заново без пробелов и переводов строк. |
| `ClearML: сервер недоступен — <адрес>: <причина>.` | Сервер API не ответил за 10 секунд, соединение не установлено (например, `ConnectionRefusedError`), ошибка TLS, или по адресу отвечает не сервер API ClearML. Код завершения не меняется. | Проверьте адрес сервера API, сеть и VPN. Для сервера с самоподписанным сертификатом задайте `api.verify_certificate` или `CLEARML_API_HOST_VERIFY_CERT`. |
| `doctor: необязательная проверка ClearML недоступна: ClearML: файл конфигурации не читается (<путь>): <класс ошибки>` | ClearML SDK не смог прочитать файл настроек: например, синтаксическая ошибка (`ConfigurationError`) или файл не в UTF-8 (`UnicodeDecodeError`). Текст ошибки не выводится: в файле лежит секретный ключ. Код завершения не меняется. | Исправьте файл или создайте его заново командой `clearml-init`. |
| `These users own the remaining paths and must run 'cveta2 doctor --cache' themselves: <пользователи>` | В кэше есть пути других пользователей без прав группы. | Попросите названных пользователей запустить `cveta2 doctor --cache`. |

Если адрес CVAT не задан нигде, проверка его не отвергает: подставляется адрес по умолчанию из пакета `http://localhost:8080` (см. [Конфигурация](../configuration.md#значения-по-умолчанию-из-пакета)).

## Из Python

Отдельной функции для `doctor` нет. Проверить логин и пароль можно так:

```python
import cveta2

try:
    cveta2.CvatConfig.load().require_credentials()
except cveta2.MissingCredentialsError as error:
    print(error)
```

`MissingCredentialsError` — подкласс `cveta2.Cveta2Error`. Подробнее — на странице [Python API](../python-api.md).

## См. также

- [Конфигурация](../configuration.md)
- [`cveta2 setup`](setup.md)
- [Изображения и кэши](../images-and-cache.md)
- [Глоссарий](../../GLOSSARY.md)

# Правила работы: EUR Rev 1 + русификатор ZELDA64RUS

Документ обязателен для исполнения всеми участниками работ по плану
`EUR Rev 1 + русификатор` (ветка `eur-rus-support`). Формулировки ниже —
проверенные факты и принятые решения; отклонение возможно только с явного
согласия заказчика.

## 1. Процесс

1. Все изменения — только в ветке `eur-rus-support`; в неё же коммичить.
   В `android`/`main` не коммитить без явного запроса.
2. Строго один субагент за раз (последовательно, без fan-out). После
   каждого воркера — верификация оркестратором (детерминированные
   проверки, см. §5); «done» воркера доказательством не является.
3. Каждый завершённый и проверенный этап — отдельный осмысленный коммит.
4. Рабочее состояние orchestration-веджера — в `.omp/gvs5h/eur-rus-support/`
   (не коммитится); общие факты и решения — в этом документе.
5. Файлы `resources/mm3d/project-restoration/**` не редактировать
   (вендорный content-addressed манифест).

## 2. Проверенные факты (перепроверены 2026-11-07 на реальных файлах)

1. USA Rev1: program_id `0004000000125500`, 654643200 B,
   sha256 `9c756279…323da`. EUR Rev1: program_id `0004000000125600`,
   668647424 B, sha256 `a26108ef…a722`. `probe_rom.py` печатает оба.
2. `exefs/code.bin` (LZSS) в USA и EUR **побайтово идентичен**
   (decompressed 5 967 872 B, CRC32 `ffdf1ee8` = source-CRC запиненного
   `code.bps`). Следствие: **адресные таблицы runtime-модулей общие для
   регионов, отдельный EUR-набор не нужен; единственный `code.bps`
   покрывает обе базы** (фаза D сводится к снятию TID-гейтов).
3. Все «original»-входы fingerprint-манифеста (base-layout gar'ы
   `Joker.Main*`, `Joker.gar`, `message/ltn16.gzf`) идентичны в обоих
   регионах → layout-операции рецептов применяются к EUR без изменений.
4. Вендорный `project-restoration/exheader.bin` — это EUR-exheader
   (pid `0004000000125600`) + 34 байта Modification Region; те же 34
   байта — дельта USA. Отдельные EUR-файлы Restoration **не нужны**.
5. RU-патч v1.1 меняет И romfs, И exefs: `romfs.bpm` — 108 файлов
   (`message/eu/eue.gmsg`, `message/ltn16.gzf` (кириллица),
   10×`layout/EU_English/Joker.Main*.gar`, 85×`layout/map/genbamap/
   EU_English/*.ctxb`, 7×`menu/daytelop/eu-en/*.ctxb`,
   `menu/savedata_maintainer/eu/english/guideline_parts00.ctxb`,
   `os/patch/version.ctxb`, `actors/zelda2_boss01.gar.lzs`,
   `actors/zelda2_boss07.gar.lzs`); `exefs.bpm` — `code.bin` (BPS-дельта
   фиксов перевода), `icon.icn`, `banner.bnr`. Ранний факт «RU-патч не
   меняет код» ошибочен. Патч перезаписывает EUR-English слоты русским;
   нового языкового слота не добавляет.
6. Dek-моды никогда не трогают локализованные копии `layout/*_English/*`
   — только base-файлы и `message/*`; RU-файлы с ними не конфликтуют.
7. Проверенная RU-колода (2026-11-08): голый расшифрованный CXI
   (NCCH-контейнер, без NCSD) из патча v1.1 — program_id
   `0004000000125600`, main partition 668 921 856 B, sha256
   `4cb0d107…4c9d`, Game Sequence Info region-byte `0x82` = `'E'`.
   Текст в ней уже русский. Все читатели контейнера (probe_rom,
   setup_game_folder, `game_folder.h`, DekuiGameSetup) принимают голый
   NCCH: его заголовок лежит на том же смещении `0x100`, что и первый
   NCSD-раздел.

## 3. Технические правила (архитектура)

1. `supported-rom.json` v2: `{"schema":2,"roms":[{title_id,region,
   remaster_version,main_partition_bytes,main_partition_sha256,
   description, text_language?}…]}`; читатели выбирают запись по probe
   (program_id → fallback bytes+sha), иначе прежняя ошибка unsupported.
   `text_language` задаёт колода (не пользователь): запись RU-колоды =
   `"rus"`, переключать её нельзя (иначе кириллица встанет в латинский
   шрифт).
2. Единый C++-хелпер `src/mm3d/title_ids.h` (`IsMajoraMask3DTitle`) и
   Kotlin-объект `TitleIds`; литералы title id в коде запрещены (кроме
   определений констант). Пути `mods/<title_id>` строятся из runtime
   program id, не хардкодом.
3. `setup-fingerprints.json` v2: общие поля остаются как есть
   (регион-общие, доказано), добавляется `titles.<tid>.{region,messages}`;
   список извлекаемых message-архивов и константы генераторов берутся из
   профиля (`us/{use,usf,uss}`; `eu/eue`). rus-секция профиля добавляется
   оркестратором после вендоринга RU.
4. `src/mm3d/game_folder.h`: валидация по списку {size,sha} обеих баз;
   тексты — «USA or Europe Rev 1».
5. RU-оверлей: вендоринг в `resources/mm3d/rus/**` **по точным
   регистро-путям ROM** (bpm/Bonus используют lower-case; beat сопоставляет
   без учёта регистра, 3DS FS и Citra LayeredFS — с учётом).
   `rus/manifest.json` schema 1: источник (LoZMM3D PAL rev1 RUS v1.1,
   CRC32 943ED937/3A87ABAC), для каждого файла путь/размер/sha256 RU и
   стокового EUR; `code.bin`, `icon.icn`, `banner.bnr` — только метаданные.
6. Для EUR язык текста выбирается при установке: desktop
   `setup_game_folder.py --text-language rus|stock` (без флага — из
   профиля/записи дек: `rus` для стоковой EUR, язык уже-RU колоды),
   Android Setup показывает диалог «Русский / English» только для
   верифицированных EUR-колод с паком `rus` и ещё не русским текстом
   (`DekuiGameSetup.supportsRussian`, `prepare(..., russian)`). Запись
   выбора — `user/setup/ready.json:text_language`. Игровая настройка
   языка не меняется: слот «English» = выбранный текст.
7. Дельта RU `code.bin` в дек не компонуется (дек-`code.bps` остаётся на
   стоковой EUR-код); в `rus/manifest.json` — запись-unknown про возможный
   будущий compose. Акторные `.lzs` вендорятся как romfs-файлы оверлея.
8. Текстовые данные форка для EUR/RUS генерируются существующими
   скриптами фазы C3 из `message/eu/eue.gmsg` (стокового / RU-пропатченного);
   новый формат таблиц не вводится. Если RU-токены недоступны генераторам —
   EN-подсказки остаются, фиксируется в KNOWN_ISSUES.
9. Исправления плана: D2 не выполняется (см. §2.2); C2 не выполняется
   (см. §2.4); C4/E2-«per-профиль recipes» = profile-plumbing без новых
   ops (см. §2.3). Приоритет у фактов этого документа, не у текста плана.

## 4. Контракт кода

- Python-инструменты: только stdlib; ошибки — `ValueError` в существующем
  terse-стиле; unsupported input → сразу raise, без «может продолжим».
- Тесты: pytest в `tools/mm3d/test_*.py`; реальные ROM'ы в юнит-тестах не
  требуются (фикстуры), интеграционные проверки — skipif без артефактов.
- C++/Kotlin: правки гейтов без изменения адресных констант; новые тесты
  по образцу существующих (`dekui_import_tests.cpp`).
- Gradle/CMake-сборки в процессе не гонять; финальная проверка — этап
  Verification (см. план).

## 5. Верификация после каждого этапа (обязательна оркестратору)

1. `python -m pytest tools/mm3d -q` — весь набор зелёный.
2. Прогон изменённых check-тулов/скриптов по их штатной команде.
3. `tools/mm3d/windows/smoke_setup.py` stage-режим: EUR .cci → успех и
   `stage/mods/0004000000125600/**`; USA .cci — идентичный выход
   (regression).
4. E2E на реальных файлах: RU CXI пользователя → дефолтный setup даёт
   `text_language:"rus"` и RU-файлы оверлея по манифесту; EUR .cci с
   `--text-language stock` → eue.gmsg совпадает с EUR-English pin
   профиля, RU-файлов в деке ноль.
5. Грep-инварианты: отсутствие литералов title id вне разрешённых мест
   (`grep -rn 125500 src` и эквивалент для `125600` вне JSON).

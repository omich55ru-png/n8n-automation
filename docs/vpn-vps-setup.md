# VPN-прокси на VPS для n8n → OpenRouter

Секреты (UUID, ключи, ссылка подписки) в репозиторий не кладём: только плейсхолдеры.

## Архитектура
n8n (Docker) → http://172.19.0.1:1081 (sing-box) → VLESS/Reality → нода провайдера (NL).
Выборочная маршрутизация (split routing): через прокси идут только домены из route.rules.

## Правила маршрутизации (route.rules)
| Домены | Outbound | Зачем |
|---|---|---|
| openrouter.ai, claude.ai, anthropic.com | proxy | LLM API (напрямую 403) |
| telegram.org, t.me, telesco.pe | proxy | Telegram |
| ithyper.ru | proxy | Скачивание подписки: панель периодически не отвечает прямому трафику с VPS |
| openai.com, chatgpt.com, oaistatic.com, oaiusercontent.com, oaistatsig.com | proxy | ChatGPT и OpenAI API (добавлено 04.11.2026) |

Правило ithyper.ru добавлено 02.11.2026, правило OpenAI/ChatGPT добавлено 04.11.2026. Остальное идёт напрямую (final: direct).
Правила действуют для трафика, который приходит на прокси 172.19.0.1:1081 (n8n и другие контейнеры). Браузер и телефон используют Happ, а не этот прокси.
Шаблон конфига: sing-box/config.template.json.

## Автообновление ноды (/opt/vless-updater)
1. health: GET openrouter.ai через прокси; 200 → выход (при переходе fail→ok шлёт ✅ восстановления).
2. Подписка: через прокси, при сбое — напрямую (иначе порочный круг: при мёртвом туннеле ключи не скачать). Успех → nodes_cache.txt; сбой → кэш; нет кэша → ⚠️.
3. Перебор нод с проверкой auth (АВТОВЫБОР первым): применить → restart sing-box → health; 000 → следующая. TCP жив ≠ Reality валиден (инцидент 07.11).
4. Все ноды мертвы → ❌ (один раз, пока состояние fail).

Уведомления: ❌/✅ — всегда (по смене состояния, файл .state); троттлится только ⚠️ (не чаще 1 в 4 часа, .alert_ts).
TimeoutStartSec=600 (override /etc/systemd/system/vless-updater.service.d/timeout.conf): перебор нод может занимать минуты.
Секреты (TG_TOKEN, SUB_URL, PROXY) — в /opt/vless-updater/env, в git не попадают.

## Инциденты
| Дата | Что случилось | Причина | Решение |
|---|---|---|---|
| 22.09 | reality verification failed на всех нодах | Провайдер сменил UUID | Обновить uuid из подписки |
| 29.09 | Пропало telegram-правило | Конфиг пересоздан setup-скриптом | Правила хранятся в шаблоне sing-box/ |
| 02.11 | Апдейтер получал 000 от панели | Подписка качалась напрямую, панель вешает ответ | Правило ithyper.ru + curl -x + кэш нод |
| 07.11 | reality verification failed, openrouter/telegram 000 | node3 мертва на стороне провайдера: TCP жив, Reality нет; АВТОВЫБОР указывал на неё. Плюс: подписка качалась только через мёртвый прокси, ❌-алерт съеден антиспамом | Переход на node2 вручную; update.sh v2: перебор нод с auth-check, фолбэк скачивания напрямую, алерты по смене состояния |

## Чек-лист после переустановки
1. Взять sing-box/config.template.json, подставить NODE_HOST, YOUR_UUID, NODE_PUBLIC_KEY, NODE_SHORT_ID.
2. Убедиться, что в route.rules все четыре группы доменов: jq '.route.rules' /etc/sing-box/config.json
3. sing-box check -c /etc/sing-box/config.json && systemctl restart sing-box
4. Прокси: curl -x http://172.19.0.1:1081 https://openrouter.ai/api/v1/models → 200.
5. OpenAI: curl -x http://172.19.0.1:1081 https://api.openai.com/v1/models → 401 (запрос без ключа; 401 значит, что до OpenAI дошли). После рестарта подождать 3 секунды, иначе curl вернёт 000.
6. Подписка через туннель: curl -x http://172.19.0.1:1081 "$SUB_URL" → 200.
7. bash /opt/vless-updater/update.sh → "healthy".

## Откат
Перед каждой правкой делается бэкап config.json.bakДДММ. Откат:
cp /etc/sing-box/config.json.bak0411 /etc/sing-box/config.json && systemctl restart sing-box
(.bak0411 — до добавления OpenAI; .bak0211 — до добавления ithyper.ru)

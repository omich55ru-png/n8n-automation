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
| ithyper.ru | proxy | Скачивание подписки: панель sub.ithyper.ru зависает для прямого трафика с VPS |

Правило ithyper.ru добавлено 02.11.2026. Остальное идёт напрямую (final: direct).
Шаблон конфига: sing-box/config.template.json.

## Автообновление ноды (/opt/vless-updater)
1. health: GET openrouter.ai через прокси; 200 → выход.
2. Подписка скачивается через прокси (curl -x "$PROXY").
3. Успех → копия в nodes_cache.txt. Сбой → берётся кэш; кэша нет → алерт.
4. apply_node.py выбирает живую ноду (АВТОВЫБОР первым) и правит только поля vless-outbound.
5. Рестарт sing-box, повторная проверка, уведомление в Telegram.

Антиспам: не чаще 1 алерта в 4 часа (метка времени в .alert_ts).
Секреты (TG_TOKEN, SUB_URL, PROXY) — в /opt/vless-updater/env, в git не попадают.

## Инциденты
| Дата | Что случилось | Причина | Решение |
|---|---|---|---|
| 22.09 | reality verification failed на всех нодах | Провайдер сменил UUID | Обновить uuid из подписки |
| 29.09 | Пропало telegram-правило | Конфиг пересоздан setup-скриптом | Правила хранятся в шаблоне sing-box/ |
| 02.11 | Апдейтер получал 000 от панели | Подписка качалась напрямую, панель вешает ответ | Правило ithyper.ru + curl -x + кэш нод |

## Чек-лист после переустановки
1. Взять sing-box/config.template.json, подставить NODE_HOST, YOUR_UUID, NODE_PUBLIC_KEY, NODE_SHORT_ID.
2. Убедиться, что в route.rules все три группы доменов: jq '.route.rules' /etc/sing-box/config.json
3. sing-box check -c /etc/sing-box/config.json && systemctl restart sing-box
4. Прокси: curl -x http://172.19.0.1:1081 https://openrouter.ai/api/v1/models → 200.
5. Подписка через туннель: curl -x http://172.19.0.1:1081 "$SUB_URL" → 200.
6. bash /opt/vless-updater/update.sh → "healthy".

## Откат
cp /etc/sing-box/config.json.bak0211 /etc/sing-box/config.json && systemctl restart sing-box

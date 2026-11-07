# VPN-прокси на VPS для n8n → OpenRouter

Секреты (UUID, XHTTP path, ссылка подписки, токены) в репозиторий не кладём: только плейсхолдеры.

## Архитектура (с 07.11.2026)
n8n (Docker) → http://172.19.0.1:1081 → Xray (VLESS/XHTTP/TLS) → нода провайдера (NL).
До 07.11.2026 стек был sing-box + VLESS/TCP/Reality. Провайдер перевёл сеть на XHTTP,
который sing-box не поддерживает, — сервер мигрирован на Xray-core (родная реализация XHTTP, лицензия MPL-2.0).
sing-box оставлен установленным (systemd: disabled) как исторический запасной вариант.

Split routing: через прокси идут только домены из routing.rules, остальное напрямую (freedom стоит первым outbound — это default).
Правила зашиты в vless-updater/build_xray_config.py: он пересоздаёт конфиг целиком, ручные правки routing будут перезаписаны.

## Правила маршрутизации
| Домены | Куда | Зачем |
|---|---|---|
| openrouter.ai, claude.ai, anthropic.com | proxy | LLM API (напрямую 403) |
| telegram.org, t.me, telesco.pe | proxy | Telegram |
| ithyper.ru | proxy | Подписка: панель периодически не отвечает прямому трафику |
| openai.com, chatgpt.com, oaistatic.com, oaiusercontent.com, oaistatsig.com | proxy | ChatGPT и OpenAI API |

Браузер и телефон используют Happ (Xray внутри), а не этот прокси.
Шаблон конфига: xray/config.template.json.

## Автообновление ноды (/opt/vless-updater, v3)
1. health: GET openrouter.ai через прокси; 200 → выход (при переходе fail→ok шлёт ✅).
2. Подписка: через прокси, при сбое — напрямую. Успех → nodes_cache.txt; сбой → кэш; нет кэша → ⚠️.
3. Перебор кандидатов (только ссылки xhttp+tls с sni; «АВТОВЫБОР» с security=none пропускается):
   build_xray_config.py собирает конфиг во временный файл с расширением .json → xray run -test →
   только при успехе cp в /usr/local/etc/xray/config.json → restart xray → health; 000 → следующая.
   Временный файл обязан иметь расширение .json — иначе xray не распознаёт формат (баг, найден краш-тестом 07.11).
4. Все кандидаты мертвы → ❌ один раз (state=fail).

Уведомления: ❌/✅ — всегда (по смене состояния, .state); троттлится только ⚠️ (1 раз в 4 часа, .alert_ts).
TimeoutStartSec=600 (override /etc/systemd/system/vless-updater.service.d/timeout.conf).
Секреты (TG_TOKEN, SUB_URL, PROXY) — в /opt/vless-updater/env, в git не попадают.

## Инциденты
| Дата | Что случилось | Причина | Решение |
|---|---|---|---|
| 22.09 | reality verification failed на всех нодах | Провайдер сменил UUID | Обновить uuid из подписки |
| 29.09 | Пропало telegram-правило | Конфиг пересоздан setup-скриптом | Правила в шаблоне/билдере |
| 02.11 | Апдейтер получал 000 от панели | Подписка качалась напрямую, панель вешала ответ | Правило ithyper.ru + curl -x + кэш нод |
| 07.11 | reality verification failed, openrouter/telegram 000 | Провайдер убил Reality-ноды (миграция на XHTTP); node3 мертва при живом TCP | Ручной переход на node2; update.sh v2 (перебор с auth-check) |
| 07.11 (2) | sing-box crash-луп: invalid public_key, счётчик рестартов 200+ | Промежуточная подписка со ссылками без pbk/sid; apply_node записал пустые ключи; restart без валидации | Полная миграция на Xray-core + XHTTP; update.sh v3 с gate xray run -test и фильтром кандидатов |

## Чек-лист после переустановки
1. Установить Xray: bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install
2. Взять xray/config.template.json, подставить NODE_HOST, YOUR_UUID, XHTTP_PATH → /usr/local/etc/xray/config.json
3. xray run -test -c /usr/local/etc/xray/config.json && systemctl enable --now xray
4. Прокси: curl -x http://172.19.0.1:1081 https://openrouter.ai/api/v1/models → 200; api.telegram.org → 302; api.openai.com/v1/models → 401 (401 без ключа — это норма, значит дошли)
5. bash /opt/vless-updater/update.sh → "healthy"; systemctl start vless-updater.timer

## Откат
- Конфиг xray: бэкапы /usr/local/etc/xray/config.json.bak* (перед правками делать всегда)
- update.sh: /opt/vless-updater/update.sh.bak0711-v2 — последняя sing-box-версия (эпоха Reality)
- Полный откат на sing-box имеет смысл, только если провайдер вернёт Reality-ноды

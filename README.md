# 🤖 MEXC Signal Bot v3.0

Профессиональный сигнальный бот для MEXC Futures с:
- **SMC/ICT анализом** (BOS, CHoCH, FVG, Order Blocks, Liquidity Sweeps)
- **Техническими индикаторами** (EMA, RSI, Stoch RSI, MACD, Supertrend, ADX, Volume)
- **BTC Master Signal** — мульти-индикаторный сигнал для биткоина
- **Мультимонетный скан** — топ пары MEXC + фильтр шума
- **Спред-арбитраж** — MEXC vs DEX, спреды > 10%
- **ИИ Ассистент** на Groq (Llama 3.3 70B) — задавай вопросы прямо в боте
- **Геополитические новости** (Иран, Трамп, нефть, крипто)
- **Railway деплой** — 1 клик

---

## 📁 Структура проекта

```
signal-bot/
├── main.py                      # Точка входа
├── requirements.txt
├── railway.toml                 # Railway конфиг
├── Procfile
├── .env.example                 # Шаблон переменных
├── config/
│   └── settings.py              # Все настройки
└── src/
    ├── bot.py                   # Telegram бот, хендлеры, джобы
    ├── ai/
    │   └── groq_assistant.py    # Groq ИИ ассистент
    ├── indicators/
    │   └── engine.py            # EMA, RSI, MACD, Supertrend, ADX...
    ├── smc/
    │   └── engine.py            # BOS, CHoCH, FVG, OB, Sweeps
    ├── signals/
    │   ├── btc_signal.py        # BTC мульти-индикаторный сигнал
    │   └── scanner.py           # Скан всех монет
    ├── spread/
    │   └── scanner.py           # Спред MEXC vs DEX
    ├── news/
    │   └── fetcher.py           # RSS + NewsAPI + CryptoPanic
    └── utils/
        ├── mexc_client.py       # MEXC API клиент
        ├── formatter.py         # Форматирование сообщений
        └── logger.py            # Логгер
```

---

## 🚀 Деплой на Railway (5 минут)

### 1. GitHub репозиторий

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/ВАШ_ЮЗЕР/mexc-signal-bot.git
git push -u origin main
```

### 2. Railway

1. Зайди на [railway.app](https://railway.app)
2. **New Project → Deploy from GitHub repo**
3. Выбери свой репозиторий
4. Перейди в **Settings → Variables** и добавь:

| Переменная | Значение |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Токен от @BotFather |
| `TELEGRAM_CHAT_ID` | ID твоего чата/канала |
| `GROQ_API_KEY` | Ключ с console.groq.com |
| `MIN_CONFLUENCE_SCORE` | `65` |
| `MIN_SPREAD_PCT` | `10.0` |
| `SIGNAL_COOLDOWN_MIN` | `15` |

5. Railway автоматически задеплоит бота.

---

## ⚙️ Получение ключей

### Telegram Bot Token
1. Открой @BotFather в Telegram
2. `/newbot` → задай имя и username
3. Скопируй токен

### Telegram Chat ID
1. Добавь бота в свой чат/канал
2. Напиши `/start`
3. Открой: `https://api.telegram.org/bot<TOKEN>/getUpdates`
4. Найди `"chat":{"id":XXXXXXXXX}` — это твой ID

### Groq API Key (бесплатно)
1. Зайди на [console.groq.com](https://console.groq.com)
2. Создай аккаунт → API Keys → Create key

### NewsAPI (опционально, бесплатно)
1. [newsapi.org](https://newsapi.org) → Get API Key
2. 100 запросов/день на бесплатном плане

### CryptoPanic (опционально, бесплатно)
1. [cryptopanic.com/developers/api](https://cryptopanic.com/developers/api/)

---

## 📱 Команды бота

| Команда | Описание |
|---|---|
| `/btc` | BTC сигнал (Long/Short) |
| `/btc_mtf` | BTC анализ 15m+1h+4h |
| `/scan` | Скан топ монет MEXC |
| `/signal SOLUSDT` | Сигнал по конкретной паре |
| `/spread` | Спреды > 10% MEXC vs DEX |
| `/news` | Важные новости |
| `/geo` | Геополитика (Иран, Трамп...) |
| `/smc BTCUSDT 1h` | SMC анализ (BOS/FVG/OB) |
| `/ai Стоит ли шортить BTC?` | ИИ ассистент |
| `/market` | Обзор рынка MEXC |
| `/set_tf 1h` | Установить таймфрейм |
| `/set_min 70` | Мин. уверенность сигнала |
| `/status` | Статус бота |

---

## 🧠 Логика сигналов

### Anti-noise фильтры
- ADX > 18 (рынок должен быть в тренде)
- Volume ratio > 0.5x (достаточный объём)
- Индикаторы + SMC должны **совпадать** по направлению
- Кулдаун 15 мин на монету после сигнала

### Confluence score
- **Индикаторы (55%)**: EMA stack, RSI, Stoch RSI, MACD, Supertrend, ADX, Volume, BB, Hull MA, паттерны свечей
- **SMC (45%)**: BOS/CHoCH, FVG, Order Blocks, Liquidity Sweeps, POI

### SMC логика (как на скринах)
- **BOS** = подтверждение по закрытию тела свечи (без учёта теней)
- **CHoCH** = первый BOS против структуры = сигнал разворота
- **FVG** = 3-свечной imbalance ≥ 0.15% → зона возврата цены
- **Order Block** = последняя противоположная свеча перед displacement
- **Sweep** = ложный пробой уровня ликвидности → разворот

---

## ⚠️ Дисклеймер

Бот не является финансовым советником. Всегда используй риск-менеджмент.
Не торгуй на деньги, которые не готов потерять.

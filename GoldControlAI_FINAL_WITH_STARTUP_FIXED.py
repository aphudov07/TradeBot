import MetaTrader5 as mt5
import pandas as pd
import telebot
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import time
import os
import threading

SYMBOL = "XAUUSD"
TIMEFRAME = mt5.TIMEFRAME_M1
BARS = 100
LOT = 0.1
TP_SL_RATIO = 2.0
ATR_MULTIPLIER = 0.5
MAGIC_NUMBER = 123456
TOKEN = "7732122209:AAHB_OTeyu5Z5gmC0SVRBeI95T2LU2PFZzc"
CHAT_ID = "6468849975"
LOG_FILE = LOG_FILE = "trade_log.csv"

bot = telebot.TeleBot(TOKEN)
last_trade_time = None
paused = False

# === Telegram handlers ===
@bot.message_handler(commands=['pause'])
def handle_pause(msg):
    global paused
    paused = True
    bot.send_message(msg.chat.id, "⏸ Торговля приостановлена.")

@bot.message_handler(commands=['resume'])
def handle_resume(msg):
    global paused
    paused = False
    bot.send_message(msg.chat.id, "▶️ Торговля возобновлена.")

@bot.message_handler(commands=['closeall'])
def handle_closeall(msg):
    positions = mt5.positions_get(symbol=SYMBOL)
    for p in positions:
        mt5.order_send({
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": SYMBOL,
            "volume": p.volume,
            "type": mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
            "position": p.ticket,
            "price": mt5.symbol_info_tick(SYMBOL).bid if p.type == 0 else mt5.symbol_info_tick(SYMBOL).ask,
            "deviation": 20,
            "magic": MAGIC_NUMBER,
            "comment": "GoldControlAI closeall"
        })
    bot.send_message(msg.chat.id, "🛑 Все сделки закрыты.")

@bot.message_handler(commands=['status'])
def handle_status(msg):
    acc = mt5.account_info()
    if acc:
        text = f"💼 Баланс: {acc.balance:.2f}, Средства: {acc.equity:.2f}\n"
        pos = mt5.positions_get(symbol=SYMBOL)
        text += f"📊 Позиции: {len(pos)}" if pos else "Нет открытых позиций."
        bot.send_message(msg.chat.id, text)

@bot.message_handler(commands=['stats'])
def handle_stats(msg):
    if not os.path.exists(LOG_FILE):
        bot.send_message(msg.chat.id, "Лог-файл не найден.")
        return
    df = pd.read_csv(LOG_FILE)
    if df.empty:
        bot.send_message(msg.chat.id, "Нет завершённых сделок.")
        return
    total = len(df)
    profit = df['result'].sum()
    wins = df[df['result'] > 0].shape[0]
    losses = df[df['result'] <= 0].shape[0]
    winrate = wins / total * 100 if total else 0
    bot.send_message(msg.chat.id,
        f"📈 Всего сделок: {total}\n✅ Профит: {profit:.2f}\n🎯 Winrate: {winrate:.1f}%\n🥇 Побед: {wins}, ❌ Убытков: {losses}")

# === Технические функции ===

def send_telegram(msg, image=None):
    print(msg)
    bot.send_message(CHAT_ID, msg)
    if image and os.path.exists(image):
        with open(image, "rb") as img:
            bot.send_photo(CHAT_ID, img)

def log_trade(direction, price, sl, tp, lot, ticket=None, result=None):
    row = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "direction": direction,
        "price": round(price, 2),
        "sl": round(sl, 2),
        "tp": round(tp, 2),
        "lot": lot,
        "result": result if result is not None else "",
        "ticket": ticket if ticket is not None else "",
        "position_id": "",
        "strategy": "EMA+Volume+ATR"
    }
    df = pd.DataFrame([row])
    df["position_id"] = position_id if "position_id" in locals() else ""
    df.to_csv(LOG_FILE, mode='a', header=not os.path.exists(LOG_FILE), index=False)

def get_data(tf):
    rates = mt5.copy_rates_from_pos(SYMBOL, tf, 0, BARS)
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['ema20'] = df['close'].ewm(span=20).mean()
    df['ema50'] = df['close'].ewm(span=50).mean()
    df['atr'] = (df['high'] - df['low']).rolling(14).mean().fillna(0)
    df['volume_avg'] = df['tick_volume'].rolling(10).mean()
    return df

def create_plot(df, direction, price, sl, tp, name):
    plt.figure(figsize=(10, 5))
    plt.plot(df['time'], df['close'], label='Цена')
    plt.plot(df['time'], df['ema20'], label='EMA20', linestyle='--')
    plt.plot(df['time'], df['ema50'], label='EMA50', linestyle='--')
    plt.axhline(price, color='blue', label='Вход')
    plt.axhline(sl, color='red', label='SL')
    plt.axhline(tp, color='green', label='TP')
    plt.scatter(df['time'].iloc[-2], price, color='black', label=direction.upper())
    plt.legend(); plt.xticks(rotation=45); plt.tight_layout()
    plt.savefig(name); plt.close()

def open_trade(direction, price, sl, tp):
    global last_trade_time
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": LOT,
        "type": mt5.ORDER_TYPE_BUY if direction == "buy" else mt5.ORDER_TYPE_SELL,
        "price": mt5.symbol_info_tick(SYMBOL).ask if direction == "buy" else mt5.symbol_info_tick(SYMBOL).bid,
        "sl": sl, "tp": tp,
        "deviation": 20,
        "magic": MAGIC_NUMBER,
        "comment": "GoldControlAI",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    ticket = result.order if result.retcode == mt5.TRADE_RETCODE_DONE else None
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        log_trade(direction, price, sl, tp, LOT, ticket)
        send_telegram(f"✅ Сделка: {direction.upper()} {SYMBOL} @ {price:.2f}\nSL: {sl:.2f} TP: {tp:.2f}")
    else:
        send_telegram(f"❌ Ошибка открытия: {result.comment}")

def already_trading():
    pos = mt5.positions_get(symbol=SYMBOL)
    return any(p.magic == MAGIC_NUMBER for p in pos)

def check_signal():
    global last_trade_time, paused
    if paused:
        print("⏸ Торговля на паузе")
        return

    df = get_data(TIMEFRAME)
    if df.empty:
        send_telegram("⚠️ Нет данных — открой XAUUSD в M1 и M15 в терминале.")
        return

    last = df.iloc[-2]
    candle_time = last['time']

    if last_trade_time == candle_time or already_trading():
        return
    bullish = last['close'] > last['open']
    bearish = last['close'] < last['open']
    high_volume = last['tick_volume'] > last['volume_avg']
    atr = last['atr']

    if bullish and high_volume:
        sl = last['low'] - (atr * ATR_MULTIPLIER)
        tp = last['close'] + abs(last['close'] - sl) * TP_SL_RATIO
        create_plot(df, "buy", last['close'], sl, tp, "chart_buy.png")
        send_telegram("📡 Сигнал BUY\nПричина: EMA20 > EMA50, свеча бычья, объём выше среднего, ATR > 0", image="chart_buy.png")
        send_telegram("🤖 Открываю сделку BUY...")
        open_trade("buy", last['close'], sl, tp)
        last_trade_time = candle_time

    elif bearish and high_volume:
        sl = last['high'] + (atr * ATR_MULTIPLIER)
        tp = last['close'] - abs(last['close'] - sl) * TP_SL_RATIO
        create_plot(df, "sell", last['close'], sl, tp, "chart_sell.png")
        send_telegram("📡 Сигнал SELL\nПричина: EMA20 < EMA50, свеча медвежья, объём выше среднего, ATR > 0", image="chart_sell.png")
        send_telegram("🤖 Открываю сделку SELL...")
        open_trade("sell", last['close'], sl, tp)
        last_trade_time = candle_time

    else:
        msg = f"[{datetime.now()}] 🔍 Сигналов нет — продолжаю наблюдение."
        print(msg)
        send_telegram("🔍 Сигналов нет — продолжаю наблюдение.")

# === Трейлинг-стоп ===
def modify_sl(ticket, new_sl):
    order = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "sl": new_sl,
        "tp": 0.0,
        "magic": MAGIC_NUMBER,
        "comment": "Trailing SL update",
    }
    result = mt5.order_send(order)
    print(f"[TRAILING] SL обновлён для позиции {ticket} → {new_sl:.2f}, результат: {result.comment}")

def trail_positions():
    trail_activation_profit = 0.5
    trail_step = 0.25
    while True:
        positions = mt5.positions_get(symbol=SYMBOL)
        if positions:
            tick = mt5.symbol_info_tick(SYMBOL)
            for pos in positions:
                profit = pos.profit
                if profit >= trail_activation_profit:
                    if pos.type == 0:
                        new_sl = tick.bid - trail_step
                        if new_sl > pos.sl:
                            modify_sl(pos.ticket, new_sl)
                    elif pos.type == 1:
                        new_sl = tick.ask + trail_step
                        if new_sl < pos.sl:
                            modify_sl(pos.ticket, new_sl)
        time.sleep(1)








# === Инициализация лог-файла ===
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, "w") as f:
        f.write("timestamp,direction,price,sl,tp,lot,result,ticket,position_id,strategy\n")



def update_closed_trades():
    if not os.path.exists(LOG_FILE):
        return 0
    df = pd.read_csv(LOG_FILE)
    if 'result' not in df.columns:
        return 0

    updated = 0
    for i in range(len(df)):
        if pd.isna(df.at[i, 'result']):
            ticket_price = df.at[i, 'price']
            direction = df.at[i, 'direction']
            ts = pd.to_datetime(df.at[i, 'timestamp'])
            deals = mt5.history_deals_get(datetime.now() - timedelta(days=5), datetime.now())
    if not deals:
        print("[ERROR] Сделки не найдены в истории.")
        return

    from collections import defaultdict
    grouped = defaultdict(list)
    for d in deals:
        grouped[d.position_id].append(d)

    filtered_orders = []
    for pos_id, deal_list in grouped.items():
        real_deal = next((d for d in deal_list if abs(d.profit) > 0.0001), None)
        if real_deal:
            filtered_orders.append(real_deal)
        else:
            filtered_orders.append(deal_list[0])

    orders = filtered_orders
    if orders:
            for deal in orders:
                if deal.symbol == SYMBOL and deal.type in [mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL]:
                    if int(deal.ticket) == int(df.at[i, 'ticket']) or int(deal.position_id) == int(df.at[i, 'ticket']):
                        df.at[i, 'result'] = round(deal.profit, 2)
                        updated += 1
                        break
                           
    df.to_csv(LOG_FILE, index=False)
    return updated



# === Запуск ===



@bot.message_handler(commands=['report'])
def handle_report(msg):
    generate_report()
    if os.path.exists("report.png"):
        with open("report.png", "rb") as photo:
            bot.send_photo(msg.chat.id, photo)
    else:
        bot.send_message(msg.chat.id, "❌ Отчёт не создан — нет данных.")

def generate_report():
    log_file = "trade_log.csv"
    if not os.path.exists(log_file):
        print("Лог-файл не найден.")
        return

    df = pd.read_csv(log_file)
    if df.empty or 'result' not in df.columns:
        print("Нет данных для отчета.")
        return

    df['cum_profit'] = df['result'].cumsum()
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    fig, axs = plt.subplots(3, 1, figsize=(10, 12))

    axs[0].plot(df['timestamp'], df['cum_profit'], label='Кумулятивная прибыль', color='blue')
    axs[0].set_title("📈 Кривая доходности")
    axs[0].set_ylabel("Баланс")
    axs[0].grid(True)

    wins = df[df['result'] > 0].shape[0]
    losses = df[df['result'] <= 0].shape[0]
    axs[1].bar(['Победы', 'Убытки'], [wins, losses], color=['green', 'red'])
    axs[1].set_title("🎯 Победы vs Убытки")

    df['date'] = df['timestamp'].dt.date
    daily = df.groupby('date')['result'].sum()
    axs[2].bar(daily.index.astype(str), daily.values, color='purple')
    axs[2].set_title("📅 Прибыль по дням")
    axs[2].tick_params(axis='x', rotation=45)

    plt.tight_layout()
    plt.savefig("report.png")
    plt.close()


@bot.message_handler(commands=['help'])
def handle_help(msg):
    bot.send_message(msg.chat.id, """📘 Команды GoldControlAI:
/pause – Приостановить торговлю
/resume – Возобновить торговлю
/closeall – Закрыть все сделки
/status – Баланс и открытые позиции
/stats – Статистика по закрытым сделкам
/report – Визуальный отчёт из лога
/last – Последняя завершённая сделка
/profit – Текущий плавающий PnL
/help – Список команд""")

@bot.message_handler(commands=['last'])
def handle_last(msg):
    if not os.path.exists(LOG_FILE):
        bot.send_message(msg.chat.id, "Лог-файл не найден.")
        return
    df = pd.read_csv(LOG_FILE)
    if df.empty:
        bot.send_message(msg.chat.id, "Нет завершённых сделок.")
        return
    last = df.iloc[-1]
    message = (
        f"🕒 {last['timestamp']}\n"
        f"📈 {last['direction'].upper()} @ {last['price']}\n"
        f"🎯 TP: {last['tp']} | SL: {last['sl']}\n"
        f"💰 Результат: {last['result']}"
    )
    bot.send_message(msg.chat.id, message)

@bot.message_handler(commands=['profit'])
def handle_profit(msg):
    positions = mt5.positions_get(symbol=SYMBOL)
    if not positions:
        bot.send_message(msg.chat.id, "Нет открытых позиций.")
        return
    total_profit = sum(p.profit for p in positions)
    bot.send_message(msg.chat.id, f"📈 Текущий PnL по {SYMBOL}: {total_profit:.2f} USD")

@bot.message_handler(commands=['stats'])
def handle_stats(msg):
    if not os.path.exists(LOG_FILE):
        bot.send_message(msg.chat.id, "Лог-файл не найден.")
        return
    df = pd.read_csv(LOG_FILE)
    if df.empty:
        bot.send_message(msg.chat.id, "Нет завершённых сделок.")
        return
    total = len(df)
    profit = df['result'].sum()
    wins = df[df['result'] > 0].shape[0]
    losses = df[df['result'] <= 0].shape[0]
    winrate = wins / total * 100 if total else 0
    max_win = df['result'].max()
    max_loss = df['result'].min()
    bot.send_message(msg.chat.id,
    f"📈 Всего: {total}\n"
    f"✅ Профит: {profit:.2f}\n"
    f"🎯 Winrate: {winrate:.1f}%\n"
    f"🥇 Побед: {wins}, ❌ Убытков: {losses}\n"
    f"📊 Макс. профит: {max_win:.2f}, Макс. убыток: {max_loss:.2f}")



def update_closed_trades():
    if not os.path.exists(LOG_FILE):
        print(f"[ERROR] Лог-файл не найден: {LOG_FILE}")
        return

    try:
        df = pd.read_csv(LOG_FILE)
    except Exception as e:
        print(f"[ERROR] Ошибка чтения файла: {e}")
        return

    if 'ticket' not in df.columns or 'result' not in df.columns:
        print("[ERROR] В логе отсутствуют нужные поля 'ticket' и 'result'")
        return

        

    if not mt5.initialize():
        print("❌ MetaTrader 5 не запущен")
        send_telegram("❌ MetaTrader 5 не запущен")
    else:
        print("✅ MetaTrader 5 инициализирован")

        return

    deals = mt5.history_deals_get(datetime.now() - timedelta(days=5), datetime.now())
    if not deals:
        print("[ERROR] Сделки не найдены в истории.")
        return

    from collections import defaultdict
    grouped = defaultdict(list)
    for d in deals:
        grouped[d.position_id].append(d)

    filtered_orders = []
    for pos_id, deal_list in grouped.items():
        real_deal = next((d for d in deal_list if abs(d.profit) > 0.0001), None)
        if real_deal:
            filtered_orders.append(real_deal)
        else:
            filtered_orders.append(deal_list[0])

    orders = filtered_orders

    from collections import defaultdict
    grouped = defaultdict(list)
    for d in orders:
        grouped[d.position_id].append(d)

    filtered_orders = []
    for pos_id, deal_list in grouped.items():
        real_deal = next((d for d in deal_list if d.profit != 0.0), None)
        if real_deal:
            filtered_orders.append(real_deal)
        else:
            filtered_orders.append(deal_list[0])

        orders = filtered_orders
        if orders is None:
            print("[ERROR] Не удалось получить сделки из истории.")
            mt5.shutdown()
            return

    print(f"[DEBUG] Получено {len(orders)} сделок из MT5")

    updated = 0
    for i in range(len(df)):
        if pd.isna(df.at[i, 'result']):
            log_ticket = int(df.at[i, 'ticket'])
            for deal in orders:
                if deal.position_id == log_ticket:
                    df.at[i, 'result'] = round(deal.profit, 2)
                    print(f"[MATCH] ticket={log_ticket} → profit={deal.profit}")
                    updated += 1
                    break
            else:
                print(f"[MISS] ticket={log_ticket} — не найдено в MT5 истории")

    try:
        df.to_csv(LOG_FILE, index=False)
        print(f"📊 Обновлено всего: {updated} строк.")
    except Exception as e:
        print(f"[ERROR] Не удалось сохранить лог: {e}")

    mt5.shutdown()



# === Инициализация лог-файла ===
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, "w") as f:
        f.write("timestamp,direction,price,sl,tp,lot,result,strategy\n")

# === Запуск ===


def report_closed_trades():
    updated = 0
    if not os.path.exists(LOG_FILE):
        return
    df = pd.read_csv(LOG_FILE)
    if df.empty or 'result' not in df.columns:
        return
    last = df.iloc[-1]
    if pd.notna(last['result']):
        count = len(df)
        result = float(last['result'])
        status = "по тейк-профиту ✅" if result > 0 else "по стоп-лоссу ❌"
        message = (
            f"📉 Сделка завершена: {last['direction'].upper()} @ {last['price']}\n"
            f"SL: {last['sl']} | TP: {last['tp']}\n"
            f"Завершена {status}\n"
            f"💰 Результат: {result:.2f} USD"
        )
        send_telegram(f"📊 Сделка #{count}")
        send_telegram(message)
        df = pd.read_csv(LOG_FILE)
        if 'result' not in df.columns:
            return
    for i in range(len(df)):
        price = df.at[i, 'price']
        ts = pd.to_datetime(df.at[i, 'timestamp'])
        deals = mt5.history_deals_get(ts, datetime.now())
        if deals:
            log_ticket = int(df.at[i, 'ticket'])
            deals_for_ticket = [d for d in deals if d.position_id == log_ticket or d.ticket == log_ticket]
            if deals_for_ticket:
                last_deal = deals_for_ticket[-1]
                if last_deal.profit != 0.0:
                    df.at[i, 'result'] = round(last_deal.profit, 2)
                    print(f"[MATCH] ticket={log_ticket} → profit={last_deal.profit}")
                    updated += 1
                else:
                    print(f"[SKIP] ticket={log_ticket} → найдена сделка с нулевым профитом")
            else:
                print(f"[MISS] ticket={log_ticket} → не найдено в МТ5 истории")

    try:
        df.to_csv(LOG_FILE, index=False)
        print(f"✅ Обновлено всего: {updated} сделок.")
        bot.send_message(CHAT_ID, f"✅ Обновлено {updated} сделок.")
    except Exception as e:
        bot.send_message(CHAT_ID, f"⚠️ Ошибка обновления: {e}")

def start_polling():
    while True:
        try:
            bot.polling(none_stop=True)
        except Exception as e:
            print(f"[Telegram ERROR] {e}")
            time.sleep(5)

    

    if not mt5.initialize():
        print("❌ MetaTrader 5 не запущен")
        send_telegram("❌ MetaTrader 5 не запущен")
    else:
        print("✅ MetaTrader 5 инициализирован")


    threading.Thread(target=start_polling).start()
    threading.Thread(target=trail_positions).start()

    while True:
        check_signal()
        update_closed_trades()
        report_closed_trades()
        time.sleep(60)

@bot.message_handler(commands=['refreshlog'])
def handle_refreshlog(msg):
    try:
        if not os.path.exists(LOG_FILE):
            bot.send_message(msg.chat.id, "❌ Лог-файл не найден.")
            return
        df = pd.read_csv(LOG_FILE)
        if 'result' not in df.columns or 'ticket' not in df.columns:
            bot.send_message(msg.chat.id, "⚠️ В логе не хватает необходимых полей.")
            return

        for i in range(len(df)):
            if pd.isna(df.at[i, 'result']):
                ticket = df.at[i, 'ticket']
                if pd.isna(ticket) or ticket == '':
                    continue
                ticket = int(ticket)
                deals = mt5.history_deals_get(datetime.now() - timedelta(days=2), datetime.now())
                if deals:
                    for d in deals:
                        if d.ticket == ticket or d.position_id == ticket:
                            df.at[i, 'result'] = round(d.profit, 2)
                            updated += 1
                            break
        try:
            df.to_csv(LOG_FILE, index=False)
            bot.send_message(msg.chat.id, f"✅ Обновлено {updated} сделок.")
        except Exception as e:
            bot.send_message(msg.chat.id, f"⚠️ Ошибка обновления: {e}")
    except Exception as e:
        bot.send_message(msg.chat.id, f"⚠️ Ошибка в refreshlog: {e}")


from datetime import datetime, timedelta

def refresh_log_results():
    if not os.path.exists(LOG_FILE):
        print("❌ Лог-файл не найден.")
        return

    try:
        df = pd.read_csv(LOG_FILE)
    except Exception as e:
        print(f"❌ Ошибка чтения CSV: {e}")
        return

    if 'ticket' not in df.columns or 'result' not in df.columns:
        print("⚠️ Отсутствуют колонки ticket или result в логе.")
        return

    updated = 0
    now = datetime.now()
    since = now - timedelta(days=5)
    deals = mt5.history_deals_get(since, now)
    if deals is None:
        print("⚠️ Сделки не найдены в истории.")
        return

    for i, row in df.iterrows():
        if pd.isna(row['result']) and not pd.isna(row['ticket']):
            try:
                ticket = int(row['ticket'])
                for d in deals:
                    if d.ticket == ticket or d.order == ticket or getattr(d, 'position_id', -1) == ticket:
                        df.at[i, 'result'] = round(d.profit, 2)
                        updated += 1
                        print(f"[UPDATE] ticket={ticket} → profit={d.profit}")
                        break
            except Exception as e:
                print(f"[ERROR] Ошибка при обновлении строки {i}: {e}")

    try:
        df.to_csv(LOG_FILE, index=False)
        print(f"✅ Обновлено {updated} сделок.")
    except Exception as e:
        print(f"❌ Ошибка сохранения CSV: {e}")


def trail_loop():
    while True:
        positions = mt5.positions_get(symbol=SYMBOL)
        tick = mt5.symbol_info_tick(SYMBOL)
        print(f"[TRAIL] Tick: bid={tick.bid}, ask={tick.ask} | Positions: {len(positions) if positions else 0}")
        if positions:
            for pos in positions:
                profit = pos.profit
                print(f"[TRAIL] Position {pos.ticket}: profit={profit}, sl={pos.sl}")
                if profit >= trail_activation_profit:
                    if pos.type == 0:
                        new_sl = tick.bid - trail_step
                        if new_sl < pos.price_open:
                            modify_sl(pos.ticket, new_sl)
                            print(f"[TRAIL] Updated SL for BUY {pos.ticket} to {new_sl}")
                    elif pos.type == 1:
                        new_sl = tick.ask + trail_step
                        if new_sl > pos.price_open:
                            modify_sl(pos.ticket, new_sl)
                            print(f"[TRAIL] Updated SL for SELL {pos.ticket} to {new_sl}")
        time.sleep(1)

def start_polling():
    while True:
        try:
            bot.polling(none_stop=True)
        except Exception as e:
            print(f"[Telegram ERROR] {e}")
            time.sleep(5)

def logic_loop():
    while True:
        check_signal()
        update_closed_trades()
        report_closed_trades()
        time.sleep(60)

# === Main startup ===
if not mt5.initialize():
    print("❌ MetaTrader 5 не запущен")
    send_telegram("❌ MetaTrader 5 не запущен")
else:
    print("✅ Бот запущен.")
    send_telegram("🤖 Бот запущен и готов к торговле!")
    threading.Thread(target=start_polling).start()
    threading.Thread(target=trail_loop).start()
    threading.Thread(target=logic_loop).start()

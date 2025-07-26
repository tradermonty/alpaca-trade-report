from alpaca_trade_api.rest import TimeFrame, TimeFrameUnit
from api_clients import get_alpaca_client
from datetime import datetime, timedelta
import pandas as pd
import time
import smtplib
import talib
import os
from dotenv import load_dotenv
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import uptrend_stocks
import strategy_allocation

from common_constants import ACCOUNT, TIMEZONE
from logging_config import get_logger
load_dotenv()

# モジュール用ロガー
logger = get_logger(__name__)

TZ_NY = TIMEZONE.NY  # Migrated from common_constants
TZ_UTC = TIMEZONE.UTC  # Migrated from common_constants

TEST_MODE = False  # Migrated to constant naming
TEST_DATETIME = pd.Timestamp(datetime.now().astimezone(TZ_NY)) - timedelta(days=240)

ALPACA_ACCOUNT = ACCOUNT.get_account_type()  # Migrated from common_constants

# API クライアント初期化
alpaca_client = get_alpaca_client(ALPACA_ACCOUNT)
api = alpaca_client.api  # 後方互換性のため

# Gmail App Password from environment variables
GMAIL_PASSWORD = os.getenv('GMAIL_APP_PASSWORD')
if not GMAIL_PASSWORD:
    raise ValueError("GMAIL_APP_PASSWORD environment variable not set")

# 設定値をconfig.pyから取得
from config import trading_config
UPTREND_THRESH = trading_config.UPTREND_THRESHOLD

# 投資銘柄リスト
dividend_symbols = ['SCHD', 'TXN', 'ABBV', 'LMT', 'HD', 'CVX', 'O', 'PG', 'JNJ', 'JPM', 'PAYX',
                    'EPD', 'PEP', 'MSFT', 'SLF', 'BKH', 'LRCX', 'APD', 'GPC', 'YUM', 'LYB',
                    'EFC', 'VZ', 'MO', 'KMB', 'CSCO', 'STT', 'IPG', 'PFE', 'MDLZ', 'TGT',
                    'UNM', 'DG', 'HIG', 'KVUE', 'CME', 'UNP', 'KR', 'VLO', 'ITW', 'BR', 'SIG',
                    'LEN', 'MMC', 'WM']
# dividend_symbols = ['SCHD', 'ABBV']

# ポートフォリオの配分
allocations = {'SCHD': 0.25}
remaining_allocation = (1 - allocations['SCHD']) / (len(dividend_symbols) - 1)
for symbol in dividend_symbols[1:]:  # SCHD以外の銘柄に均等配分
    allocations[symbol] = remaining_allocation

# Alpacaのアカウント情報を取得
account = api.get_account()

# 残高の取得
cash_available = float(account.cash)

bars_1min = ""


def send_email_via_gmail(subject, message, recipient_email, sender_email, sender_password):
    try:
        # Create the email
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = recipient_email
        msg['Subject'] = subject

        # Attach the message
        msg.attach(MIMEText(message, 'plain'))

        # Connect to Gmail's SMTP server
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()  # Start TLS encryption
        server.login(sender_email, sender_password)  # Log in to the server

        # Send the email
        server.sendmail(sender_email, recipient_email, msg.as_string())

        # Disconnect from the server
        server.quit()

        logger.info("Email sent successfully!")

    except Exception as e:
        logger.error("Failed to send email. Error: %s", e)


def get_existing_positions():
    positions = api.list_positions()
    return positions


def is_closing_time_range(range_minutes=1):
    if TEST_MODE:
        # close_dt = pd.Timestamp(str(test_datetime.date()) + " " + str(close_time), tz=TZ_NY)
        # close_dt -= timedelta(minutes=2)
        current_dt = pd.Timestamp(test_datetime)
    else:
        # close_dt = pd.Timestamp(str(datetime.date.today()) + " " + str(close_time), tz=TZ_NY)
        current_dt = pd.Timestamp(datetime.now().astimezone(TZ_NY))

    cal = api.get_calendar(start=str(current_dt.date()), end=str(current_dt.date()))

    if len(cal) > 0:
        close_time = cal[0].close
        close_dt = pd.Timestamp(str(current_dt.date()) + " " + str(close_time), tz=TZ_NY)
    else:
        logger.info("Market will not open on the date.")
        return False

    if close_dt - timedelta(minutes=range_minutes) <= current_dt < close_dt:
        logger.debug("Past closing time range")
        return True
    else:
        logger.debug("%s it's not in closing time range", current_dt)
        return False


def get_last_minute_of_day():
    now = datetime.now()
    market_close_time = now.replace(hour=15, minute=30, second=0, microsecond=0) - timedelta(minutes=30)
    return market_close_time


def is_market_open():
    if TEST_MODE:
        return True
    else:
        clock = api.get_clock()
        return clock.is_open


def get_latest_price(symbol):
    global test_datetime
    close = 0

    if TEST_MODE:
        # bars = api.get_bars(symbol, TimeFrame(1, TimeFrameUnit.Minute),
        #                     start=test_datetime.date(), end=test_datetime.date()).df

        start_time = pd.Timestamp(test_datetime) - timedelta(minutes=60)
        end_time = pd.Timestamp(test_datetime) - timedelta(minutes=1)

        bars_1min = api.get_bars(symbol, TimeFrame(1, TimeFrameUnit.Minute),
                                 start=start_time.date(), end=str(test_datetime.date())).df

        bars = bars_1min.between_time(start_time.astimezone(TZ_UTC).time(), end_time.astimezone(TZ_UTC).time())
        # bars = bars_1min[bars_1min.index <= end_time]
        if bars.size > 0:
            close = bars['close'].tail(1).iloc[0]

    else:
        # barset = api.get_barset(symbol, 'minute', 1)
        # return barset[symbol][0].c
        bar = api.get_latest_bar(symbol)
        close = bar.c

    return close


def get_rsi(symbol, period=14):
    """TA-Libを利用してRSIと株価データを取得する関数"""
    current_dt = pd.Timestamp(datetime.now().astimezone(TZ_NY))
    # RSI計算に必要な過去データを十分に確保する
    # periodの10倍などを目安にする方法は以前と同様
    start_dt = current_dt - timedelta(days=period * 10)
    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = current_dt.strftime("%Y-%m-%d")
    
    # 株価データを取得
    bars = api.get_bars(
        symbol,
        TimeFrame(1, TimeFrameUnit.Day),
        start=start_date,
        end=end_date
    ).df
    
    # 取得したDataFrameが時系列順ではない可能性があるのでソートしておく
    bars = bars.sort_index()
    
    # 終値の配列を取り出す
    closes = bars["close"].values
    
    # TA-LibでRSIを計算 (Wilder式)
    rsi_values = talib.RSI(closes, timeperiod=period)
    
    return pd.Series(rsi_values)


def get_rsi_old(symbol, period=14):
    global test_datetime
    ema = 0

    if TEST_MODE:
        current_dt = pd.Timestamp(test_datetime)
    else:
        current_dt = pd.Timestamp(datetime.now().astimezone(TZ_NY))

    start_dt = current_dt - timedelta(days=period * 10)

    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = current_dt.strftime("%Y-%m-%d")

    bars = api.get_bars(symbol, TimeFrame(1, TimeFrameUnit.Day), start=start_date, end=end_date).df
    closes = bars['close']

    delta = closes.diff()  # 差分を計算

    avg_gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    avg_loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

    # 相対強度を計算
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))  # RSIの計算式

    return rsi

def place_order(symbol, qty, side='buy'):
    try:
        api.submit_order(
            symbol=symbol,
            qty=qty,
            side=side,
            type='market',
            time_in_force='day',
        )
        logger.info("%s: %s order placed for %s shares.", symbol, side, qty)
    except Exception as e:
        logger.error("Error placing order for %s: %s", symbol, e)


def rebalance_portfolio():
    message = "=== Dividend rebalance result === \n\n"

    portfolio_value = float(api.get_account().portfolio_value)

    target_value = strategy_allocation.get_target_value('strategy5', ALPACA_ACCOUNT)
    # target_value = portfolio_value * 0.50  # 常にポートフォリオ50%を維持
    current_value = 0

    positions = get_existing_positions()
    for pos in positions:
        if pos.symbol in dividend_symbols:
            current_value += float(pos.market_value)

    if target_value > current_value:

        long_signal = uptrend_stocks.get_long_signal()
        uptrend_ratio = uptrend_stocks.get_ratio()

        for symbol in dividend_symbols:
            price = get_latest_price(symbol)
            allocation = allocations[symbol]

            target_symbol_value = target_value * allocation

            # 現在のポートフォリオでのシンボルの価値を取得
            current_symbol_value = sum(float(pos.market_value) for pos in positions if pos.symbol == symbol)

            # このシンボルに対してターゲット配分に達するための投資金額を計算
            invest_amount = (target_symbol_value - current_symbol_value) / 2  # 下落からの反発時に2回に分けて買い増し

            logger.debug("%s: target value: %.2f, current value: %.2f, invest_amount: %.2f", symbol, target_symbol_value, current_symbol_value, invest_amount)
            message += f"{symbol}: target value: {target_symbol_value:.2f}, current value: {current_symbol_value:.2f}, invenst_amount: {invest_amount:.2f}\n"

            # 投資金額が正の値の場合のみ（つまり、目標配分に達していない場合）
            if invest_amount > 0:
                qty = round(invest_amount / price)  # 株価に基づいて購入株数を計算
                if qty > 0:
                    # RSIの計算
                    rsi_series = get_rsi(symbol)
                    rsi_today = rsi_series.iloc[-1]  # 本日のRSI

                    # 相場全体でロングシグナルが出て、かつRSIが50以下の場合のみ買い増し
                    if long_signal == "Entry" and uptrend_ratio < UPTREND_THRESH and rsi_today <= 50:
                        logger.info("%s: uptrend and RSI criteria meet. placing buy order: %.2f x %.2f, %.2f (RSI: %.2f)", symbol, price, qty, price*qty, rsi_today)
                        message += f"{symbol}: uptrend and RSI criteria meet. placing buy order: {price:.2f} x {qty:.2f},  {price * qty:.2f} (RSI: {rsi_today:.2f})\n"
                        place_order(symbol, qty)
                    else:
                        logger.debug("%s: uptrend or RSI criteria does not meet. (RSI: %.2f)", symbol, rsi_today)
                        message += f"{symbol}: uptrend or RSI criteria does not meet. (RSI: {rsi_today:.2f})\n"

                        rsi_yesterday = rsi_series.iloc[-2]  # 昨日のRSI
                        rsi_min = rsi_series.rolling(window=14).min().iloc[-1]  # 14日間のRSIの最小値
                        rsi_sma_14 = rsi_series.rolling(window=14).mean()  # RSIの14日間SMA
                        rsi_sma_slope_today = rsi_sma_14.iloc[-1] - rsi_sma_14.iloc[-2]  # 今日のSMAの傾き
                        rsi_sma_slope_yesterday = rsi_sma_14.iloc[-2] - rsi_sma_14.iloc[-3]  # 昨日のSMAの傾き
                        rsi_sma_slope_2dago = rsi_sma_14.iloc[-3] - rsi_sma_14.iloc[-4]  # 2日前のSMAの傾き

                        # RSIの14SMAの傾きが下落から上昇に転換し、かつ直近14日間のRSIの最小値が30以下の場合に買い増し
                        if rsi_today >= 40 and rsi_yesterday < 40 and rsi_min <= 35:
                        # if rsi_sma_slope_2dago < 0 and rsi_sma_slope_yesterday > 0 and rsi_sma_slope_today > 0 and rsi_min <= 30:
                            logger.info("%s: placing buy order %.2f x %s --- rsi: %.2f, %.2f, %.2f", symbol, price, qty, rsi_today, rsi_yesterday, rsi_min)
                            message += f"{symbol}: placing buy order {price:.2f} x {qty} --- rsi: {rsi_today:.2f}, {rsi_yesterday:.2f}, {rsi_min:.2f}\n"
                            place_order(symbol, qty)
                        else:
                            logger.debug("%s: RSI criteria do not meet. --- rsi: %.2f, %.2f, %.2f", symbol, rsi_today, rsi_yesterday, rsi_min)
                            message += f"{symbol}: RSI criteria do not meet. --- rsi: {rsi_today:.2f}, {rsi_yesterday:.2f}, {rsi_min:.2f}\n"

            message += "\n"
                            
        try:
            # 現在の日付をYYYY-MM-DD形式で取得
            current_date = datetime.now().strftime("%Y-%m-%d")

            # 件名に日付を埋め込む
            send_email_via_gmail(f"Dividend stock rebalance result - {current_date}", message,
                     "taku.saotome@gmail.com", "taku.saotome@gmail.com",
                     GMAIL_PASSWORD)
            
        except Exception as error:
            logger.error("Sending email failed: %s", error)


def run_daily_trading():
    global test_datetime

    while True:
        if not is_market_open():
            logger.info("The market is closed today. Exit trading.")
            break

        # 毎日引けの30分前に取引実行
        if is_closing_time_range(30):
        # if is_closing_time_range(280):
            uptrend_stocks.update_trend_count(force=True)
            rebalance_portfolio()
            break

        if TEST_MODE:
            test_datetime += timedelta(minutes=30)
        else:
            # 1分ごとに市場時間をチェック
            time.sleep(60)


if __name__ == "__main__":
    # now = datetime.now()
    # now = now.replace(hour=13, minute=00, second=0, microsecond=0) - timedelta(minutes=30)
    # test_datetime = pd.Timestamp(now.astimezone(TZ_NY)) - timedelta(days=1690)
    # rebalance_portfolio()
#    for symbol in dividend_symbols:
#        print(symbol)
#        print(get_rsi(symbol))
    run_daily_trading()

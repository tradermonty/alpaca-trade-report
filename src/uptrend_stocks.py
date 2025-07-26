import argparse
import datetime
import requests
import pandas as pd
import io
import time
from datetime import timedelta
from zoneinfo import ZoneInfo
import os
from dotenv import load_dotenv

from api_clients import get_alpaca_client

import gspread
from oauth2client.service_account import ServiceAccountCredentials

load_dotenv()

# API クライアント初期化
alpaca_client = get_alpaca_client('live')


# FinvizのAPIキー設定
FINVIZ_API_KEY = os.getenv('FINVIZ_API_KEY')

# Finvizリトライ設定
FINVIZ_MAX_RETRIES = 5  # 最大リトライ回数
FINVIZ_RETRY_WAIT = 1   # 初回リトライ待機時間（秒）

UPTREND_SCREENER = f"https://elite.finviz.com/export.ashx?v=151&f=cap_microover,sh_avgvol_o100,sh_price_o10," \
                   f"ta_highlow52w_a30h,ta_perf2_4wup,ta_sma20_pa,ta_sma200_pa," \
                   f"ta_sma50_sa200&ft=4&o=-epsyoy1&ar=60&c=0,1,2,79,3,4,5,6,7,8,9,10,11,12,13,73,74,75,14,15,16,77," \
                   f"17,18,19,20,21,23,22,82,78,127,128,24,25,85,26,27,28,29,30,31,84,32,33,34,35,36,37,38,39,40,41," \
                   f"90,91,92,93,94,95,96,97,98,99,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,125,126,59,68," \
                   f"70,80,83,76,60,61,62,63,64,67,89,69,81,86,87,88,65,66,71,72,103,100,101,104,102,106,107,108,109," \
                   f"110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,105&auth={FINVIZ_API_KEY} "

TOTAL_SCREENER = f"https://elite.finviz.com/export.ashx?v=151&f=cap_microover,sh_avgvol_o100," \
                 f"sh_price_o10&ft=4&o=-epsyoy1&ar=60&c=0,1,2,79,3,4,5,6,7,8,9,10,11,12,13,73,74,75,14,15,16,77,17," \
                 f"18,19,20,21,23,22,82,78,127,128,24,25,85,26,27,28,29,30,31,84,32,33,34,35,36,37,38,39,40,41,90,91," \
                 f"92,93,94,95,96,97,98,99,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,125,126,59,68,70,80,83," \
                 f"76,60,61,62,63,64,67,89,69,81,86,87,88,65,66,71,72,103,100,101,104,102,106,107,108,109,110,111," \
                 f"112,113,114,115,116,117,118,119,120,121,122,123,124,105&auth={FINVIZ_API_KEY} "

TZ_NY = ZoneInfo("US/Eastern")
TZ_UTC = ZoneInfo('UTC')

COL_COUNT = "B"  # Count
COL_RATIO = "D"  # Ratio
COL_TREND_UP = "F"  # Trand up ratio
COL_TREND_DOWN = "G"  # Trand down ratio
COL_UPPER = "H"  # Upper ratio
COL_LOWER = "I"  # Lower ratio
COL_LONG_SIGNAL = "Q"  # Long Signal
COL_SHORT_SIGNAL = "W"  # Short Signal
COL_SLOPE = "K"  # Slope

api = alpaca_client.api  # 後方互換性のため

# def open_gspreadsheet(sheet_name):
#     # Google Drive APIと連携するためのクライアントを作成
#     scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
#     creds = ServiceAccountCredentials.from_json_keyfile_name(
#         '../config/spreadsheetautomation-430123-8795f1278b02.json', scope)
#     client = gspread.authorize(creds)
#
#     # Google Sheetsを開く
#     sheet = client.open(sheet_name).sheet1
#
#     return sheet

# Google Drive APIと連携するためのクライアントを作成
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(
    '../config/spreadsheetautomation-430123-8795f1278b02.json', scope)
client = gspread.authorize(creds)

# Google Sheetsを開く
max_retries = 5
attempt = 0
sheet = None

while attempt < max_retries:
    try:
        sheet = client.open("US Market - Uptrend Stocks").worksheet("all")
        break

    except Exception as error:
        attempt += 1
        print(datetime.datetime.now().astimezone(TZ_NY),
              "failed to open spreadsheet.", error)
        if attempt == max_retries:
            print("reached maximum retries. Continuing without spreadsheet access.")
            sheet = None
        else:
            time.sleep(10)


def number_of_stocks(url):
    row_count = 0

    retries = 0
    while retries < FINVIZ_MAX_RETRIES:
        resp = requests.get(url)

        if resp.status_code == 200:
            df = pd.read_csv(io.BytesIO(resp.content), sep=",")
            row_count = len(df)
            break

        elif resp.status_code == 429:
            retries += 1
            wait_time = FINVIZ_RETRY_WAIT * (2 ** (retries - 1))
            print(f"Rate limit exceeded. Retrying in {wait_time} seconds...")
            time.sleep(wait_time)

        else:
            print(f"Error fetching data from Finviz. Status code: {resp.status_code}")
            break

    return row_count


def is_closing_time_range(range_minutes=1):
    current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))

    cal = api.get_calendar(start=str(current_dt.date()), end=str(current_dt.date()))
    if len(cal) > 0:
        close_time = cal[0].close
        close_dt = pd.Timestamp(str(current_dt.date()) + " " + str(close_time), tz=TZ_NY)
    else:
        print("market will not open on the date.")
        return

    if close_dt - timedelta(minutes=range_minutes) <= current_dt < close_dt:
        print("past closing time")
        return True
    else:
        print(current_dt, "it's not in closing time range")
        return False


def sleep_until_next_close(time_to_minutes=1):
    market_dt = datetime.date.today()

    days = 1

    cal = api.get_calendar(start=str(market_dt), end=str(market_dt))

    while True:
        if len(cal) == 0:
            market_dt += timedelta(days=days)
            cal = api.get_calendar(start=str(market_dt), end=str(market_dt))
            days += 1
        else:
            close_time = cal[0].close
            current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))

            next_close_dt = pd.Timestamp(str(market_dt) + " " + str(close_time), tz=TZ_NY)

            if current_dt > next_close_dt:
                market_dt += timedelta(days=days)
                cal = api.get_calendar(start=str(market_dt), end=str(market_dt))
                days += 1
            else:
                while True:
                    if next_close_dt > current_dt + timedelta(minutes=time_to_minutes):
                        print("time to next close", next_close_dt - current_dt)
                        time.sleep(60)
                    else:
                        print(current_dt, "close time reached.")
                        break

                    current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))
                break


def update_trend_count(force=False):

    weekday = True
    ap = argparse.ArgumentParser()
    ap.add_argument('--close_time_range', default=5)
    args = vars(ap.parse_args())

    close_time_range = args['close_time_range']

    cal = api.get_calendar(start=str(datetime.date.today()), end=str(datetime.date.today()))
    if len(cal) <= 0:
        print("market will not open today.")
        weekday = False
        return

    if force:
        print("execute update")
    else:
        print("wait for time to close")
        while weekday:
            sleep_until_next_close(time_to_minutes=close_time_range)
            if is_closing_time_range(range_minutes=close_time_range):
                break

    # finviz APIで上昇トレンドの銘柄数を取得
    uptrend_count = number_of_stocks(UPTREND_SCREENER)
    total_count = number_of_stocks(TOTAL_SCREENER)

    # # Google Drive APIと連携するためのクライアントを作成
    # scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    # creds = ServiceAccountCredentials.from_json_keyfile_name(
    #     '../config/spreadsheetautomation-430123-8795f1278b02.json', scope)
    # client = gspread.authorize(creds)
    #
    # # Google Sheetsを開く
    # sheet = client.open("Minervini_template_numbers").sheet1

    # sheet = open_gspreadsheet("Minervini_template_numbers")

    # シートからすべてのレコードを取得
    data = sheet.get_all_records()

    # 'Date'列で今日の日付を検索し、対応する行番号を取得
    today = datetime.datetime.now().strftime("%-m/%-d/%Y")
    row_to_update = None

    for i, record in enumerate(data):
        if str(record['Date']) == today:
            row_to_update = i + 2  # gspreadのインデックスは1から始まるので、ヘッダ行の分を加算
            break

    if row_to_update is None:
        print("シートに今日の日付が見つかりませんでした。")
        for i, record in enumerate(data):
            if str(record['Date']) == "":
                row_to_update = i + 2  # gspreadのインデックスは1から始まるので、ヘッダ行の分を加算
                sheet.update_cell(row_to_update, 1, today)  # 'Date'が1列目の場合
                break

    # 'Count', 'Total' 列を更新
    sheet.update_cell(row_to_update, 2, uptrend_count)  # 'Count'が2列目の場合
    sheet.update_cell(row_to_update, 3, total_count)  # 'Total'が3列目の場合
    print(f"行 {row_to_update} を値 {uptrend_count} で更新しました。")


def is_uptrend(date=None):
    row_to_update = None
    # sheet = open_gspreadsheet("Minervini_template_numbers")
    if sheet is None:
        return False

    data = sheet.get_all_records()

    if date is None:
        date = datetime.datetime.now().strftime("%-m/%-d/%Y")

    for i, record in enumerate(data):
        if str(record['Date']) == date:
            row_to_update = i + 2  # gspreadのインデックスは1から始まるので、ヘッダ行の分を加算
            break

    if row_to_update is None:
        print("Unable to get today's data.")
        return False

    count = sheet.get(COL_COUNT + str(row_to_update))[0]
    if count:
        count = count[0]
    else:
        count = ""

    if count == "":
        row_to_update -= 1

    trend_up = sheet.get(COL_TREND_UP + str(row_to_update))[0]
    if trend_up:
        trend_up = trend_up[0]
    else:
        trend_up = ""

    if trend_up != "":
        return True

    return False


def is_downtrend(date=None):
    row_to_update = None
    # sheet = open_gspreadsheet("Minervini_template_numbers")
    if sheet is None:
        return False

    data = sheet.get_all_records()

    if date is None:
        date = datetime.datetime.now().strftime("%-m/%-d/%Y")
    else:
        date = date.strftime("%-m/%-d/%Y")

    for i, record in enumerate(data):
        if str(record['Date']) == date:
            row_to_update = i + 2  # gspreadのインデックスは1から始まるので、ヘッダ行の分を加算
            break

    if row_to_update is None:
        print("Unable to get data.")
        return False

    count = sheet.get(COL_COUNT + str(row_to_update))[0]
    if count:
        count = count[0]
    else:
        count = ""

    if count == "":
        row_to_update -= 1

    trend = sheet.get(COL_TREND_DOWN + str(row_to_update))[0]
    if trend:
        trend = trend[0]
    else:
        trend = ""

    if trend != "":
        return True

    return False


def is_overbought(check_prev=False):
    row_to_update = None
    # sheet = open_gspreadsheet("Minervini_template_numbers")
    if sheet is None:
        return False

    data = sheet.get_all_records()

    today = datetime.datetime.now().strftime("%-m/%-d/%Y")

    for i, record in enumerate(data):
        if str(record['Date']) == today:
            row_to_update = i + 2  # gspreadのインデックスは1から始まるので、ヘッダ行の分を加算
            break

    if row_to_update is None:
        print("Unable to get today's data.")
        return False

    count = sheet.get(COL_COUNT + str(row_to_update))[0]
    if count:
        count = count[0]
    else:
        count = ""

    if count == "":
        row_to_update -= 1

    ratio = sheet.get(COL_RATIO + str(row_to_update))[0]
    if ratio:
        ratio = float(ratio[0].replace('%', ''))
    else:
        ratio = 0

    upper = sheet.get(COL_UPPER + str(row_to_update))[0]
    if upper:
        upper = float(upper[0].replace('%', ''))
    else:
        upper = 0

    if check_prev:
        ratio_prev = sheet.get(COL_RATIO + str(row_to_update - 1))[0]
        if ratio_prev:
            ratio_prev = float(ratio_prev[0].replace('%', ''))
        else:
            ratio_prev = 0

        if ratio >= upper > ratio_prev:
            return True

    else:
        if ratio >= upper:
            return True

    return False


def is_oversold(check_prev=False):
    row_to_update = None

    # sheet = open_gspreadsheet("Minervini_template_numbers")
    if sheet is None:
        return False

    data = sheet.get_all_records()

    today = datetime.datetime.now().strftime("%-m/%-d/%Y")

    for i, record in enumerate(data):
        if str(record['Date']) == today:
            row_to_update = i + 2  # gspreadのインデックスは1から始まるので、ヘッダ行の分を加算
            break

    if row_to_update is None:
        print("Unable to get today's data.")
        return False

    count = sheet.get(COL_COUNT + str(row_to_update))[0]
    if count:
        count = count[0]
    else:
        count = ""

    if count == "":
        row_to_update -= 1

    ratio = sheet.get(COL_RATIO + str(row_to_update))[0]
    if ratio:
        ratio = float(ratio[0].replace('%', ''))
    else:
        ratio = 0

    lower = sheet.get(COL_LOWER + str(row_to_update))[0]
    if lower:
        lower = float(lower[0].replace('%', ''))
    else:
        lower = 0

    if check_prev:
        ratio_prev = sheet.get(COL_RATIO + str(row_to_update - 1))[0]
        if ratio_prev:
            ratio_prev = float(ratio_prev[0].replace('%', ''))
        else:
            ratio_prev = 0

        if ratio <= lower < ratio_prev:
            return True

    else:
        if ratio <= lower:
            return True

    return False


def get_long_signal():
    row_to_update = None
    signal = ""

    # sheet = open_gspreadsheet("Minervini_template_numbers")
    if sheet is None:
        return signal

    data = sheet.get_all_records()

    today = datetime.datetime.now().strftime("%-m/%-d/%Y")

    for i, record in enumerate(data):
        if str(record['Date']) == today:
            row_to_update = i + 2
            break

    if row_to_update is None:
        print("Unable to get today's data.")
        return signal

    count = sheet.get(COL_COUNT + str(row_to_update))[0]
    if count:
        count = count[0]
    else:
        count = ""

    if count == "":
        row_to_update -= 1

    signal = sheet.get(COL_LONG_SIGNAL + str(row_to_update))[0]
    if signal:
        signal = signal[0]
    else:
        signal = ""

    # if the market closed on one day prior, check signal on the day
    # if signal == "":
    #     days = 1
    #     while True:
    #         cal = api.get_calendar(start=str(datetime.date.today() - timedelta(days=days)),
    #                               end=str(datetime.date.today() - timedelta(days=days)))
    #         if len(cal) <= 0:
    #             signal = sheet.get(COL_LONG_SIGNAL + str(row_to_update - days))[0]
    #             if signal:
    #                 signal = signal[0]
    #                 break
    #             else:
    #                 days += 1
    #         else:
    #             signal = ""
    #             break

    return signal


def get_short_signal():
    row_to_update = None
    signal = ""

    # sheet = open_gspreadsheet("Minervini_template_numbers")
    if sheet is None:
        return signal

    data = sheet.get_all_records()

    today = datetime.datetime.now().strftime("%-m/%-d/%Y")

    for i, record in enumerate(data):
        if str(record['Date']) == today:
            row_to_update = i + 2
            break

    if row_to_update is None:
        print("Unable to get today's data.")
        return signal

    count = sheet.get(COL_COUNT + str(row_to_update))[0]
    if count:
        count = count[0]
    else:
        count = ""

    if count == "":
        row_to_update -= 1

    signal = sheet.get(COL_SHORT_SIGNAL + str(row_to_update))[0]
    if signal:
        signal = signal[0]
    else:
        signal = ""

    # if the market closed on one day prior, check signal on the day
    # days = 1
    # if signal == "":
    #     while True:
    #         cal = api.get_calendar(start=str(datetime.date.today() - timedelta(days=days)),
    #                               end=str(datetime.date.today() - timedelta(days=days)))
    #         if len(cal) <= 0:
    #             signal = sheet.get(COL_SHORT_SIGNAL + str(row_to_update - days))[0]
    #             if signal:
    #                 signal = signal[0]
    #                 break
    #             else:
    #                 days += 1
    #         else:
    #             signal = ""
    #             break

    return signal


def get_slope(date=""):
    row_to_update = None
    slope = 0
    if sheet is None:
        return slope

    data = sheet.get_all_records()

    if date == "":
        date = datetime.datetime.now().strftime("%-m/%-d/%Y")
    elif type(date) is not str:
        date = date.strftime("%-m/%-d/%Y")

    for i, record in enumerate(data):
        if str(record['Date']) == date:
            row_to_update = i + 2  # gspreadのインデックスは1から始まるので、ヘッダ行の分を加算
            slope = sheet.get(COL_SLOPE + str(row_to_update))[0]
            if slope:
                slope = float(slope[0])
            break

    return slope


def get_ratio(date=""):
    row_to_update = None
    ratio = 0
    if sheet is None:
        return ratio

    data = sheet.get_all_records()

    if date == "":
        date = datetime.datetime.now().strftime("%-m/%-d/%Y")
    elif type(date) is not str:
        date = date.strftime("%-m/%-d/%Y")

    for i, record in enumerate(data):
        if str(record['Date']) == date:
            row_to_update = i + 2  # gspreadのインデックスは1から始まるので、ヘッダ行の分を加算
            ratio = sheet.get(COL_RATIO + str(row_to_update))[0]
            if ratio:
                ratio = float(ratio[0].replace('%', '')) / 100.0
            break

    return ratio


if __name__ == '__main__':
    # print("Uptrend", is_uptrend())
    # print("Downtrend", is_downtrend())
    # print("Overbought", is_overbought(check_prev=True))
    # print("Oversold", is_oversold(check_prev=True))
    # print("Long signal", get_long_signal())
    # print("Short signal", get_short_signal())
    # print("slope", get_slope(datetime.datetime.today()))

    update_trend_count()

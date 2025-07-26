import argparse
import datetime
import requests
import pandas as pd
import io
import time
from datetime import timedelta
import os
from dotenv import load_dotenv

from api_clients import get_alpaca_client, get_finviz_client

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from common_constants import TIMEZONE
load_dotenv()

sectors =[
    "sec_basicmaterials",
    "sec_communicationservices",
    "sec_consumercyclical",
    "sec_consumerdefensive",
    "sec_energy",
    "sec_financial",
    "sec_healthcare",
    "sec_industrials",
    "sec_realestate",
    "sec_technology",
    "sec_utilities"
]

industries = [
    "ind_advertisingagencies",
    "ind_aerospacedefense",
    "ind_agriculturalinputs",
    "ind_airlines",
    "ind_airportsairservices",
    "ind_aluminum",
    "ind_apparelmanufacturing",
    "ind_apparelretail",
    "ind_assetmanagement",
    "ind_automanufacturers",
    "ind_autoparts",
    "ind_autotruckdealerships",
    "ind_banksdiversified",
    "ind_banksregional",
    "ind_beveragesbrewers",
    "ind_beveragesnonalcoholic",
    "ind_beverageswineriesdistilleries",
    "ind_biotechnology",
    "ind_broadcasting",
    "ind_buildingmaterials",
    "ind_buildingproductsequipment",
    "ind_businessequipmentsupplies",
    "ind_capitalmarkets",
    "ind_chemicals",
    "ind_closedendfunddebt",
    "ind_closedendfundequity",
    "ind_closedendfundforeign",
    "ind_cokingcoal",
    "ind_communicationequipment",
    "ind_computerhardware",
    "ind_confectioners",
    "ind_conglomerates",
    "ind_consultingservices",
    "ind_consumerelectronics",
    "ind_copper",
    "ind_creditservices",
    "ind_departmentstores",
    "ind_diagnosticsresearch",
    "ind_discountstores",
    "ind_drugmanufacturersgeneral",
    "ind_drugmanufacturersspecialtygeneric",
    "ind_educationtrainingservices",
    "ind_electricalequipmentparts",
    "ind_electroniccomponents",
    "ind_electronicgamingmultimedia",
    "ind_electronicscomputerdistribution",
    "ind_engineeringconstruction",
    "ind_entertainment",
    "ind_exchangetradedfund",
    "ind_farmheavyconstructionmachinery",
    "ind_farmproducts",
    "ind_financialconglomerates",
    "ind_financialdatastockexchanges",
    "ind_fooddistribution",
    "ind_footwearaccessories",
    "ind_furnishingsfixturesappliances",
    "ind_gambling",
    "ind_gold",
    "ind_grocerystores",
    "ind_healthcareplans",
    "ind_healthinformationservices",
    "ind_homeimprovementretail",
    "ind_householdpersonalproducts",
    "ind_industrialdistribution",
    "ind_informationtechnologyservices",
    "ind_infrastructureoperations",
    "ind_insurancebrokers",
    "ind_insurancediversified",
    "ind_insurancelife",
    "ind_insurancepropertycasualty",
    "ind_insurancereinsurance",
    "ind_insurancespecialty",
    "ind_integratedfreightlogistics",
    "ind_internetcontentinformation",
    "ind_internetretail",
    "ind_leisure",
    "ind_lodging",
    "ind_lumberwoodproduction",
    "ind_luxurygoods",
    "ind_marineshipping",
    "ind_medicalcarefacilities",
    "ind_medicaldevices",
    "ind_medicaldistribution",
    "ind_medicalinstrumentssupplies",
    "ind_metalfabrication",
    "ind_mortgagefinance",
    "ind_oilgasdrilling",
    "ind_oilgasep",
    "ind_oilgasequipmentservices",
    "ind_oilgasintegrated",
    "ind_oilgasmidstream",
    "ind_oilgasrefiningmarketing",
    "ind_otherindustrialmetalsmining",
    "ind_otherpreciousmetalsmining",
    "ind_packagedfoods",
    "ind_packagingcontainers",
    "ind_paperpaperproducts",
    "ind_personalservices",
    "ind_pharmaceuticalretailers",
    "ind_pollutiontreatmentcontrols",
    "ind_publishing",
    "ind_railroads",
    "ind_realestatedevelopment",
    "ind_realestatediversified",
    "ind_realestateservices",
    "ind_recreationalvehicles",
    "ind_reitdiversified",
    "ind_reithealthcarefacilities",
    "ind_reithotelmotel",
    "ind_reitindustrial",
    "ind_reitmortgage",
    "ind_reitoffice",
    "ind_reitresidential",
    "ind_reitretail",
    "ind_reitspecialty",
    "ind_rentalleasingservices",
    "ind_residentialconstruction",
    "ind_resortscasinos",
    "ind_restaurants",
    "ind_scientifictechnicalinstruments",
    "ind_securityprotectionservices",
    "ind_semiconductorequipmentmaterials",
    "ind_semiconductors",
    "ind_shellcompanies",
    "ind_silver",
    "ind_softwareapplication",
    "ind_softwareinfrastructure",
    "ind_solar",
    "ind_specialtybusinessservices",
    "ind_specialtychemicals",
    "ind_specialtyindustrialmachinery",
    "ind_specialtyretail",
    "ind_staffingemploymentservices",
    "ind_steel",
    "ind_telecomservices",
    "ind_textilemanufacturing",
    "ind_thermalcoal",
    "ind_tobacco",
    "ind_toolsaccessories",
    "ind_travelservices",
    "ind_trucking",
    "ind_uranium",
    "ind_utilitiesdiversified",
    "ind_utilitiesindependentpowerproducers",
    "ind_utilitiesregulatedelectric",
    "ind_utilitiesregulatedgas",
    "ind_utilitiesregulatedwater",
    "ind_utilitiesrenewable",
    "ind_wastemanagement"
]

# Alpaca API credentials for live account
# API クライアント初期化
alpaca_client = get_alpaca_client('live')
finviz_client = get_finviz_client()

TZ_NY = TIMEZONE.NY  # Migrated from common_constants
TZ_UTC = TIMEZONE.UTC  # Migrated from common_constants

api = alpaca_client.api  # 後方互換性のため


def number_of_stocks(sector):
    """指定されたセクターの銘柄数を取得"""
    uptrend_url = finviz_client.get_uptrend_screener_url(sector)
    total_url = finviz_client.get_total_screener_url(sector)
    
    uptrend_count = finviz_client.get_stock_count(uptrend_url)
    total_count = finviz_client.get_stock_count(total_url)
    
    return uptrend_count, total_count


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


def update_trend_count():

    weekday = True
    ap = argparse.ArgumentParser()
    ap.add_argument('--close_time_range', default=3)
    args = vars(ap.parse_args())

    close_time_range = args['close_time_range']

    cal = api.get_calendar(start=str(datetime.date.today()), end=str(datetime.date.today()))
    if len(cal) <= 0:
        print("market will not open today.")
        weekday = False
        return

    while weekday:
        sleep_until_next_close(time_to_minutes=close_time_range)
        if is_closing_time_range(range_minutes=close_time_range):
            break

    for sector in sectors:
        time.sleep(1)
        uptrend_count, total_count = number_of_stocks(sector)
        if total_count > 0:
            ratio = uptrend_count/total_count
        else:
            ratio = 0
        print(sector, uptrend_count, total_count, f"{ratio:.2%}")

        # Google Drive APIと連携するためのクライアントを作成
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            '../config/spreadsheetautomation-430123-8795f1278b02.json', scope)
        client = gspread.authorize(creds)

        # Google Sheetsを開く
        sheet = client.open("US Market - Uptrend Stocks").worksheet(sector)

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

    # for industry in industries:
    #     time.sleep(1)
    #     uptrend_count = number_of_stocks(UPTREND_SCREENER.replace("[SECTOR]", industry))
    #     time.sleep(1)
    #     total_count = number_of_stocks(TOTAL_SCREENER.replace("[SECTOR]", industry))
    #     if total_count > 0:
    #         ratio = uptrend_count/total_count
    #     else:
    #         ratio = 0
    #
    #     print(industry, uptrend_count, total_count, f"{ratio:.2%}")


if __name__ == '__main__':
    update_trend_count()

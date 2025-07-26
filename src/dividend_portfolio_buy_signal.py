from datetime import datetime, timedelta, timezone
import talib as ta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import pandas as pd
from alpaca_trade_api.rest import TimeFrame, TimeFrameUnit
from api_clients import get_alpaca_client
import pytz
from dotenv import load_dotenv
import os

# 環境変数の読み込み
load_dotenv()
GMAIL_PASSWORD = os.getenv('GMAIL_PASSWORD')

# タイムゾーンの設定
TZ_NY = pytz.timezone('America/New_York')

# API クライアント初期化
alpaca_client = get_alpaca_client('live')  # Default to live account
api = alpaca_client.api  # 後方互換性のため

# log
ENTRY_SIGNAL_LOG_FILE = "entry_signals_log.csv"

# ポートフォリオ銘柄のリスト
symbols = ['AAPL', 'ABBV', 'ABT', 'ACN', 'ADM', 'ADP', 'AFL', 'AMAT', 'AMGN', 'AMP', 'AOS',
           'ARCC', 'AVGO', 'BBY', 'BMY', 'BLK', 'BR', 'CDW', 'COST', 'CTAS', 'CVX', 'DHI',
           'DKS', 'DPZ', 'DRI', 'EQR', 'FAST', 'GES', 'GOOG', 'GS', 'HD', 'HSY', 'JPM', 'KO', 'KR',
           'LEN', 'LMT', 'MAS', 'MCD', 'MCO', 'MDT', 'MMC', 'MO', 'MS', 'MSCI', 'MSFT', 'NDSN', 'NEE',
           'NXST', 'O', 'OC', 'OKE', 'OZK', 'PAYX', 'PEP', 'PG', 'PH', 'RF', 'RJF', 'ROL', 'SBUX',
           'SNA', 'SPGI', 'SWKS', 'SYK', 'TGT', 'TMUS', 'TROW', 'TXN', 'TXRH', 'UNH', 'USB', 'V',
           'VICI', 'WM', 'WSM', 'WSO', 'XOM', 'ZTS', 'JNJ', 'TRV']

# 閾値の設定
deviation_threshold = 5  # 乖離率の閾値 (%)
rsi_min_threshold = 37  # RSIの最小値の閾値
lookback_period = 14  # RSI計算期間
rsi_slope_lookback = 3  # RSIの傾き確認期間
recent_period = (datetime.now(TZ_NY) - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


# ログファイルにデータを書き込む関数
def log_entry(symbol, data):
    with open(ENTRY_SIGNAL_LOG_FILE, "a") as log_file:
        log_file.write(f"Date: {datetime.now()}, Symbol: {symbol}\n")
        log_file.write(data.to_csv())
        log_file.write("\n")


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

        print("Email sent successfully!")

    except Exception as e:
        print(f"Failed to send email. Error: {e}")


# 200日移動平均との乖離率を計算する関数
def calculate_deviation_from_ma(df, ma_period=200):
    df['MA'] = df['Close'].rolling(window=ma_period).mean()
    df['Deviation'] = (df['Close'] - df['MA']) / df['MA'] * 100
    return df


# 週足の200日移動平均が上向きかを確認する関数
def is_weekly_ma_upward(symbol):
    # 週足データを取得
    weekly_data = yf.download(symbol, period='5y', interval='1wk')

    # 200週移動平均を計算
    weekly_data['MA_200w'] = weekly_data['Close'].rolling(window=200).mean()

    # 直近2週間で200週移動平均線の傾きがプラスであることを確認
    if len(weekly_data) > 200:
        slope = weekly_data['MA_200w'].iloc[-1] - weekly_data['MA_200w'].iloc[-2]
        return slope > 0
    return False


# 銘柄ごとの条件を満たすかを確認する関数
def check_entry_conditions(symbol, deviation_threshold, rsi_min_threshold, lookback_period):
    try:
        # 現在の日時（NY時間）を取得
        current_dt = pd.Timestamp(datetime.now().astimezone(TZ_NY))
        # 200日移動平均の計算に必要な過去データを確保するため、期間を延長
        start_dt = current_dt - timedelta(days=400)  # 200日MAの計算のため、余裕を持って400日分取得
        
        # 株価データを取得
        bars = api.get_bars(
            symbol,
            TimeFrame(1, TimeFrameUnit.Day),
            start=start_dt.strftime("%Y-%m-%d"),
            end=current_dt.strftime("%Y-%m-%d")
        ).df
        
        # 取得したDataFrameを時系列順にソート
        bars = bars.sort_index()
        
        # データ数の確認を追加
        print(f"取得データ数: {len(bars)}日分")
        
        # 200日移動平均を計算
        bars['MA200'] = bars['close'].rolling(window=200).mean()
        bars['Deviation'] = (bars['close'] - bars['MA200']) / bars['MA200'] * 100
        
        # RSIを計算
        bars['RSI'] = ta.RSI(bars['close'].values, timeperiod=lookback_period)
        
        # 過去14日間の最小値を計算
        bars['Deviation_Min'] = bars['Deviation'].rolling(window=lookback_period).min()
        bars['RSI_Min'] = bars['RSI'].rolling(window=lookback_period).min()
        
        # RSIの傾きを確認
        bars['RSI_Change'] = bars['RSI'].diff(periods=rsi_slope_lookback)
        bars['RSI_Slope_Switch'] = (bars['RSI_Change'].shift(1) < 0) & (bars['RSI_Change'] > 0)
        
        # デバッグ用の出力を追加
        print(f"\n{symbol} の判定結果:")
        print("=== 直近5日間のデータ ===")
        debug_cols = ['close', 'MA200', 'Deviation', 'Deviation_Min', 'RSI', 'RSI_Min', 'RSI_Change', 'RSI_Slope_Switch']
        debug_data = bars[debug_cols].tail()
        
        # 最新日の条件チェック
        latest_data = debug_data.iloc[-1]
        deviation_check = latest_data['Deviation_Min'] < deviation_threshold
        rsi_check = latest_data['RSI_Min'] < rsi_min_threshold
        slope_check = latest_data['RSI_Slope_Switch']
        
        print("\n各指標の値:")
        print(f"現在値: ${latest_data['close']:.2f}")
        print(f"200日MA: ${latest_data['MA200']:.2f}")
        print(f"乖離率: {latest_data['Deviation']:.2f}%")
        print(f"乖離率の最小値: {latest_data['Deviation_Min']:.2f}% (閾値: {deviation_threshold}%)")
        print(f"RSI: {latest_data['RSI']:.2f}")
        print(f"RSIの最小値: {latest_data['RSI_Min']:.2f} (閾値: {rsi_min_threshold})")
        print(f"RSIの変化: {latest_data['RSI_Change']:.2f}")
        print(f"RSIの転換: {'はい' if slope_check else 'いいえ'}")
        
        print("\n条件チェック:")
        print(f"1. 乖離率が{deviation_threshold}%未満: {'○' if deviation_check else '×'}")
        print(f"2. RSIが{rsi_min_threshold}未満: {'○' if rsi_check else '×'}")
        print(f"3. RSIが上昇転換: {'○' if slope_check else '×'}")
        
        # 全ての条件を満たすかチェック
        all_conditions_met = deviation_check and rsi_check and slope_check
        
        # 直近期間のチェックを追加
        is_recent = bars.index[-1].tz_localize(None) >= recent_period.replace(tzinfo=None)
        
        if all_conditions_met and is_recent:
            print("\n🟢 エントリー条件を満たしました")
            print("\n詳細データ:")
            print(debug_data)
            log_entry(symbol, debug_data)
            return True
        else:
            if not is_recent:
                print("\n❌ 直近のデータではありません")
            else:
                print("\n❌ エントリー条件を満たしていません")
            return False
            
    except Exception as e:
        print(f"エラー ({symbol}): {str(e)}")
        return False


if __name__ == '__main__':
    buy_signals = []

    # 各銘柄のエントリー条件をチェック
    for symbol in symbols:
        if check_entry_conditions(symbol, deviation_threshold, rsi_min_threshold, lookback_period):
            buy_signals.append(symbol)

    # 買いシグナルが出た銘柄の年間株価推移を個別のチャートで表示
    if buy_signals:
        # シグナルが出た銘柄リストとFinvizリンクを作成
        message = "Signal detected for: \n"
        for signal in buy_signals:
            message += f"{signal}: https://elite.finviz.com/quote.ashx?t={signal}&p=d\n"

        print(message)

        try:
            # 現在の日付をYYYY-MM-DD形式で取得
            current_date = datetime.now().strftime("%Y-%m-%d")

            # Emailを送信
            send_email_via_gmail(f"Dividend stock buy signal - {current_date}", message,
                                 "taku.saotome@gmail.com", "taku.saotome@gmail.com",
                                 GMAIL_PASSWORD)
        except Exception as error:
            print("sending email failed.", error)

    else:
        print("買いシグナルが出た銘柄はありませんでした。")

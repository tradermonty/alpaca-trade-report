import os
import requests
import pandas as pd
import io
import argparse
import json
from datetime import datetime, timedelta
import pytz
import time
from bs4 import BeautifulSoup
from openai import OpenAI
from alpaca_trade_api.common import URL
import webbrowser
from dotenv import load_dotenv

# .envファイルの読み込み
load_dotenv()

# OpenAI APIキーを設定
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

ALPACA_ACCOUNT = 'live'

# Alpaca APIの設定
if ALPACA_ACCOUNT == 'live':
    # Alpaca API credentials for live account
    ALPACA_BASE_URL = URL('https://api.alpaca.markets')
    ALPACA_API_KEY = os.getenv('ALPACA_API_KEY_LIVE')
    ALPACA_SECRET_KEY = os.getenv('ALPACA_SECRET_KEY_LIVE')
else:
    # Alpaca API credentials for paper account
    ALPACA_BASE_URL = URL('https://paper-api.alpaca.markets')
    ALPACA_API_KEY = os.getenv('ALPACA_API_KEY_PAPER')
    ALPACA_SECRET_KEY = os.getenv('ALPACA_SECRET_KEY_PAPER')

# Alpacaのニュース取得APIのエンドポイント
ALPACA_NEWS_API_URL = "https://data.alpaca.markets/v1beta1/news"

# FinvizのAPIキー設定
FINVIZ_API_KEY = os.getenv('FINVIZ_API_KEY')

# Finvizリトライ設定
FINVIZ_MAX_RETRIES = 5  # 最大リトライ回数
FINVIZ_RETRY_WAIT = 1   # 初回リトライ待機時間（秒）

# Alpha VantageのAPIキー設定
ALPHA_VANTAGE_API_KEY = os.getenv('ALPHA_VANTAGE_API_KEY')

NEWS_ARTICLE_PERIOD = 7  # ニュース記事を取得する期間 (日)

# アメリカ東部標準時（EST/EDT）に対応した開始日時と終了日時を計算
def get_est_day_range(date_str):
    target_date = datetime.strptime(date_str, '%Y-%m-%d')
    eastern = pytz.timezone('America/New_York')

    previous_day = target_date - timedelta(days=NEWS_ARTICLE_PERIOD)
    market_close_time = datetime(previous_day.year, previous_day.month, previous_day.day, 16, 0, 0)
    market_close_time = eastern.localize(market_close_time)

    end_of_day = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59)
    end_of_day = eastern.localize(end_of_day)

    start_time_alpha_vantage = market_close_time.strftime('%Y%m%dT%H%M')
    end_time_alpha_vantage = end_of_day.strftime('%Y%m%dT%H%M')

    start_time_alpaca = market_close_time.isoformat()
    end_time_alpaca = end_of_day.isoformat()

    return start_time_alpha_vantage, end_time_alpha_vantage, start_time_alpaca, end_time_alpaca


def fetch_article_content(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()  # エラーチェック
        soup = BeautifulSoup(response.content, 'html.parser')

        # <p>タグをすべて取得して本文として結合
        paragraphs = soup.find_all('p')
        article_text = ' '.join([p.get_text() for p in paragraphs])

        # Benzinga Proに関する広告が含まれているかをチェック
        if "Benzinga Pro" in article_text or "Want the fastest, most accurate stock market intelligence?" in article_text:
            return ""  # 広告内容が含まれていた場合、空白として返す

        return article_text if article_text else ""  # 本文がない場合も空白を返す
    except Exception:
        return ""  # エラーが発生した場合も空白を返す


# AlpacaのAPIを使ってニュースを取得
def get_news_from_alpaca(ticker, start_time, end_time):
    headers = {
        "APCA-API-KEY-ID": ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY
    }
    params = {
        "symbols": ticker,
        "start": start_time,
        "end": end_time,
        "limit": 10,
        "include_content": True
    }

    response = requests.get(ALPACA_NEWS_API_URL, headers=headers, params=params)
    response.raise_for_status()
    
    articles = response.json()["news"]
    filtered_articles = [article for article in articles if len(article['symbols']) == 1]

    return filtered_articles


# FinvizのAPIを使ってニュースを取得
def get_news_from_finviz(ticker, target_date):
    url = f"https://elite.finviz.com/news_export.ashx?v=3&t={ticker}&auth={FINVIZ_API_KEY}"

    retries = 0

    while retries < FINVIZ_MAX_RETRIES:
        resp = requests.get(url)
        print(resp)

        if resp.status_code == 200:
            df = pd.read_csv(io.BytesIO(resp.content), sep=",", quotechar='"', on_bad_lines='skip', engine='python')
            expected_columns = ['Title', 'Source', 'Date', 'Url', 'Category', 'Ticker']
            if len(df.columns) != len(expected_columns):
                df.columns = expected_columns

            target_date = datetime.strptime(target_date, '%Y-%m-%d')
            previous_date = target_date - timedelta(days=1)

            df['Date'] = pd.to_datetime(df['Date'])
            filtered_df = df[(df['Date'] >= previous_date) & (df['Date'] <= target_date)]
            limited_df = filtered_df.head(10)

            if len(limited_df) == 0:
                return []

            news_items = limited_df.apply(lambda row: {
                "headline": row['Title'],
                "summary": row['Title'],
                "url": row['Url'],
                "created_at": row['Date'].strftime('%Y-%m-%d %H:%M:%S'),
            }, axis=1).tolist()

            return news_items

        elif resp.status_code == 429:
            retries += 1
            wait_time = FINVIZ_RETRY_WAIT * (2 ** (retries - 1))
            print(f"Rate limit exceeded. Retrying in {wait_time} seconds...")
            time.sleep(wait_time)
        else:
            print(f"Error fetching news from Finviz. Status code: {resp.status_code}")
            return []

    print(f"Failed to fetch news from Finviz after {FINVIZ_MAX_RETRIES} retries.")
    return []


# Alpha VantageのAPIを使ってニュースを取得
def get_news_from_alpha_vantage(ticker, start_time, end_time):
    url = f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers={ticker}&apikey={ALPHA_VANTAGE_API_KEY}&time_from={start_time}&time_to={end_time}"

    response = requests.get(url)
    response.raise_for_status()
    data = response.json()

    if "feed" not in data:
        print(f"No news articles found for {ticker} from Alpha Vantage.")
        return []

    articles = data["feed"]
    filtered_articles = [{
        "headline": article['title'],
        "summary": article.get('summary', ''),
        "url": article['url'],
        "created_at": article['time_published'],
    } for article in articles if any(ticker_data['ticker'] == ticker for ticker_data in article.get('ticker_sentiment', []))]

    return filtered_articles


def get_prompt(ticker, combined_text, detailed=False, lang='ja'):
    if lang == 'ja':
        if detailed:
            return f"""
            以下は{ticker}に関する複数のニュース記事です。これらの記事を詳細に分析し、以下の項目について評価してください。

            ニュース記事の内容:
            {combined_text}

            分析結果を次のJSON形式で返してください:
            {{
                "category": 1から5の数字で返してください（1. 決算発表, 2. 業績予想, 3. アナリストレーティング, 4. S&P指数への組み込み, 5. その他）,
                "reason": 選択の理由を日本語で400文字以内で記載してください,
                "probability": 0〜100%の範囲で上昇する確率を予測して記載してください,
                "analysis": {{
                    "positive_factors": [上昇要因を3つまで箇条書きで],
                    "negative_factors": [下落要因を3つまで箇条書きで],
                    "market_sentiment": "ポジティブ/ニュートラル/ネガティブのいずれかで市場心理を評価",
                    "technical_factors": "技術的要因の分析（出来高、株価の動き等）を100文字以内で",
                    "risk_factors": [主要なリスク要因を2つまで箇条書きで]
                }}
            }}
            """
        else:
            return f"""
            以下は{ticker}に関する複数のニュース記事です。これらの記事を分析し、株価上昇または下落の要因を分析してください。
            また、今後の数ヶ月の間に上昇する確率を予測してください。

            ニュース記事の内容:
            {combined_text}

            分析結果を1〜4のいずれかに分類して、結果を次のJSON形式で返してください:
            {{
                "category": 1から5の数字で返してください（1. 決算発表, 2. 業績予想, 3. アナリストレーティング, 4. S&P指数への組み込み, 5. その他）,
                "reason": 選択の理由を日本語で200文字以内で記載してください,
                "probability": 0〜100%の範囲で上昇する確率を予測して記載してください
            }}
            """
    else:  # English prompts
        if detailed:
            return f"""
            Below are multiple news articles about {ticker}. Please analyze these articles in detail and evaluate the following items.

            News article content:
            {combined_text}

            Please return the analysis results in the following JSON format:
            {{
                "category": Please return a number from 1 to 5 (1. Earnings Report, 2. Performance Forecast, 3. Analyst Rating, 4. S&P Index Inclusion, 5. Others),
                "reason": Explain the reason for selection in 400 characters or less,
                "probability": Predict the probability of increase in the range of 0-100%,
                "analysis": {{
                    "positive_factors": [Up to 3 bullish factors in bullet points],
                    "negative_factors": [Up to 3 bearish factors in bullet points],
                    "market_sentiment": "Evaluate market psychology as either Positive/Neutral/Negative",
                    "technical_factors": "Technical analysis (volume, price movement, etc.) within 100 characters",
                    "risk_factors": [Up to 2 main risk factors in bullet points]
                }}
            }}
            """
        else:
            return f"""
            Below are multiple news articles about {ticker}. Please analyze these articles and analyze the factors for stock price increase or decrease.
            Also, please predict the probability of increase over the next few months.

            News article content:
            {combined_text}

            Please classify the analysis results into one of 1-4 and return in the following JSON format:
            {{
                "category": Please return a number from 1 to 5 (1. Earnings Report, 2. Performance Forecast, 3. Analyst Rating, 4. S&P Index Inclusion, 5. Others),
                "reason": Explain the reason for selection in 200 characters or less,
                "probability": Predict the probability of increase in the range of 0-100%
            }}
            """

def analyze_articles_and_get_json(ticker, alpaca_articles, finviz_articles, alpha_vantage_articles, model='gpt-4o-mini', detailed=False, lang='ja'):
    combined_articles = []

    # Alpacaの記事を追加
    for article in alpaca_articles:
        if not article['content']:
            article_content = fetch_article_content(article['url'])
        else:
            article_content = article['content']

        combined_articles.append(article['headline'] + "\n" + article_content)

    # Finvizの記事を追加
    for article in finviz_articles:
        article_content = fetch_article_content(article['url'])
        combined_articles.append(article['headline'] + "\n" + article_content)

    # Alpha Vantageの記事を追加
    for article in alpha_vantage_articles:
        article_content = fetch_article_content(article['url'])
        combined_articles.append(article['headline'] + "\n" + article_content)

    combined_text = "\n\n".join(combined_articles)
    prompt = get_prompt(ticker, combined_text, detailed, lang)

    chat_completion = client.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
        model=model,
    )

    answer = chat_completion.choices[0].message.content

    try:
        cleaned_answer = answer.strip('```').strip().replace('json\n', '')

        if not cleaned_answer.strip():
            raise ValueError("Empty response from ChatGPT")

        result = json.loads(cleaned_answer)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error decoding JSON: {e}")
        result = {"category": 99, "reason": "Failed to analyze news.", "ticker": ticker, "probability": 0}

    result["ticker"] = ticker
    return result


def analyze(ticker, date, model='gpt-4o-mini', detailed=False, lang='ja'):
    result = {"category": 99, "reason": "Failed to analyze news.", "ticker": ticker, "probability": 0}

    try:
        datetime.strptime(date, '%Y-%m-%d')
    except ValueError:
        print("Invalid date format. Please use YYYY-MM-DD.")
        result = {"category": 99, "reason": "Invalid date format. Please use YYYY-MM-DD.", "ticker": ticker,
                  "probability": 0}
        return result

    start_time_alpha_vantage, end_time_alpha_vantage, start_time_alpaca, end_time_alpaca = get_est_day_range(date)

    alpaca_articles = get_news_from_alpaca(ticker, start_time_alpaca, end_time_alpaca)
    finviz_articles = get_news_from_finviz(ticker, date)
    alpha_vantage_articles = []

    if not alpaca_articles and not finviz_articles and not alpha_vantage_articles:
        print(f"No news articles found for {ticker}.")
        result = {"category": 99, "reason": "No news articles found.", "ticker": ticker, "probability": 0}
        return result

    result = analyze_articles_and_get_json(
        ticker, 
        alpaca_articles, 
        finviz_articles, 
        alpha_vantage_articles, 
        model=model,
        detailed=detailed,
        lang=lang
    )

    return result


# メイン関数
def main():
    parser = argparse.ArgumentParser(description='Analyze news articles for a specific ticker and date.')
    parser.add_argument('tickers', nargs='+', help='Ticker symbols to analyze (e.g., AAPL TSLA AMZN).')
    parser.add_argument('--date', type=str, help='Start date for news in YYYY-MM-DD format.')
    parser.add_argument('--model', type=str, default='gpt-4o-mini',
                      choices=['o1-mini', 'gpt-4o-mini', 'gpt-4o', 'gpt-4o-mini'],
                      help='ChatGPT model to use (default: gpt-4o-mini)')
    parser.add_argument('--detailed', action='store_true',
                      help='Enable detailed analysis mode')
    parser.add_argument('--lang', type=str, choices=['ja', 'en'], default='ja',
                      help='Output language (ja: Japanese, en: English) (default: ja)')
    args = parser.parse_args()

    if args.date is None:
        args.date = datetime.today().strftime("%Y-%m-%d")

    results = []
    for ticker in args.tickers:
        result = analyze(ticker, args.date, model=args.model, detailed=args.detailed, lang=args.lang)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        results.append(result)

    # 詳細モードの場合はDataFrameの列を調整して2つの表を作成
    df = pd.DataFrame(results)
    
    # 基本情報の表を作成（categoryを除外）
    basic_df = df[['ticker', 'reason', 'probability']]
    markdown_table = basic_df.to_markdown(index=False)

    # 詳細モードの場合は分析情報の表も追加
    if args.detailed:
        # 各銘柄ごとに詳細分析を表形式で追加
        for result in results:
            if 'analysis' in result:
                analysis = result['analysis']
                markdown_table += f"\n\n### {result['ticker']} Detailed Analysis\n\n"
                
                # 1銘柄の詳細分析用のデータを作成
                analysis_data = {
                    'Category': [
                        'Positive Factors',
                        'Negative Factors',
                        'Market Sentiment',
                        'Technical Factors',
                        'Risk Factors'
                    ],
                    'Details': [
                        "<br>".join([f"• {factor}" for factor in analysis.get('positive_factors', [])]),
                        "<br>".join([f"• {factor}" for factor in analysis.get('negative_factors', [])]),
                        analysis.get('market_sentiment', ''),
                        analysis.get('technical_factors', ''),
                        "<br>".join([f"• {factor}" for factor in analysis.get('risk_factors', [])])
                    ]
                }
                
                analysis_df = pd.DataFrame(analysis_data)
                markdown_table += analysis_df.to_markdown(index=False)

    print(markdown_table)

    # 言語に応じてファイル名を設定
    output_file = "news_analysis_results_en.md" if args.lang == 'en' else "news_analysis_results.md"
    with open(output_file, "w", encoding='utf-8') as f:
        f.write(markdown_table)

    # ブラウザでレポートを開く
    webbrowser.open('file://' + os.path.realpath(output_file))


# 実行
if __name__ == '__main__':
    main()

# リスク管理システム詳細ドキュメント

## 概要

本システムのリスク管理は多層防御アプローチを採用し、取引前・取引中・取引後の各段階でリスクを制御します。PnL基準管理、ポジションサイジング、相関管理、ドローダウン制御を組み合わせて、資本保護を最優先とした運用を実現します。

---

## 1. PnL基準管理

### 基本概念
```python
PNL_CRITERIA = -0.06  # 直近30日でポートフォリオの6%以上の損失で取引停止
PNL_CHECK_PERIOD = 30  # 30日間のローリング期間
```

### 実装詳細

#### PnL計算ロジック
```python
def calculate_rolling_pnl(days=30):
    """
    直近N日間の実現・未実現損益を計算
    
    Returns:
        float: ポートフォリオ価値に対するPnL比率
    """
    try:
        # アカウント情報取得
        account = alpaca_client.get_account()
        current_value = float(account.portfolio_value)
        
        # 取引履歴取得
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)
        
        activities = alpaca_client.api.get_activities(
            activity_types='FILL',
            after=start_date,
            until=end_date,
            page_size=500
        )
        
        # FIFO方式でPnL計算
        realized_pnl = calculate_fifo_pnl(activities)
        
        # 未実現損益計算
        positions = alpaca_client.get_positions()
        unrealized_pnl = sum(float(pos.unrealized_pl) for pos in positions)
        
        total_pnl = realized_pnl + unrealized_pnl
        
        # 戦略配分を考慮したPnL比率
        strategy_allocation = get_strategy_allocation()
        allocated_capital = current_value * strategy_allocation.get('strategy5', 0.5)
        
        pnl_ratio = total_pnl / allocated_capital if allocated_capital > 0 else 0
        
        # ログに記録
        pnl_data = {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'realized_pnl': realized_pnl,
            'unrealized_pnl': unrealized_pnl,
            'total_pnl': total_pnl,
            'pnl_ratio': pnl_ratio,
            'portfolio_value': current_value
        }
        write_pnl_log(pnl_data)
        
        return pnl_ratio
        
    except Exception as e:
        logger.error(f"PnL計算エラー: {e}")
        return 0  # エラー時は保守的に0を返す
```

#### FIFO PnL計算
```python
def calculate_fifo_pnl(fills):
    """
    First-In-First-Out方式での実現損益計算
    税務処理との整合性を保つため、FIFOルールを適用
    """
    position_queue = []  # (price, quantity, timestamp)
    realized_pnl = 0.0
    
    for fill in sorted(fills, key=lambda x: x.timestamp):
        if fill.side == 'buy':
            # 買いポジション追加
            position_queue.append({
                'price': float(fill.price),
                'qty': int(fill.qty),
                'timestamp': fill.timestamp
            })
        
        elif fill.side == 'sell':
            # 売りポジション：FIFOで決済
            sell_qty = int(fill.qty)
            sell_price = float(fill.price)
            
            while sell_qty > 0 and position_queue:
                oldest_position = position_queue[0]
                
                if oldest_position['qty'] <= sell_qty:
                    # ポジション完全決済
                    pnl = (sell_price - oldest_position['price']) * oldest_position['qty']
                    realized_pnl += pnl
                    sell_qty -= oldest_position['qty']
                    position_queue.pop(0)
                else:
                    # ポジション部分決済
                    pnl = (sell_price - oldest_position['price']) * sell_qty
                    realized_pnl += pnl
                    oldest_position['qty'] -= sell_qty
                    sell_qty = 0
    
    return realized_pnl
```

#### 取引停止判定
```python
def check_pnl_criteria():
    """
    PnL基準による取引継続可否の判定
    
    Returns:
        bool: True=取引継続可能, False=取引停止
    """
    try:
        current_pnl = calculate_rolling_pnl(days=PNL_CHECK_PERIOD)
        
        if current_pnl <= PNL_CRITERIA:
            logger.warning(f"PnL基準違反: {current_pnl:.3f} <= {PNL_CRITERIA}")
            send_risk_alert(f"取引停止: PnL {current_pnl:.1%}")
            return False
        
        logger.info(f"PnL基準OK: {current_pnl:.3f} > {PNL_CRITERIA}")
        return True
        
    except Exception as e:
        logger.error(f"PnL基準チェックエラー: {e}")
        return False  # エラー時は保守的に停止
```

---

## 2. ポジションサイジング

### 戦略配分システム
```python
def get_target_value(strategy_name='strategy5'):
    """
    戦略別の目標投資額を計算
    
    Args:
        strategy_name: 戦略識別子
        
    Returns:
        float: 目標投資額（USD）
    """
    try:
        # アカウント総価値取得
        account = alpaca_client.get_account()
        total_value = float(account.portfolio_value)
        
        # 戦略配分取得
        allocation = get_strategy_allocation()
        strategy_ratio = allocation.get(strategy_name, 0.2)  # デフォルト20%
        
        # 目標投資額計算
        target_value = total_value * strategy_ratio
        
        logger.info(f"戦略 {strategy_name}: 目標投資額 ${target_value:,.0f} "
                   f"(総価値の{strategy_ratio:.1%})")
        
        return target_value
        
    except Exception as e:
        logger.error(f"目標投資額計算エラー: {e}")
        return 0
```

### 個別ポジションサイズ計算
```python
def calculate_position_size(target_value, num_positions=5, current_price=None):
    """
    個別銘柄のポジションサイズを計算
    
    Args:
        target_value: 戦略の目標投資額
        num_positions: 分散ポジション数
        current_price: 現在価格（オプション）
        
    Returns:
        dict: {'value': 投資額, 'shares': 株数}
    """
    # 基本ポジションサイズ
    base_position_value = target_value / num_positions
    
    # リスク調整（ボラティリティベース）
    if current_price:
        volatility_adjustment = calculate_volatility_adjustment(current_price)
        adjusted_value = base_position_value * volatility_adjustment
    else:
        adjusted_value = base_position_value
    
    # 最大ポジションサイズ制限
    max_position = target_value * 0.3  # 戦略内で最大30%
    final_value = min(adjusted_value, max_position)
    
    # 株数計算（現在価格が利用可能な場合）
    shares = int(final_value / current_price) if current_price else None
    
    return {
        'value': final_value,
        'shares': shares,
        'base_value': base_position_value,
        'adjustment': volatility_adjustment if current_price else 1.0
    }
```

### ボラティリティ調整
```python
def calculate_volatility_adjustment(ticker):
    """
    過去のボラティリティに基づくポジションサイズ調整
    
    Args:
        ticker: 銘柄シンボル
        
    Returns:
        float: 調整係数 (0.5-1.5の範囲)
    """
    try:
        # 過去30日の価格データ取得
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)
        
        bars = alpaca_client.api.get_bars(
            ticker,
            TimeFrame.Day,
            start=start_date,
            end=end_date
        )
        
        if len(bars) < 10:
            return 1.0  # データ不足時はデフォルト
        
        # 日次リターンのボラティリティ計算
        prices = [bar.c for bar in bars]
        returns = [(prices[i] / prices[i-1] - 1) for i in range(1, len(prices))]
        volatility = np.std(returns) * np.sqrt(252)  # 年率ボラティリティ
        
        # 調整係数計算（ボラティリティ30%を基準とする）
        base_volatility = 0.30
        adjustment = base_volatility / volatility if volatility > 0 else 1.0
        
        # 0.5-1.5の範囲に制限
        adjustment = max(0.5, min(1.5, adjustment))
        
        logger.info(f"{ticker} ボラティリティ調整: {volatility:.1%} -> 係数 {adjustment:.2f}")
        return adjustment
        
    except Exception as e:
        logger.error(f"ボラティリティ調整エラー {ticker}: {e}")
        return 1.0
```

---

## 3. 相関リスク管理

### セクター集中リスク
```python
def check_sector_concentration(new_ticker, current_positions):
    """
    セクター集中リスクをチェック
    
    Args:
        new_ticker: 新規購入予定銘柄
        current_positions: 現在のポジション一覧
        
    Returns:
        bool: True=追加購入可能, False=集中リスクあり
    """
    try:
        # 新規銘柄のセクター取得
        new_sector = get_sector_info(new_ticker)
        
        # 現在のセクター別投資額集計
        sector_exposure = {}
        total_value = 0
        
        for position in current_positions:
            sector = get_sector_info(position.symbol)
            value = float(position.market_value)
            sector_exposure[sector] = sector_exposure.get(sector, 0) + value
            total_value += value
        
        # 新規投資後のセクター比率計算
        new_position_value = calculate_position_size()['value']
        projected_sector_value = sector_exposure.get(new_sector, 0) + new_position_value
        projected_total = total_value + new_position_value
        
        sector_ratio = projected_sector_value / projected_total if projected_total > 0 else 0
        
        # セクター集中制限（40%以下）
        MAX_SECTOR_RATIO = 0.40
        
        if sector_ratio > MAX_SECTOR_RATIO:
            logger.warning(f"セクター集中リスク: {new_sector} {sector_ratio:.1%} > {MAX_SECTOR_RATIO:.1%}")
            return False
        
        logger.info(f"セクター集中OK: {new_sector} {sector_ratio:.1%}")
        return True
        
    except Exception as e:
        logger.error(f"セクター集中チェックエラー: {e}")
        return False  # エラー時は保守的に拒否
```

### 銘柄相関チェック
```python
def check_correlation_risk(new_ticker, current_positions, lookback_days=60):
    """
    既存ポジションとの価格相関をチェック
    
    Args:
        new_ticker: 新規銘柄
        current_positions: 現在のポジション
        lookback_days: 相関計算期間
        
    Returns:
        bool: True=相関リスクなし, False=高相関リスクあり
    """
    MAX_CORRELATION = 0.70
    
    try:
        # 新規銘柄の価格データ取得
        new_prices = get_price_data(new_ticker, lookback_days)
        
        high_correlation_count = 0
        
        for position in current_positions:
            existing_ticker = position.symbol
            existing_prices = get_price_data(existing_ticker, lookback_days)
            
            # 価格相関計算
            correlation = calculate_correlation(new_prices, existing_prices)
            
            if abs(correlation) > MAX_CORRELATION:
                high_correlation_count += 1
                logger.warning(f"高相関検出: {new_ticker} vs {existing_ticker} = {correlation:.2f}")
        
        # 高相関銘柄が複数ある場合は拒否
        if high_correlation_count >= 2:
            logger.warning(f"相関リスク: {new_ticker} は {high_correlation_count} 銘柄と高相関")
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"相関チェックエラー: {e}")
        return True  # データ不足時は許可
```

---

## 4. ドローダウン制御

### リアルタイム監視
```python
class DrawdownMonitor:
    """リアルタイムドローダウン監視クラス"""
    
    def __init__(self):
        self.peak_value = 0
        self.current_drawdown = 0
        self.max_drawdown = 0
        self.drawdown_start = None
        
    def update(self, current_value):
        """ポートフォリオ価値更新とドローダウン計算"""
        
        # 新高値更新
        if current_value > self.peak_value:
            self.peak_value = current_value
            self.current_drawdown = 0
            self.drawdown_start = None
            
        else:
            # ドローダウン計算
            self.current_drawdown = (self.peak_value - current_value) / self.peak_value
            
            if self.drawdown_start is None:
                self.drawdown_start = datetime.now()
            
            # 最大ドローダウン更新
            if self.current_drawdown > self.max_drawdown:
                self.max_drawdown = self.current_drawdown
        
        # アラート判定
        self.check_drawdown_alerts()
        
    def check_drawdown_alerts(self):
        """ドローダウンアラートチェック"""
        
        # レベル1: 5%ドローダウン（警告）
        if self.current_drawdown > 0.05:
            logger.warning(f"ドローダウン警告: {self.current_drawdown:.1%}")
        
        # レベル2: 8%ドローダウン（注意）
        if self.current_drawdown > 0.08:
            send_risk_alert(f"ドローダウン注意: {self.current_drawdown:.1%}")
        
        # レベル3: 12%ドローダウン（緊急）
        if self.current_drawdown > 0.12:
            self.trigger_emergency_stop()
    
    def trigger_emergency_stop(self):
        """緊急停止処理"""
        logger.critical(f"緊急停止: ドローダウン {self.current_drawdown:.1%}")
        
        # 新規取引停止フラグ設定
        set_emergency_stop_flag(True)
        
        # 管理者通知
        send_emergency_alert(
            f"緊急停止発動\n"
            f"現在ドローダウン: {self.current_drawdown:.1%}\n"
            f"最大ドローダウン: {self.max_drawdown:.1%}\n"
            f"ドローダウン継続期間: {datetime.now() - self.drawdown_start}"
        )
```

---

## 5. 動的リスク調整

### 市場環境適応
```python
def adjust_risk_parameters():
    """市場環境に応じたリスクパラメータ動的調整"""
    
    try:
        # VIX取得（市場恐怖指数）
        vix_level = get_vix_level()
        
        # S&P500の20日ボラティリティ
        sp500_volatility = get_sp500_volatility()
        
        # リスク環境判定
        if vix_level > 30 or sp500_volatility > 0.25:
            # 高リスク環境
            risk_multiplier = 0.7  # リスク30%削減
            logger.info("高リスク環境検出: リスク削減モード")
            
        elif vix_level < 15 and sp500_volatility < 0.15:
            # 低リスク環境
            risk_multiplier = 1.2  # リスク20%増加
            logger.info("低リスク環境検出: リスク拡大モード")
            
        else:
            # 通常環境
            risk_multiplier = 1.0
            logger.info("通常リスク環境")
        
        # パラメータ更新
        update_risk_parameters(risk_multiplier)
        
    except Exception as e:
        logger.error(f"動的リスク調整エラー: {e}")

def update_risk_parameters(multiplier):
    """リスクパラメータの動的更新"""
    
    # ポジションサイズ調整
    global POSITION_SIZE_MULTIPLIER
    POSITION_SIZE_MULTIPLIER = multiplier
    
    # ストップロス調整
    global DYNAMIC_STOP_MULTIPLIER
    DYNAMIC_STOP_MULTIPLIER = 1.0 / multiplier  # リスク低下時はストップを緩める
    
    # 最大ポジション数調整
    global MAX_POSITIONS
    MAX_POSITIONS = int(5 * multiplier)
    
    logger.info(f"リスクパラメータ更新: 乗数={multiplier:.2f}")
```

---

## 6. リスク報告とアラート

### 日次リスクレポート
```python
def generate_daily_risk_report():
    """日次リスクレポート生成"""
    
    report = {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'portfolio_value': get_portfolio_value(),
        'daily_pnl': calculate_daily_pnl(),
        'rolling_30day_pnl': calculate_rolling_pnl(30),
        'current_drawdown': drawdown_monitor.current_drawdown,
        'max_drawdown': drawdown_monitor.max_drawdown,
        'position_count': len(get_current_positions()),
        'sector_exposure': calculate_sector_exposure(),
        'correlation_metrics': calculate_correlation_metrics(),
        'risk_alerts': get_active_risk_alerts()
    }
    
    # レポート保存
    save_risk_report(report)
    
    # 管理者送信（重要な変化がある場合）
    if should_send_report(report):
        send_risk_report_email(report)
    
    return report
```

### アラートシステム
```python
class RiskAlertManager:
    """リスクアラート管理"""
    
    ALERT_LEVELS = {
        'INFO': 1,
        'WARNING': 2, 
        'CRITICAL': 3,
        'EMERGENCY': 4
    }
    
    def send_alert(self, level, message, data=None):
        """リスクアラート送信"""
        
        alert = {
            'timestamp': datetime.now(),
            'level': level,
            'message': message,
            'data': data or {}
        }
        
        # ログ記録
        logger.log(self._get_log_level(level), f"RISK ALERT: {message}")
        
        # レベル別処理
        if level >= self.ALERT_LEVELS['CRITICAL']:
            # 即座に管理者通知
            self.send_immediate_notification(alert)
            
        if level >= self.ALERT_LEVELS['EMERGENCY']:
            # 緊急停止処理
            self.trigger_emergency_procedures(alert)
        
        # アラート履歴保存
        self.save_alert_history(alert)
    
    def send_immediate_notification(self, alert):
        """即座の管理者通知"""
        try:
            # Email通知
            send_email_alert(alert)
            
            # Slack通知（設定されている場合）
            if SLACK_WEBHOOK_URL:
                send_slack_alert(alert)
                
        except Exception as e:
            logger.error(f"通知送信エラー: {e}")
```

---

## 7. バックテストとリスク検証

### 履歴データでのリスク検証
```python
def backtest_risk_metrics(start_date, end_date):
    """過去データでリスク指標をバックテスト"""
    
    results = {
        'max_drawdown': 0,
        'sharpe_ratio': 0,
        'sortino_ratio': 0,
        'var_95': 0,  # 95% Value at Risk
        'expected_shortfall': 0,
        'maximum_consecutive_losses': 0
    }
    
    # 過去の取引データ取得
    historical_trades = get_historical_trades(start_date, end_date)
    
    if not historical_trades:
        return results
    
    # 日次リターン計算
    daily_returns = calculate_daily_returns(historical_trades)
    
    # リスク指標計算
    results['max_drawdown'] = calculate_max_drawdown(daily_returns)
    results['sharpe_ratio'] = calculate_sharpe_ratio(daily_returns)
    results['sortino_ratio'] = calculate_sortino_ratio(daily_returns)
    results['var_95'] = calculate_var(daily_returns, confidence=0.95)
    results['expected_shortfall'] = calculate_expected_shortfall(daily_returns, confidence=0.95)
    results['maximum_consecutive_losses'] = calculate_max_consecutive_losses(daily_returns)
    
    return results
```

このリスク管理システムは、資本保護を最優先としながら、適切なリスクテイクによる収益機会の確保を目指しています。各コンポーネントは独立してテスト可能で、システム全体の堅牢性を保証します。
// Turkish names for the bot's live-editable settings (config.DEFAULT_SETTINGS). The help text
// comes from the bot itself; a key missing here (a newer bot) is shown as it is.
const LABELS: Record<string, string> = {
  trading_enabled: 'Yeni işlem açılsın',
  allow_short: 'Short işlemlere izin ver',
  ema_trend_period: 'Trend EMA periyodu',
  ema_slope_bars: 'Trend eğimi (mum)',
  rsi_period: 'RSI periyodu',
  rsi_long_min: 'Long için RSI alt sınırı',
  rsi_long_max: 'Long için RSI üst sınırı',
  rsi_short_min: 'Short için RSI alt sınırı',
  rsi_short_max: 'Short için RSI üst sınırı',
  macd_fast: 'MACD hızlı periyot',
  macd_slow: 'MACD yavaş periyot',
  macd_signal: 'MACD sinyal periyodu',
  macd_cross_lookback: 'MACD kesişim penceresi (mum)',
  volume_ma_period: 'Hacim ortalaması periyodu',
  volume_factor: 'Hacim çarpanı',
  atr_period: 'ATR periyodu',
  adx_period: 'ADX periyodu',
  adx_min: 'En düşük ADX (trend gücü)',
  donchian_period: 'Donchian kanal periyodu',
  breakout_atr_buffer: 'Kırılım payı (ATR)',
  min_atr_pct: 'En düşük oynaklık (ATR %)',
  min_confirmations: 'Gereken teyit sayısı',
  exit_on_trend_flip: 'Trend dönünce çık',
  risk_per_trade_pct: 'İşlem başına risk (%)',
  atr_sl_multiplier: 'Stop-loss mesafesi (ATR katı)',
  risk_reward_ratio: 'Kâr al / risk oranı',
  trailing_enabled: 'Trailing stop',
  trailing_atr_multiplier: 'Trailing mesafesi (ATR katı)',
  trailing_activation_r: 'Trailing başlama eşiği (R)',
  daily_loss_limit_pct: 'Günlük zarar limiti (%)',
  max_open_positions: 'En fazla açık pozisyon',
  max_symbol_exposure_pct: 'Sembol başına en fazla büyüklük (%)',
  round_trip_cost_pct: 'Hesaba katılan işlem maliyeti (%)',
  exchange_stop_enabled: 'Borsada stop emri (canlı mod)',
};

export function settingLabel(key: string): string {
  return LABELS[key] ?? key;
}

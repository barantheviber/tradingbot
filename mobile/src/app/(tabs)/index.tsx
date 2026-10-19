import { useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { RefreshControl, ScrollView, Text, View } from 'react-native';

import { api } from '../../api/client';
import type { Candle, Pnl, Trade } from '../../api/types';
import { BotControl } from '../../components/BotControl';
import { CandleChart } from '../../components/CandleChart';
import { PnlCurve } from '../../components/PnlCurve';
import { SafetyHaltCard } from '../../components/SafetyHaltCard';
import { WelcomeCard } from '../../components/WelcomeCard';
import { Banner, Card, Chip, Stat, styles } from '../../components/ui';
import { useConnection, useRequiredConnection } from '../../lib/connection';
import { age, num, pct, signed } from '../../lib/format';
import { useLive } from '../../lib/live';
import { colors, pnlColor } from '../../lib/theme';

const CHART_CANDLES = 120;

export default function OverviewScreen() {
  const connection = useRequiredConnection();
  const { local } = useConnection();
  const { status, positions, wsConnected, error, refresh } = useLive();
  const [pnl, setPnl] = useState<Pnl | null>(null);
  const [symbol, setSymbol] = useState<string | null>(null);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [chartError, setChartError] = useState<string | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [periods, setPeriods] = useState<{ ema: number; donchian: number }>({ ema: 200, donchian: 20 });
  const [refreshing, setRefreshing] = useState(false);

  const activeSymbol = symbol ?? status?.symbols[0] ?? null;

  const loadPnl = useCallback(() => api.pnl(connection).then(setPnl).catch(() => undefined), [connection]);
  const loadTrades = useCallback(
    () => api.trades(connection, 1000).then(setTrades).catch(() => undefined),
    [connection],
  );
  // The chart draws the same EMA / Donchian periods the bot trades with; they are live settings.
  const loadPeriods = useCallback(async () => {
    try {
      const settings = await api.settings(connection);
      const value = (key: string, fallback: number) => {
        const v = Number(settings.find((s) => s.key === key)?.value);
        return Number.isFinite(v) && v > 0 ? Math.round(v) : fallback;
      };
      setPeriods({ ema: value('ema_trend_period', 200), donchian: value('donchian_period', 20) });
    } catch {
      // keep the defaults
    }
  }, [connection]);
  const loadCandles = useCallback(async () => {
    if (!activeSymbol) return;
    try {
      // extra candles in front so the EMA has warmed up by the first candle shown
      const limit = Math.min(1000, CHART_CANDLES + periods.ema);
      setCandles(await api.candles(connection, activeSymbol, status?.timeframe, limit));
      setChartError(null);
    } catch (e) {
      setChartError(e instanceof Error ? e.message : String(e));
    }
  }, [connection, activeSymbol, status?.timeframe, periods.ema]);

  useFocusEffect(
    useCallback(() => {
      loadPeriods();
    }, [loadPeriods]),
  );

  // PnL and the trade list change when a position closes; re-read them whenever the open count changes.
  useEffect(() => {
    loadPnl();
    loadTrades();
  }, [loadPnl, loadTrades, status?.open_positions]);

  useEffect(() => {
    loadCandles();
    const timer = setInterval(loadCandles, 30_000);
    return () => clearInterval(timer);
  }, [loadCandles]);

  const onRefresh = async () => {
    setRefreshing(true);
    await Promise.all([refresh(), loadPnl(), loadTrades(), loadPeriods(), loadCandles()]);
    setRefreshing(false);
  };

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />}
    >
      {local ? <BotControl positions={positions} /> : null}
      {status?.safety_halt?.active ? (
        <SafetyHaltCard halt={status.safety_halt} connection={connection} onChanged={() => void refresh()} />
      ) : null}
      {local ? <WelcomeCard timeframe={status?.timeframe ?? null} /> : null}
      {error && !local ? <Banner tone="error" text={error} /> : null}
      {status && !status.bot_running && !local ? (
        <Banner text={`Bot çalışmıyor görünüyor (${age(status.heartbeat_age_sec)}). Kapatma komutları bot açılınca işlenir.`} />
      ) : null}
      {status?.entries_halted_by_daily_limit ? (
        <Banner tone="error" text="Günlük zarar limiti aşıldı: UTC gece yarısına kadar yeni pozisyon açılmayacak." />
      ) : null}
      {status && !status.trading_enabled ? <Banner text="Kill switch kapalı: yeni pozisyon açılmıyor." /> : null}

      <Card title="Durum">
        <View style={styles.statGrid}>
          <Stat
            label="Mod"
            value={status ? (status.mode === 'paper' ? 'PAPER' : 'LIVE') : '-'}
            color={status?.mode === 'live' ? colors.down : colors.up}
            hint={status ? `${status.exchange}${status.testnet ? ' (testnet)' : ''} · ${status.timeframe}` : undefined}
          />
          <Stat
            label="Bot"
            value={status ? (status.bot_running ? 'Çalışıyor' : 'Durdu') : '-'}
            color={status?.bot_running ? colors.up : colors.warn}
            hint={`${wsConnected ? 'canlı' : 'bağlantı yok'} · ${age(status?.heartbeat_age_sec)}`}
          />
          <Stat label="Özsermaye" value={num(status?.equity)} />
          <Stat label="Bugünkü PnL" value={signed(status?.today_pnl)} color={pnlColor(status?.today_pnl)} />
          <Stat
            label="Günlük zarar"
            value={pct(status?.daily_loss_pct)}
            hint={status ? `limit %${num(status.daily_loss_limit_pct, 1)}` : undefined}
            color={status?.entries_halted_by_daily_limit ? colors.down : undefined}
          />
          <Stat label="Açık pozisyon" value={status ? `${status.open_positions} / ${status.max_open_positions ?? '-'}` : '-'} />
        </View>
      </Card>

      <Card title="Grafik">
        <View style={[styles.chipRow, { marginBottom: 8 }]}>
          {(status?.symbols ?? []).map((s) => (
            <Chip key={s} label={s} active={s === activeSymbol} onPress={() => setSymbol(s)} />
          ))}
        </View>
        {chartError ? <Text style={styles.muted}>{chartError}</Text> : null}
        <CandleChart
          candles={candles}
          visible={CHART_CANDLES}
          positions={positions.filter((p) => p.symbol === activeSymbol)}
          trades={trades}
          symbol={activeSymbol}
          timeframe={status?.timeframe}
          emaPeriod={periods.ema}
          donchianPeriod={periods.donchian}
        />
      </Card>

      <Card title="PnL eğrisi">
        <PnlCurve trades={trades} unrealized={pnl?.unrealized_pnl} startingEquity={pnl?.starting_equity} />
      </Card>

      <Card title="PnL özeti">
        <View style={styles.statGrid}>
          <Stat label="Toplam PnL" value={signed(pnl?.total_pnl)} color={pnlColor(pnl?.total_pnl)} />
          <Stat label="Gerçekleşmemiş" value={signed(pnl?.unrealized_pnl)} color={pnlColor(pnl?.unrealized_pnl)} />
          <Stat label="İşlem" value={pnl ? String(pnl.trades) : '-'} hint={pnl ? `${pnl.wins} kazanç / ${pnl.losses} kayıp` : undefined} />
          <Stat label="Kazanma oranı" value={pct(pnl?.win_rate_pct, 1)} />
          <Stat
            label="Profit factor"
            value={pnl ? (pnl.profit_factor_infinite ? '∞' : num(pnl.profit_factor)) : '-'}
          />
          <Stat label="Maks. drawdown" value={num(pnl?.max_drawdown)} hint={pct(pnl?.max_drawdown_pct)} />
          <Stat label="Ort. kazanç" value={num(pnl?.avg_win)} color={pnl?.trades ? colors.up : undefined} />
          <Stat label="Ort. kayıp" value={num(pnl?.avg_loss)} color={pnl?.trades ? colors.down : undefined} />
          <Stat
            label="Beklenti / işlem"
            value={signed(pnl?.expectancy)}
            color={pnlColor(pnl?.expectancy)}
            hint="ortalama PnL"
          />
          <Stat label="Ödenen komisyon" value={num(pnl?.fees)} />
        </View>
      </Card>
    </ScrollView>
  );
}

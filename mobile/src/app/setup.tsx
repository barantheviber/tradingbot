import { router } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Pressable, ScrollView, Text, TextInput, View } from 'react-native';

import { BotRuntime } from '../../modules/bot-runtime';
import { Button, Card, styles } from '../components/ui';
import { useConnection } from '../lib/connection';
import { useLocalBot } from '../lib/localBot';
import {
  DEFAULT_SETUP,
  EXCHANGES,
  parseSymbols,
  TIMEFRAMES,
  validateSetup,
  type LocalSetup,
  type MarketType,
} from '../lib/localSetup';
import { colors } from '../lib/theme';

function Chips<T extends string>({ options, value, onChange }: { options: { id: T; label: string }[]; value: T; onChange: (v: T) => void }) {
  return (
    <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6 }}>
      {options.map((o) => (
        <Pressable
          key={o.id}
          onPress={() => onChange(o.id)}
          style={{
            paddingHorizontal: 12,
            paddingVertical: 6,
            borderRadius: 14,
            borderWidth: 1,
            borderColor: o.id === value ? colors.accent : colors.border,
          }}
        >
          <Text style={{ color: o.id === value ? colors.accent : colors.muted }}>{o.label}</Text>
        </Pressable>
      ))}
    </View>
  );
}

export default function SetupScreen() {
  const { localSetup, saveLocalSetup } = useConnection();
  const bot = useLocalBot();
  const first = localSetup === null;
  const start = localSetup ?? DEFAULT_SETUP;
  const [exchangeId, setExchangeId] = useState(start.exchangeId);
  const [marketType, setMarketType] = useState<MarketType>(start.marketType);
  const [symbols, setSymbols] = useState(start.symbols.join(', '));
  const [timeframe, setTimeframe] = useState(start.timeframe);
  const [balance, setBalance] = useState(String(start.startingBalance));
  const [problems, setProblems] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const running = bot.state.phase === 'running' || bot.state.phase === 'starting';

  const submit = async () => {
    const setup: LocalSetup = {
      exchangeId,
      marketType,
      symbols: parseSymbols(symbols),
      timeframe,
      startingBalance: Number(balance.replace(',', '.')),
    };
    const found = validateSetup(setup);
    setProblems(found);
    if (found.length) return;
    setBusy(true);
    try {
      const conn = await saveLocalSetup(setup);
      if (first) await bot.start(setup, conn.token);
      else if (running) {
        // restart with the new setup
        bot.stop();
        const until = Date.now() + 90_000;
        while (Date.now() < until && !['stopped', 'error'].includes(BotRuntime?.getState().phase ?? 'stopped')) {
          await new Promise((r) => setTimeout(r, 1_000));
        }
        await bot.start(setup, conn.token);
      }
      router.replace('/');
    } catch (e) {
      setProblems([e instanceof Error ? e.message : String(e)]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <KeyboardAvoidingView style={styles.screen}>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <Card title={first ? 'Hoş geldiniz: botu kuralım' : 'Bot kurulumu'}>
          <Text style={styles.muted}>
            Bot bu telefonun içinde çalışır, bilgisayara ihtiyaç duymaz. Her zaman paper trading (sanal bakiye)
            modundadır; gerçek emir göndermez ve borsa API anahtarı istemez.
          </Text>
          <View style={{ gap: 10, marginTop: 12 }}>
            <Text style={styles.text}>Borsa</Text>
            <Chips options={EXCHANGES} value={exchangeId} onChange={setExchangeId} />
            <Text style={styles.text}>Piyasa</Text>
            <Chips<MarketType>
              options={[
                { id: 'spot', label: 'Spot' },
                { id: 'future', label: 'Vadeli' },
                { id: 'swap', label: 'Sürekli vadeli' },
              ]}
              value={marketType}
              onChange={setMarketType}
            />
            <Text style={styles.text}>Semboller (virgülle ayırın)</Text>
            <TextInput
              style={styles.input}
              value={symbols}
              onChangeText={setSymbols}
              autoCapitalize="characters"
              autoCorrect={false}
              placeholder="BTC/USDT, ETH/USDT"
              placeholderTextColor={colors.muted}
            />
            <Text style={styles.text}>Zaman dilimi</Text>
            <Chips options={TIMEFRAMES.map((t) => ({ id: t, label: t }))} value={timeframe} onChange={setTimeframe} />
            <Text style={styles.text}>Sanal başlangıç bakiyesi (USDT)</Text>
            <TextInput style={styles.input} value={balance} onChangeText={setBalance} keyboardType="decimal-pad" />
          </View>
          {problems.map((p) => (
            <Text key={p} style={{ color: colors.down, marginTop: 8 }}>
              {p}
            </Text>
          ))}
          <View style={{ marginTop: 14 }}>
            <Button
              label={first ? 'Kaydet ve botu başlat' : running ? 'Kaydet ve yeniden başlat' : 'Kaydet'}
              tone="primary"
              onPress={() => void submit()}
              busy={busy}
            />
          </View>
        </Card>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

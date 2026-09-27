import * as SecureStore from 'expo-secure-store';
import { useEffect, useState } from 'react';
import { Text, View } from 'react-native';

import { Button, Card, styles } from './ui';

const KEY = 'tradingbot.welcomeDismissed';

/** First-run notes on the overview until the user closes them. */
export function WelcomeCard({ timeframe }: { timeframe: string | null }) {
  const [hidden, setHidden] = useState(true);

  useEffect(() => {
    SecureStore.getItemAsync(KEY)
      .then((v) => setHidden(v === '1'))
      .catch(() => setHidden(false));
  }, []);

  if (hidden) return null;

  const close = () => {
    setHidden(true);
    SecureStore.setItemAsync(KEY, '1').catch(() => undefined);
  };

  const lines = [
    `Bot yalnızca kapanmış mumlarda karar verir. ${timeframe ?? 'Seçtiğiniz'} zaman diliminde ilk kararın gelmesi bir mum süresi kadar sürebilir; bu sırada ekranın sakin olması normaldir.`,
    'Her şey paper trading (sanal bakiye) ile olur, gerçek emir gönderilmez.',
    'Bot çalışırken bildirim çubuğunda "Trading bot çalışıyor" bildirimi durur. Uygulamayı kapatsanız da bot çalışmaya devam eder.',
    'Pil ayarını "Kısıtlanmamış" yapın; yoksa Android botu arka planda durdurabilir.',
    'Bilgisayara geçerken: "Durdur"a basıp "Kapat ve durdur"u seçin, sonra bilgisayarda botu başlatın. İki cihaz birbirinin pozisyonlarını bilmez.',
  ];

  return (
    <Card title="Bot hazır. Bilmeniz gerekenler">
      <View style={{ gap: 6 }}>
        {lines.map((l) => (
          <Text key={l} style={styles.text}>
            • {l}
          </Text>
        ))}
      </View>
      <View style={{ marginTop: 10 }}>
        <Button label="Anladım" onPress={close} />
      </View>
    </Card>
  );
}

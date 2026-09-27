import { useCallback, useEffect, useState } from 'react';
import { PermissionsAndroid, Platform } from 'react-native';

import { BotRuntime, type BotRuntimeState } from '../../modules/bot-runtime';
import { runtimeConfig, type LocalSetup } from './localSetup';

const POLL_MS = 2_000;

/** State of the bot running on this phone, polled from the native service. */
export function useLocalBot() {
  const [state, setState] = useState<BotRuntimeState>(() => BotRuntime?.getState() ?? { phase: 'stopped', message: null });

  const poll = useCallback(() => {
    if (BotRuntime) setState(BotRuntime.getState());
  }, []);

  useEffect(() => {
    if (!BotRuntime) return;
    const timer = setInterval(poll, POLL_MS);
    return () => clearInterval(timer);
  }, [poll]);

  const start = useCallback(
    async (setup: LocalSetup, token: string) => {
      if (!BotRuntime) return;
      // Android 13+ asks before showing notifications; the bot still runs if the user says no.
      if (Platform.OS === 'android' && Platform.Version >= 33) {
        await PermissionsAndroid.request('android.permission.POST_NOTIFICATIONS' as never).catch(() => undefined);
      }
      BotRuntime.start(runtimeConfig(setup, token));
      poll();
    },
    [poll],
  );

  const stop = useCallback(() => {
    BotRuntime?.stop();
    poll();
  }, [poll]);

  return { state, start, stop, available: BotRuntime !== null };
}

export function batteryUnrestricted(): boolean {
  return BotRuntime ? BotRuntime.isIgnoringBatteryOptimizations() : true;
}

export function askBatteryUnrestricted(): void {
  BotRuntime?.requestIgnoreBatteryOptimizations();
}

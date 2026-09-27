import { Platform } from 'react-native';
import { requireOptionalNativeModule } from 'expo';

export type BotPhase = 'stopped' | 'starting' | 'running' | 'stopping' | 'error';

export interface BotRuntimeState {
  phase: BotPhase;
  message: string | null;
}

interface BotRuntimeNative {
  start(config: string): void;
  stop(): void;
  getState(): BotRuntimeState;
  newToken(): string;
  isIgnoringBatteryOptimizations(): boolean;
  requestIgnoreBatteryOptimizations(): void;
}

/** The on-device bot. null in Expo Go, on the web and on iOS: those only connect to a bot elsewhere. */
export const BotRuntime: BotRuntimeNative | null =
  Platform.OS === 'android' ? requireOptionalNativeModule<BotRuntimeNative>('BotRuntime') : null;

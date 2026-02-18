import { getRosbridgeClient } from '$lib/recording/rosbridge';

export type RosbridgeStatus = 'idle' | 'connecting' | 'connected' | 'disconnected' | 'error';

export type RecorderStatus = Record<string, unknown> & {
  state?: string;
  status?: string;
  phase?: string;
  task?: string;
  dataset_id?: string;
  episode_index?: number | null;
  episode_count?: number;
  num_episodes?: number;
  frame_count?: number;
  episode_frame_count?: number;
  episode_time_s?: number;
  reset_time_s?: number;
  episode_elapsed_s?: number;
  episode_remaining_s?: number;
  reset_elapsed_s?: number;
  reset_remaining_s?: number;
  last_error?: string;
};

export const RECORDER_STATUS_TOPIC = '/lerobot_recorder/status';
export const RECORDER_STATUS_THROTTLE_MS = 66;

export const parseRecorderPayload = (msg: Record<string, unknown>): RecorderStatus => {
  if (typeof msg.data === 'string') {
    try {
      return JSON.parse(msg.data) as RecorderStatus;
    } catch {
      return { state: 'unknown' };
    }
  }
  return msg as RecorderStatus;
};

export const subscribeRecorderStatus = (handlers: {
  onStatus: (status: RecorderStatus) => void;
  onConnectionChange?: (status: RosbridgeStatus) => void;
  throttleMs?: number;
}) => {
  const client = getRosbridgeClient();
  const unsubscribe = client.subscribe(
    RECORDER_STATUS_TOPIC,
    (message) => {
      handlers.onStatus(parseRecorderPayload(message));
    },
    {
      throttle_rate: handlers.throttleMs ?? RECORDER_STATUS_THROTTLE_MS
    }
  );

  const offStatus = client.onStatusChange((next) => {
    handlers.onConnectionChange?.(next);
  });
  handlers.onConnectionChange?.(client.getStatus());

  return () => {
    unsubscribe();
    offStatus();
  };
};

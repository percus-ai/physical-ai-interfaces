import { browser } from '$app/environment';
import { getBackendUrl } from '$lib/config';

type StreamOptions<T> = {
  path: string;
  onMessage: (payload: T) => void;
  onError?: (event: Event) => void;
};

export const connectStream = <T>({ path, onMessage, onError }: StreamOptions<T>) => {
  if (!browser) return () => {};

  const baseUrl = getBackendUrl();
  const url = new URL(path, baseUrl);
  const source = new EventSource(url.toString(), { withCredentials: true });

  const handleMessage = (event: MessageEvent<string>) => {
    if (!event.data) return;
    try {
      const payload = JSON.parse(event.data) as T;
      onMessage(payload);
    } catch {
      // ignore parse errors
    }
  };

  source.addEventListener('message', handleMessage);

  source.onerror = (event) => {
    onError?.(event);
  };

  return () => {
    source.removeEventListener('message', handleMessage);
    source.close();
  };
};

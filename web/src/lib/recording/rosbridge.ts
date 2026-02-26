import { getBackendUrl } from '$lib/config';

type RosbridgeStatus = 'idle' | 'connecting' | 'connected' | 'disconnected' | 'error';

type SubscriptionOptions = {
  type?: string;
  throttle_rate?: number;
  queue_length?: number;
};

type SubscriptionHandler = (message: Record<string, unknown>) => void;

type Subscription = {
  topic: string;
  handlers: Set<SubscriptionHandler>;
  options: SubscriptionOptions;
};

class RosbridgeClient {
  private ws: WebSocket | null = null;
  private status: RosbridgeStatus = 'idle';
  private subscriptions = new Map<string, Subscription>();
  private connectPromise: Promise<void> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempt = 0;
  private statusListeners = new Set<(status: RosbridgeStatus) => void>();

  getStatus() {
    return this.status;
  }

  onStatusChange(handler: (status: RosbridgeStatus) => void) {
    this.statusListeners.add(handler);
    return () => {
      this.statusListeners.delete(handler);
    };
  }

  connect() {
    if (this.status === 'connected' && this.ws) return Promise.resolve();
    if (this.connectPromise) return this.connectPromise;

    this.updateStatus('connecting');
    const url = this.buildUrl();
    if (!url) {
      this.updateStatus('error');
      return Promise.reject(new Error('rosbridge url not available'));
    }

    this.connectPromise = new Promise((resolve, reject) => {
      const ws = new WebSocket(url);
      this.ws = ws;

      ws.onopen = () => {
        this.updateStatus('connected');
        this.connectPromise = null;
        this.reconnectAttempt = 0;
        for (const sub of this.subscriptions.values()) {
          this.sendSubscribe(sub.topic, sub.options);
        }
        resolve();
      };

      ws.onmessage = (event) => {
        if (!event?.data) return;
        let payload: Record<string, unknown> | null = null;
        try {
          payload = JSON.parse(event.data);
        } catch {
          return;
        }
        if (!payload || payload.op !== 'publish') return;
        const topic = payload.topic as string | undefined;
        if (!topic) return;
        const sub = this.subscriptions.get(topic);
        if (!sub) return;
        for (const handler of sub.handlers) {
          handler(payload.msg as Record<string, unknown>);
        }
      };

      ws.onerror = () => {
        this.updateStatus('error');
        this.connectPromise = null;
        this.scheduleReconnect();
        reject(new Error('rosbridge connection error'));
      };

      ws.onclose = () => {
        this.updateStatus('disconnected');
        this.connectPromise = null;
        this.ws = null;
        this.scheduleReconnect();
      };
    });

    return this.connectPromise;
  }

  subscribe(topic: string, handler: SubscriptionHandler, options: SubscriptionOptions = {}) {
    if (!topic) return () => {};

    let entry = this.subscriptions.get(topic);
    if (!entry) {
      entry = {
        topic,
        handlers: new Set<SubscriptionHandler>(),
        options
      };
      this.subscriptions.set(topic, entry);
    }

    entry.handlers.add(handler);

    if (this.status === 'connected' && this.ws) {
      this.sendSubscribe(topic, entry.options);
    } else if (typeof window !== 'undefined') {
      this.connect().catch(() => {
        // ignore connect errors; component can show fallback
      });
    }

    return () => {
      const current = this.subscriptions.get(topic);
      if (!current) return;
      current.handlers.delete(handler);
      if (current.handlers.size === 0) {
        this.subscriptions.delete(topic);
        if (this.ws && this.status === 'connected') {
          this.sendUnsubscribe(topic);
        }
      }
    };
  }

  private sendSubscribe(topic: string, options: SubscriptionOptions) {
    if (!this.ws || this.status !== 'connected') return;
    const payload = {
      op: 'subscribe',
      topic,
      type: options.type,
      queue_length: options.queue_length ?? 1,
      throttle_rate: options.throttle_rate ?? 100
    };
    this.ws.send(JSON.stringify(payload));
  }

  private sendUnsubscribe(topic: string) {
    if (!this.ws || this.status !== 'connected') return;
    this.ws.send(JSON.stringify({ op: 'unsubscribe', topic }));
  }

  private scheduleReconnect() {
    if (this.reconnectTimer || this.subscriptions.size === 0) return;
    const delay = Math.min(1000 * 2 ** this.reconnectAttempt, 15000);
    this.reconnectAttempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect().catch(() => {
        // retry continues on next schedule
      });
    }, delay);
  }

  private updateStatus(next: RosbridgeStatus) {
    if (this.status === next) return;
    this.status = next;
    for (const listener of this.statusListeners) {
      listener(next);
    }
  }

  private buildUrl() {
    if (typeof window === 'undefined') return '';
    const backendUrl = getBackendUrl();
    try {
      const parsed = new URL(backendUrl);
      const protocol = parsed.protocol === 'https:' ? 'wss' : 'ws';
      const host = parsed.hostname || window.location.hostname || 'localhost';
      return `${protocol}://${host}:9090`;
    } catch {
      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const host = window.location.hostname || 'localhost';
      return `${protocol}://${host}:9090`;
    }
  }
}

let singleton: RosbridgeClient | null = null;

export const getRosbridgeClient = () => {
  if (!singleton) {
    singleton = new RosbridgeClient();
  }
  return singleton;
};

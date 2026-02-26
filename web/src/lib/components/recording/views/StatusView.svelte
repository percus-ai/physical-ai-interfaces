<script lang="ts">
  import { getRosbridgeClient } from '$lib/recording/rosbridge';

  let { topic = '', title = 'Status' }: { topic?: string; title?: string } = $props();

  let payload = $state<Record<string, unknown> | null>(null);
  let raw = $state<string | null>(null);
  let status = $state('idle');
  let lastUpdated = $state('');
  let unsubscribe: (() => void) | null = null;

  const parsePayload = (msg: Record<string, unknown>) => {
    if (typeof msg.data === 'string') {
      raw = msg.data;
      try {
        const parsed = JSON.parse(msg.data);
        if (parsed && typeof parsed === 'object') {
          payload = parsed as Record<string, unknown>;
          return;
        }
      } catch {
        // ignore
      }
    }
    raw = null;
    payload = msg;
  };

  const handleMessage = (msg: Record<string, unknown>) => {
    parsePayload(msg);
    lastUpdated = new Date().toLocaleTimeString();
  };

  const subscribe = () => {
    if (!topic) return;
    const client = getRosbridgeClient();
    const throttleRate = topic === '/lerobot_recorder/status' ? 66 : 200;
    unsubscribe?.();
    unsubscribe = client.subscribe(topic, handleMessage, {
      throttle_rate: throttleRate
    });
    status = client.getStatus();
  };

  $effect(() => {
    if (!topic) {
      unsubscribe?.();
      unsubscribe = null;
      payload = null;
      raw = null;
      return;
    }
    subscribe();
    return () => {
      unsubscribe?.();
      unsubscribe = null;
    };
  });
</script>

<div class="flex h-full flex-col gap-3">
  <div class="flex items-center justify-between">
    <p class="text-xs font-semibold uppercase tracking-widest text-slate-500">{title}</p>
    <span class="text-[10px] text-slate-400">{topic || 'no topic'}</span>
  </div>
  <div class="flex-1 rounded-2xl border border-slate-200/60 bg-white/70 p-3 text-xs text-slate-600">
    {#if payload}
      <div class="grid gap-2">
        {#each Object.entries(payload) as [key, value]}
          <div class="flex items-center justify-between gap-4">
            <span class="text-slate-500">{key}</span>
            <span class="text-slate-800">{typeof value === 'object' ? JSON.stringify(value) : String(value)}</span>
          </div>
        {/each}
      </div>
    {:else if raw}
      <pre class="whitespace-pre-wrap text-xs text-slate-700">{raw}</pre>
    {:else}
      <p class="text-xs text-slate-400">データを待機中… ({status})</p>
    {/if}
  </div>
  <p class="text-[10px] text-slate-400">更新: {lastUpdated || '-'}</p>
</div>

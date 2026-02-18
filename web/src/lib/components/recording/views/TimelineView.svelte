<script lang="ts">
  import {
    subscribeRecorderStatus,
    type RecorderStatus,
    type RosbridgeStatus
  } from '$lib/recording/recorderStatus';

  let {
    sessionId = '',
    title = 'Timeline',
    mode = 'recording'
  }: {
    sessionId?: string;
    title?: string;
    mode?: 'recording' | 'operate';
  } = $props();

  let recorderStatus = $state<RecorderStatus | null>(null);
  let rosbridgeStatus = $state<RosbridgeStatus>('idle');

  const asNumber = (value: unknown, fallback = 0) => {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  };

  $effect(() => {
    if (typeof window === 'undefined') return;
    return subscribeRecorderStatus({
      onStatus: (next) => {
        recorderStatus = next;
      },
      onConnectionChange: (next) => {
        rosbridgeStatus = next;
      }
    });
  });

  const status = $derived(recorderStatus ?? {});
  const statusDatasetId = $derived.by(() => {
    const value = (status as Record<string, unknown>)?.dataset_id;
    return typeof value === 'string' ? value : '';
  });
  const rawStatusPhase = $derived(String((status as Record<string, unknown>)?.phase ?? 'wait'));
  const statusPhase = $derived.by(() => {
    if (!sessionId) return rawStatusPhase;
    if (!statusDatasetId || statusDatasetId !== sessionId) return 'wait';
    return rawStatusPhase;
  });
  const statusDetail = $derived(String((status as Record<string, unknown>)?.last_error ?? ''));
  const finalizeElapsed = $derived(asNumber((status as Record<string, unknown>)?.finalize_elapsed_s ?? 0));
  const episodeIndex = $derived((status as Record<string, unknown>)?.episode_index ?? null);
  const episodeTotal = $derived(asNumber((status as Record<string, unknown>)?.num_episodes ?? 0));
  const episodeTime = $derived(asNumber((status as Record<string, unknown>)?.episode_time_s ?? 0));
  const episodeElapsed = $derived(asNumber((status as Record<string, unknown>)?.episode_elapsed_s ?? 0));
  const resetTime = $derived(asNumber((status as Record<string, unknown>)?.reset_time_s ?? 0));
  const resetElapsed = $derived(asNumber((status as Record<string, unknown>)?.reset_elapsed_s ?? 0));

  const timelineMode = $derived(
    statusPhase === 'finalizing'
      ? 'finalizing'
      : statusPhase === 'recording'
        ? 'recording'
        : statusPhase === 'reset'
          ? 'reset'
          : 'wait'
  );
  const timelineTotal = $derived(
    timelineMode === 'recording' ? episodeTime : timelineMode === 'reset' ? resetTime : 0
  );
  const timelineElapsed = $derived(
    timelineMode === 'recording'
      ? episodeElapsed
      : timelineMode === 'reset'
        ? resetElapsed
        : timelineMode === 'finalizing'
          ? finalizeElapsed
          : 0
  );
  const timelineProgress = $derived(
    timelineMode === 'finalizing'
      ? 1
      : timelineTotal > 0
        ? Math.min(Math.max(timelineElapsed / timelineTotal, 0), 1)
        : 0
  );
  const timelineLabel = $derived(
    timelineMode === 'recording'
      ? '録画中'
      : timelineMode === 'reset'
        ? 'リセット中'
        : timelineMode === 'finalizing'
          ? '保存中'
          : '待機中'
  );
  const connectionWarning = $derived(
    rosbridgeStatus !== 'connected' ? 'rosbridge が切断されています。状態は更新されません。' : ''
  );

  const formatSeconds = (value: number) => `${value.toFixed(1)}s`;
</script>

<div class="flex h-full flex-col gap-3">
  <div class="flex items-center justify-between">
    <p class="text-xs font-semibold uppercase tracking-widest text-slate-500">{title}</p>
    <span class="text-[10px] text-slate-400">{timelineLabel}</span>
  </div>

  {#if mode !== 'recording'}
    <div class="rounded-xl border border-amber-200/70 bg-amber-50/60 p-3 text-xs text-amber-700">
      このビューは録画セッションのみ対応しています。
    </div>
  {:else}
    {#if connectionWarning}
      <p class="text-xs text-amber-600">{connectionWarning}</p>
    {/if}

    <div class="rounded-2xl border border-slate-200/60 bg-white/70 p-3">
      <div class="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
        <span>録画タイムライン</span>
        <span>
          {#if episodeIndex != null}
            エピソード {Number(episodeIndex) + 1}{episodeTotal ? ` / ${episodeTotal}` : ''}
          {:else}
            エピソード待機中
          {/if}
        </span>
      </div>
      <div class="mt-3 h-3 w-full overflow-hidden rounded-full bg-slate-200/70">
        <div
          class={`h-full rounded-full transition ${
            timelineMode === 'reset'
              ? 'bg-amber-400'
              : timelineMode === 'finalizing'
                ? 'bg-sky-400 animate-pulse'
                : 'bg-brand'
          }`}
          style={`width: ${(timelineProgress * 100).toFixed(1)}%`}
        ></div>
      </div>
      <div class="mt-2 flex justify-between text-[10px] text-slate-500">
        <span>
          {#if timelineMode === 'finalizing'}
            {formatSeconds(timelineElapsed)}
          {:else}
            {formatSeconds(timelineElapsed)}
          {/if}
        </span>
        <span>
          {#if timelineMode === 'finalizing'}
            エピソード保存中
          {:else}
            {formatSeconds(timelineTotal)}
          {/if}
        </span>
      </div>
    </div>

    {#if statusDetail}
      <p class="text-xs text-slate-500">{statusDetail}</p>
    {/if}
  {/if}
</div>

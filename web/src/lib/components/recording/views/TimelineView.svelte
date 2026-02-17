<script lang="ts">
  let {
    title = 'Timeline',
    mode = 'recording',
    recorderStatus = null,
    rosbridgeStatus = 'idle'
  }: {
    title?: string;
    mode?: 'recording' | 'operate';
    recorderStatus?: Record<string, unknown> | null;
    rosbridgeStatus?: 'idle' | 'connecting' | 'connected' | 'disconnected' | 'error';
  } = $props();

  const asNumber = (value: unknown, fallback = 0) => {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  };

  const status = $derived(recorderStatus ?? {});
  const statusPhase = $derived(String((status as Record<string, unknown>)?.phase ?? 'wait'));
  const statusDetail = $derived(String((status as Record<string, unknown>)?.last_error ?? ''));
  const episodeIndex = $derived((status as Record<string, unknown>)?.episode_index ?? null);
  const episodeTotal = $derived(asNumber((status as Record<string, unknown>)?.num_episodes ?? 0));
  const episodeTime = $derived(asNumber((status as Record<string, unknown>)?.episode_time_s ?? 0));
  const episodeElapsed = $derived(asNumber((status as Record<string, unknown>)?.episode_elapsed_s ?? 0));
  const resetTime = $derived(asNumber((status as Record<string, unknown>)?.reset_time_s ?? 0));
  const resetElapsed = $derived(asNumber((status as Record<string, unknown>)?.reset_elapsed_s ?? 0));

  const timelineMode = $derived(
    statusPhase === 'recording' ? 'recording' : statusPhase === 'reset' ? 'reset' : 'wait'
  );
  const timelineTotal = $derived(
    timelineMode === 'recording' ? episodeTime : timelineMode === 'reset' ? resetTime : 0
  );
  const timelineElapsed = $derived(
    timelineMode === 'recording' ? episodeElapsed : timelineMode === 'reset' ? resetElapsed : 0
  );
  const timelineProgress = $derived(
    timelineTotal > 0 ? Math.min(Math.max(timelineElapsed / timelineTotal, 0), 1) : 0
  );
  const timelineLabel = $derived(
    timelineMode === 'recording' ? '録画中' : timelineMode === 'reset' ? 'リセット中' : '待機中'
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
          class={`h-full rounded-full transition ${timelineMode === 'reset' ? 'bg-amber-400' : 'bg-brand'}`}
          style={`width: ${(timelineProgress * 100).toFixed(1)}%`}
        ></div>
      </div>
      <div class="mt-2 flex justify-between text-[10px] text-slate-500">
        <span>{formatSeconds(timelineElapsed)}</span>
        <span>{formatSeconds(timelineTotal)}</span>
      </div>
    </div>

    {#if statusDetail}
      <p class="text-xs text-slate-500">{statusDetail}</p>
    {/if}
  {/if}
</div>

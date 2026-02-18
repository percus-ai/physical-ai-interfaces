<script lang="ts">
  import {
    subscribeRecorderStatus,
    type RecorderStatus,
    type RosbridgeStatus
  } from '$lib/recording/recorderStatus';

  let {
    sessionId = '',
    title = 'Progress',
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
  const episodeCountValue = $derived(asNumber((status as Record<string, unknown>)?.episode_count ?? 0, 0));
  const numEpisodes = $derived(asNumber((status as Record<string, unknown>)?.num_episodes ?? 0, 0));
  const frameCount = $derived(asNumber((status as Record<string, unknown>)?.frame_count ?? 0, 0));
  const episodeFrameCount = $derived(asNumber((status as Record<string, unknown>)?.episode_frame_count ?? 0, 0));
  const episodeTime = $derived(asNumber((status as Record<string, unknown>)?.episode_time_s ?? 0, 0));
  const resetTime = $derived(asNumber((status as Record<string, unknown>)?.reset_time_s ?? 0, 0));
  const episodeElapsed = $derived(asNumber((status as Record<string, unknown>)?.episode_elapsed_s ?? 0, 0));
  const episodeRemaining = $derived(asNumber((status as Record<string, unknown>)?.episode_remaining_s ?? 0, 0));
  const resetElapsed = $derived(asNumber((status as Record<string, unknown>)?.reset_elapsed_s ?? 0, 0));
  const resetRemaining = $derived(asNumber((status as Record<string, unknown>)?.reset_remaining_s ?? 0, 0));
  const statusDatasetId = $derived.by(() => {
    const value = (status as Record<string, unknown>)?.dataset_id;
    return typeof value === 'string' ? value : '';
  });
  const statusState = $derived.by(() => {
    const state = (status as Record<string, unknown>)?.state ?? (status as Record<string, unknown>)?.status ?? '';
    if (!sessionId) return String(state);
    if (!statusDatasetId || statusDatasetId !== sessionId) return 'inactive';
    return String(state);
  });
  const episodeDisplayNumber = $derived.by(() => {
    if (numEpisodes <= 0) return '-';
    const state = String(statusState);
    const base = Math.max(episodeCountValue, 0);
    const value = state === 'recording' || state === 'paused' ? base + 1 : base;
    return String(Math.min(Math.max(value, 1), numEpisodes));
  });
  const progress = $derived(numEpisodes > 0 ? Math.min(episodeCountValue / numEpisodes, 1) : 0);
  const connectionWarning = $derived(
    rosbridgeStatus !== 'connected' ? 'rosbridge が切断されています。状態は更新されません。' : ''
  );

  let fps = $state(0);
  let fpsSamples: { t: number; frames: number }[] = [];
  let lastFpsFrameCount: number | null = null;
  const fpsDisplay = $derived(fps > 0 ? fps.toFixed(1) : '-');
  const FPS_WINDOW_MS = 2000;
  const FPS_EMA_ALPHA = 0.15;

  $effect(() => {
    const now = performance.now();
    const totalFrames = frameCount;
    const state = String(statusState);
    const isRecording = state === 'recording';

    if (!isRecording) {
      fps = 0;
      fpsSamples = [];
      lastFpsFrameCount = null;
      return;
    }

    if (lastFpsFrameCount != null && totalFrames === lastFpsFrameCount) {
      return;
    }

    const lastSample = fpsSamples.length ? fpsSamples[fpsSamples.length - 1] : null;
    if (lastSample && totalFrames < lastSample.frames) {
      // Frame counter was reset (retake/restart). Restart FPS window.
      fpsSamples = [];
    }

    fpsSamples = [...fpsSamples, { t: now, frames: totalFrames }].filter((sample) => now - sample.t <= FPS_WINDOW_MS);
    lastFpsFrameCount = totalFrames;
    if (fpsSamples.length < 2) {
      return;
    }

    const first = fpsSamples[0];
    const last = fpsSamples[fpsSamples.length - 1];
    const elapsedMs = last.t - first.t;
    const frameDelta = last.frames - first.frames;
    if (elapsedMs <= 0 || frameDelta < 0) {
      return;
    }

    const windowFps = (frameDelta * 1000) / elapsedMs;
    fps = fps > 0 ? fps * (1 - FPS_EMA_ALPHA) + windowFps * FPS_EMA_ALPHA : windowFps;
  });
</script>

<div class="flex h-full flex-col gap-3">
  <div class="flex items-center justify-between">
    <p class="text-xs font-semibold uppercase tracking-widest text-slate-500">{title}</p>
    <span class="text-[10px] text-slate-400">{Math.round(progress * 100)}%</span>
  </div>
  {#if mode !== 'recording'}
    <div class="rounded-2xl border border-amber-200/70 bg-amber-50/60 p-3 text-xs text-amber-700">
      このビューはデータセット収録のみ対応しています。
    </div>
  {:else}
    {#if connectionWarning}
      <p class="mb-2 text-xs text-amber-600">{connectionWarning}</p>
    {/if}
    <div class="rounded-2xl border border-slate-200/60 bg-white/70 p-3">
      <div class="flex items-center justify-between text-xs text-slate-500">
        <span>Episode {episodeDisplayNumber}</span>
        <span>{numEpisodes ? `${episodeCountValue}/${numEpisodes}` : '-'}</span>
      </div>
      <div class="mt-2 h-2 w-full rounded-full bg-slate-100">
        <div class="h-2 rounded-full bg-brand transition" style={`width: ${Math.min(progress * 100, 100)}%`}></div>
      </div>
      <div class="mt-3 grid gap-2 text-xs text-slate-600 sm:grid-cols-2">
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-2">
          <p class="label">frame</p>
          <p class="mt-1 text-sm font-semibold text-slate-800">{frameCount}</p>
          <p class="text-[11px] text-slate-500">current ep: {episodeFrameCount} ({fpsDisplay} fps)</p>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-2">
          <p class="label">episode time</p>
          <p class="mt-1 text-sm font-semibold text-slate-800">{episodeTime || '-'}s</p>
          <p class="text-[11px] text-slate-500">{episodeElapsed.toFixed(1)}s / 残り{episodeRemaining.toFixed(1)}s</p>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-2">
          <p class="label">reset</p>
          <p class="mt-1 text-sm font-semibold text-slate-800">{resetTime || '-'}s</p>
          <p class="text-[11px] text-slate-500">{resetElapsed.toFixed(1)}s / 残り{resetRemaining.toFixed(1)}s</p>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-2">
          <p class="label">state</p>
          <p class="mt-1 text-sm font-semibold text-slate-800">{statusState || '-'}</p>
        </div>
      </div>
    </div>
  {/if}
</div>

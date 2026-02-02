<script lang="ts">
  import { createQuery } from '@tanstack/svelte-query';
  import { derived, writable } from 'svelte/store';
  import { api } from '$lib/api/client';

  export let sessionId = '';
  export let title = 'Progress';
  export let mode: 'recording' | 'operate' = 'recording';

  type RecordingSessionStatusResponse = {
    dataset_id?: string;
    status?: Record<string, unknown>;
  };

  const sessionIdStore = writable(sessionId);
  $: sessionIdStore.set(sessionId);

  const statusQuery = createQuery<RecordingSessionStatusResponse>(
    derived(sessionIdStore, ($sessionId) => ({
      queryKey: ['recording', 'session', $sessionId],
      queryFn: () => api.recording.sessionStatus($sessionId),
      enabled: Boolean($sessionId)
    }))
  );

  const asNumber = (value: unknown, fallback = 0) => {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  };

  $: status = $statusQuery.data?.status ?? {};
  $: episodeIndex = asNumber((status as Record<string, unknown>)?.episode_index ?? 0, 0);
  $: episodeCountValue = asNumber((status as Record<string, unknown>)?.episode_count ?? 0, 0);
  $: numEpisodes = asNumber((status as Record<string, unknown>)?.num_episodes ?? 0, 0);
  $: frameCount = asNumber((status as Record<string, unknown>)?.frame_count ?? 0, 0);
  $: episodeTime = asNumber((status as Record<string, unknown>)?.episode_time_s ?? 0, 0);
  $: resetTime = asNumber((status as Record<string, unknown>)?.reset_time_s ?? 0, 0);
  $: statusState =
    (status as Record<string, unknown>)?.state ?? (status as Record<string, unknown>)?.status ?? '';
  $: progress = numEpisodes > 0 ? Math.min(episodeCountValue / numEpisodes, 1) : 0;
</script>

<div class="flex h-full flex-col gap-3">
  <div class="flex items-center justify-between">
    <p class="text-xs font-semibold uppercase tracking-widest text-slate-500">{title}</p>
    <span class="text-[10px] text-slate-400">{Math.round(progress * 100)}%</span>
  </div>
  {#if mode !== 'recording'}
    <div class="rounded-2xl border border-amber-200/70 bg-amber-50/60 p-3 text-xs text-amber-700">
      このビューは録画セッションのみ対応しています。
    </div>
  {:else}
    <div class="rounded-2xl border border-slate-200/60 bg-white/70 p-3">
      <div class="flex items-center justify-between text-xs text-slate-500">
        <span>Episode {numEpisodes ? Math.max(episodeIndex, 0) + 1 : '-'}</span>
        <span>{numEpisodes ? `${episodeCountValue}/${numEpisodes}` : '-'}</span>
      </div>
      <div class="mt-2 h-2 w-full rounded-full bg-slate-100">
        <div class="h-2 rounded-full bg-brand transition" style={`width: ${Math.min(progress * 100, 100)}%`}></div>
      </div>
      <div class="mt-3 grid gap-2 text-xs text-slate-600 sm:grid-cols-2">
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-2">
          <p class="label">frame</p>
          <p class="mt-1 text-sm font-semibold text-slate-800">{frameCount}</p>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-2">
          <p class="label">episode time</p>
          <p class="mt-1 text-sm font-semibold text-slate-800">{episodeTime || '-'}s</p>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-2">
          <p class="label">reset</p>
          <p class="mt-1 text-sm font-semibold text-slate-800">{resetTime || '-'}s</p>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-2">
          <p class="label">state</p>
          <p class="mt-1 text-sm font-semibold text-slate-800">{statusState || '-'}</p>
        </div>
      </div>
    </div>
  {/if}
</div>

<script lang="ts">
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { formatBytes, formatDate } from '$lib/format';
  import OperateStatusCards from '$lib/components/OperateStatusCards.svelte';
  import { getRosbridgeClient } from '$lib/recording/rosbridge';
  import ActiveSessionSection from '$lib/components/ActiveSessionSection.svelte';
  import ActiveSessionCard from '$lib/components/ActiveSessionCard.svelte';

  type RecordingSummary = {
    recording_id: string;
    dataset_name?: string;
    task?: string;
    profile_name?: string;
    created_at?: string;
    episode_count?: number;
    target_total_episodes?: number;
    remaining_episodes?: number;
    episode_time_s?: number;
    reset_time_s?: number;
    continuable?: boolean;
    continue_block_reason?: string;
    size_bytes?: number;
  };

  type RecordingListResponse = {
    recordings?: RecordingSummary[];
    total?: number;
  };

  type OperateStatusResponse = {
    backend?: { status?: string; message?: string };
    vlabor?: { status?: string; message?: string };
    lerobot?: { status?: string; message?: string };
    network?: { status?: string; message?: string };
    driver?: { status?: string; message?: string };
  };

  type RecorderStatus = {
    state?: string;
    dataset_id?: string;
    task?: string;
    episode_index?: number | null;
    num_episodes?: number;
    frame_count?: number;
    episode_frame_count?: number;
    last_frame_at?: string | null;
  };

  const recordingsQuery = createQuery<RecordingListResponse>({
    queryKey: ['recording', 'recordings'],
    queryFn: () => api.recording.list()
  });

  const operateStatusQuery = createQuery<OperateStatusResponse>({
    queryKey: ['operate', 'status'],
    queryFn: api.operate.status
  });

  const recordings = $derived($recordingsQuery.data?.recordings ?? []);

  const STATUS_TOPIC = '/lerobot_recorder/status';
  const STATUS_THROTTLE_MS = 66;
  const STATUS_LABELS: Record<string, string> = {
    idle: '待機',
    warming: '準備中',
    recording: '録画中',
    paused: '一時停止',
    resetting: 'リセット中',
    inactive: '停止',
    completed: '完了',
    failed: '失敗'
  };

  let recorderStatus = $state<RecorderStatus | null>(null);
  let rosbridgeStatus = $state<'idle' | 'connecting' | 'connected' | 'disconnected' | 'error'>('idle');
  let lastStatusAt = $state('');

  const parseRecorderPayload = (msg: Record<string, unknown>): RecorderStatus => {
    if (typeof msg.data === 'string') {
      try {
        return JSON.parse(msg.data) as RecorderStatus;
      } catch {
        return { state: 'unknown' };
      }
    }
    return msg as RecorderStatus;
  };

  $effect(() => {
    if (typeof window === 'undefined') return;
    const client = getRosbridgeClient();
    const unsubscribe = client.subscribe(
      STATUS_TOPIC,
      (message) => {
        recorderStatus = parseRecorderPayload(message);
        lastStatusAt = new Date().toLocaleTimeString();
      },
      { throttle_rate: STATUS_THROTTLE_MS }
    );
    const offStatus = client.onStatusChange((next) => {
      rosbridgeStatus = next;
    });
    rosbridgeStatus = client.getStatus();
    return () => {
      unsubscribe();
      offStatus();
    };
  });

  const activeSessionId = $derived(recorderStatus?.dataset_id ?? '');
  const activeSessionState = $derived(recorderStatus?.state ?? 'unknown');
  const activeSessionLabel = $derived(STATUS_LABELS[activeSessionState] ?? activeSessionState);
  const activeEpisodeIndex = $derived(
    recorderStatus?.episode_index != null ? recorderStatus.episode_index + 1 : null
  );
  const activeEpisodeTotal = $derived(recorderStatus?.num_episodes ?? null);
  const activeFrameCount = $derived(recorderStatus?.frame_count ?? null);
  const activeEpisodeFrameCount = $derived(recorderStatus?.episode_frame_count ?? null);
  const rawStatus = $derived(recorderStatus ? JSON.stringify(recorderStatus, null, 2) : '');

</script>

<section class="card-strong p-8">
  <p class="section-title">Record</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">データ録画</h1>
      <p class="mt-2 text-sm text-slate-600">録画セッションの状況を表示します。</p>
    </div>
    <Button.Root class="btn-primary" href="/record/new">新規セッションを作成</Button.Root>
  </div>
</section>

<ActiveSessionSection title="稼働中セッション" description="現在稼働中の録画セッションを表示します。">
  <ActiveSessionCard>
    {#if activeSessionId}
      {#if rosbridgeStatus !== 'connected'}
        <p class="text-xs text-rose-600">rosbridge が切断されています。状態は更新されません。</p>
      {/if}
      <div class="flex flex-wrap items-center gap-3 text-sm text-slate-700">
        <span class="chip">状態: {activeSessionLabel}</span>
        <span class="chip">Session: {activeSessionId}</span>
        {#if activeEpisodeIndex}
          <span class="chip">
            Episode: {activeEpisodeIndex}{activeEpisodeTotal ? ` / ${activeEpisodeTotal}` : ''}
          </span>
        {/if}
        {#if activeFrameCount != null}
          <span class="chip">Frames: {activeFrameCount}</span>
        {/if}
        {#if activeEpisodeFrameCount != null}
          <span class="chip">Episode Frames: {activeEpisodeFrameCount}</span>
        {/if}
        {#if recorderStatus?.last_frame_at}
          <span class="chip">Last: {formatDate(recorderStatus.last_frame_at)}</span>
        {/if}
        <span class="chip">更新: {lastStatusAt || '-'}</span>
        <a class="btn-ghost px-3 py-1 text-xs" href={`/record/sessions/${activeSessionId}`}>詳細を見る</a>
      </div>
      <details class="mt-3 rounded-xl border border-slate-200/60 bg-white/70 p-3 text-xs text-slate-600">
        <summary class="cursor-pointer text-slate-500">状態の生データ</summary>
        <pre class="mt-2 whitespace-pre-wrap text-[11px] text-slate-700">{rawStatus || '-'}</pre>
      </details>
    {:else}
      <p class="text-sm text-slate-500">稼働中のセッションはありません。</p>
    {/if}
  </ActiveSessionCard>
</ActiveSessionSection>

<section class="card p-6">
  <div class="flex items-center justify-between">
    <div>
      <h2 class="text-xl font-semibold text-slate-900">セッション履歴</h2>
      <p class="text-sm text-slate-600">録画済みセッションの履歴です。</p>
    </div>
    <Button.Root class="btn-ghost" type="button" onclick={() => $recordingsQuery.refetch?.()}>更新</Button.Root>
  </div>
  <div class="mt-4 overflow-x-auto">
    <table class="min-w-full text-sm">
      <thead class="text-left text-xs uppercase tracking-widest text-slate-400">
        <tr>
          <th class="pb-3">セッション</th>
          <th class="pb-3">プロフィール</th>
          <th class="pb-3">エピソード</th>
          <th class="pb-3">サイズ</th>
          <th class="pb-3">作成日時</th>
        </tr>
      </thead>
      <tbody class="text-slate-600">
        {#if $recordingsQuery.isLoading}
          <tr><td class="py-3" colspan="5">読み込み中...</td></tr>
        {:else if recordings.length}
          {#each recordings as recording}
            <tr class="border-t border-slate-200/60">
              <td class="py-3">
                {#if recording.continuable}
                  <a class="text-brand underline" href={`/record/sessions/${encodeURIComponent(recording.recording_id)}`}>
                    {recording.dataset_name ?? recording.recording_id}
                  </a>
                {:else}
                  <span class="text-slate-500">{recording.dataset_name ?? recording.recording_id}</span>
                  {#if recording.continue_block_reason}
                    <p class="mt-1 text-[11px] text-slate-400">{recording.continue_block_reason}</p>
                  {/if}
                {/if}
              </td>
              <td class="py-3">{recording.profile_name ?? '-'}</td>
              <td class="py-3">{recording.episode_count ?? '-'}</td>
              <td class="py-3">{formatBytes(recording.size_bytes ?? 0)}</td>
              <td class="py-3">{formatDate(recording.created_at)}</td>
            </tr>
          {/each}
        {:else}
          <tr><td class="py-3" colspan="5">録画がありません。</td></tr>
        {/if}
      </tbody>
    </table>
  </div>
</section>

<OperateStatusCards status={$operateStatusQuery.data} />

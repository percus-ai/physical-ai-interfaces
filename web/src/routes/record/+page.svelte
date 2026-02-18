<script lang="ts">
  import { onDestroy } from 'svelte';
  import { Button, DropdownMenu } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import toast from 'svelte-french-toast';
  import DotsThree from 'phosphor-svelte/lib/DotsThree';
  import { api } from '$lib/api/client';
  import { formatBytes, formatDate } from '$lib/format';
  import { connectStream } from '$lib/realtime/stream';
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
    is_local?: boolean;
  };

  type RecordingListResponse = {
    recordings?: RecordingSummary[];
    total?: number;
  };

  type RecordingUploadStatus = {
    dataset_id: string;
    status: 'idle' | 'running' | 'completed' | 'failed' | 'disabled' | string;
    phase: string;
    progress_percent: number;
    message: string;
    files_done: number;
    total_files: number;
    current_file?: string | null;
    error?: string | null;
    updated_at?: string | null;
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
  let reuploadBusy = $state<Record<string, boolean>>({});
  let archiveBusy = $state<Record<string, boolean>>({});
  let uploadStatusMap = $state<Record<string, RecordingUploadStatus>>({});
  const uploadStreamStops = new Map<string, () => void>();

  const UPLOAD_STATUS_LABELS: Record<string, string> = {
    idle: '未開始',
    running: 'アップロード中',
    completed: '完了',
    failed: '失敗',
    disabled: '無効'
  };

  const setReuploadBusy = (recordingId: string, busy: boolean) => {
    reuploadBusy = {
      ...reuploadBusy,
      [recordingId]: busy
    };
  };

  const isReuploadBusy = (recordingId: string) => Boolean(reuploadBusy[recordingId]);
  const setArchiveBusy = (recordingId: string, busy: boolean) => {
    archiveBusy = {
      ...archiveBusy,
      [recordingId]: busy
    };
  };
  const isArchiveBusy = (recordingId: string) => Boolean(archiveBusy[recordingId]);
  const isTerminalUploadStatus = (status: string) =>
    status === 'completed' || status === 'failed' || status === 'disabled';

  const normalizeUploadStatus = (recordingId: string, status?: Partial<RecordingUploadStatus>) => ({
    dataset_id: recordingId,
    status: status?.status ?? 'idle',
    phase: status?.phase ?? 'idle',
    progress_percent: Number(status?.progress_percent ?? 0),
    message: status?.message ?? '',
    files_done: Number(status?.files_done ?? 0),
    total_files: Number(status?.total_files ?? 0),
    current_file: status?.current_file ?? null,
    error: status?.error ?? null,
    updated_at: status?.updated_at ?? null
  });

  const setUploadStatus = (recordingId: string, status: RecordingUploadStatus) => {
    const previous = uploadStatusMap[recordingId];
    uploadStatusMap = {
      ...uploadStatusMap,
      [recordingId]: status
    };
    if (isTerminalUploadStatus(status.status) && previous?.status !== status.status) {
      void $recordingsQuery.refetch?.();
    }
  };

  const stopUploadStream = (recordingId: string) => {
    const stop = uploadStreamStops.get(recordingId);
    if (!stop) return;
    stop();
    uploadStreamStops.delete(recordingId);
  };

  const ensureUploadStream = (recordingId: string) => {
    if (!recordingId || uploadStreamStops.has(recordingId)) return;
    const stop = connectStream<RecordingUploadStatus>({
      path: `/api/stream/recording/sessions/${encodeURIComponent(recordingId)}/upload-status`,
      onMessage: (payload) => {
        const normalized = normalizeUploadStatus(recordingId, payload);
        setUploadStatus(recordingId, normalized);
        if (isTerminalUploadStatus(normalized.status) && !isReuploadBusy(recordingId)) {
          window.setTimeout(() => {
            if (!isReuploadBusy(recordingId)) {
              stopUploadStream(recordingId);
            }
          }, 5000);
        }
      }
    });
    uploadStreamStops.set(recordingId, stop);
  };

  const uploadStatusLabel = (recordingId: string) => {
    const status = uploadStatusMap[recordingId];
    if (!status) return '-';
    const label = UPLOAD_STATUS_LABELS[status.status] ?? status.status;
    if (status.status === 'running') {
      const progress = Number.isFinite(status.progress_percent)
        ? `${Math.max(0, Math.min(100, status.progress_percent)).toFixed(1)}%`
        : '0.0%';
      return `${label} (${progress})`;
    }
    return label;
  };

  const reuploadRecording = async (recording: RecordingSummary) => {
    const recordingId = String(recording.recording_id || '').trim();
    if (!recordingId || !recording.is_local || isReuploadBusy(recordingId)) return;
    ensureUploadStream(recordingId);
    setUploadStatus(
      recordingId,
      normalizeUploadStatus(recordingId, {
        status: 'running',
        phase: 'starting',
        progress_percent: 0,
        message: 'Re-uploading dataset to R2...'
      })
    );
    setReuploadBusy(recordingId, true);
    try {
      await api.storage.reuploadDataset(recordingId);
      toast.success('再アップロードを受け付けました。');
    } catch (err) {
      const message = err instanceof Error ? err.message : '再アップロードに失敗しました。';
      setUploadStatus(
        recordingId,
        normalizeUploadStatus(recordingId, {
          status: 'failed',
          phase: 'failed',
          message,
          error: message
        })
      );
      toast.error(message);
    } finally {
      setReuploadBusy(recordingId, false);
      const latest = uploadStatusMap[recordingId];
      if (latest && isTerminalUploadStatus(latest.status)) {
        window.setTimeout(() => {
          if (!isReuploadBusy(recordingId)) {
            stopUploadStream(recordingId);
          }
        }, 5000);
      }
    }
  };

  const archiveRecording = async (recording: RecordingSummary) => {
    const recordingId = String(recording.recording_id || '').trim();
    if (!recordingId || isArchiveBusy(recordingId) || isReuploadBusy(recordingId)) return;
    setArchiveBusy(recordingId, true);
    try {
      await api.storage.archiveDataset(recordingId);
      stopUploadStream(recordingId);
      uploadStatusMap = {
        ...uploadStatusMap,
        [recordingId]: normalizeUploadStatus(recordingId, { status: 'idle', phase: 'idle' })
      };
      toast.success('アーカイブしました。');
      await $recordingsQuery.refetch?.();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'アーカイブに失敗しました。';
      toast.error(message);
    } finally {
      setArchiveBusy(recordingId, false);
    }
  };

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

  $effect(() => {
    const currentIds = new Set(recordings.map((recording) => String(recording.recording_id || '').trim()));
    for (const recordingId of Array.from(uploadStreamStops.keys())) {
      if (!currentIds.has(recordingId)) {
        stopUploadStream(recordingId);
      }
    }
  });

  onDestroy(() => {
    for (const stop of uploadStreamStops.values()) {
      stop();
    }
    uploadStreamStops.clear();
  });

</script>

<section class="card-strong p-8">
  <p class="section-title">Record</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">データ録画</h1>
      <p class="mt-2 text-sm text-slate-600">データセット収録の状況を表示します。</p>
    </div>
    <Button.Root class="btn-primary" href="/record/new">新規データセットを作成</Button.Root>
  </div>
</section>

<ActiveSessionSection title="稼働中データセット" description="現在収録中のデータセットを表示します。">
  <ActiveSessionCard>
    {#if activeSessionId}
      {#if rosbridgeStatus !== 'connected'}
        <p class="text-xs text-rose-600">rosbridge が切断されています。状態は更新されません。</p>
      {/if}
      <div class="flex flex-wrap items-center gap-3 text-sm text-slate-700">
        <span class="chip">状態: {activeSessionLabel}</span>
        <span class="chip">Dataset: {activeSessionId}</span>
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
        <a class="btn-ghost px-3 py-1 text-xs" href={`/record/sessions/${activeSessionId}`}>収録を開く</a>
      </div>
      <details class="mt-3 rounded-xl border border-slate-200/60 bg-white/70 p-3 text-xs text-slate-600">
        <summary class="cursor-pointer text-slate-500">状態の生データ</summary>
        <pre class="mt-2 whitespace-pre-wrap text-[11px] text-slate-700">{rawStatus || '-'}</pre>
      </details>
    {:else}
      <p class="text-sm text-slate-500">稼働中のデータセットはありません。</p>
    {/if}
  </ActiveSessionCard>
</ActiveSessionSection>

<section class="card p-6">
  <div class="flex items-center justify-between">
    <div>
      <h2 class="text-xl font-semibold text-slate-900">データセット履歴</h2>
      <p class="text-sm text-slate-600">収録済みデータセットの履歴です。</p>
    </div>
    <Button.Root class="btn-ghost" type="button" onclick={() => $recordingsQuery.refetch?.()}>更新</Button.Root>
  </div>
  <div class="mt-4 overflow-x-auto">
    <table class="min-w-full text-sm">
      <thead class="text-left text-xs uppercase tracking-widest text-slate-400">
        <tr>
          <th class="pb-3">データセット</th>
          <th class="pb-3">プロフィール</th>
          <th class="pb-3">エピソード</th>
          <th class="pb-3">アップロード</th>
          <th class="pb-3">サイズ</th>
          <th class="pb-3">作成日時</th>
          <th class="pb-3 text-right">操作</th>
        </tr>
      </thead>
      <tbody class="text-slate-600">
        {#if $recordingsQuery.isLoading}
          <tr><td class="py-3" colspan="7">読み込み中...</td></tr>
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
              <td class="py-3">
                <div class="flex flex-col gap-1">
                  <span
                    class={`text-xs font-semibold ${
                      uploadStatusMap[recording.recording_id]?.status === 'failed'
                        ? 'text-rose-600'
                        : uploadStatusMap[recording.recording_id]?.status === 'completed'
                          ? 'text-emerald-600'
                          : uploadStatusMap[recording.recording_id]?.status === 'running'
                            ? 'text-amber-600'
                            : 'text-slate-500'
                    }`}
                  >
                    {uploadStatusLabel(recording.recording_id)}
                  </span>
                  {#if uploadStatusMap[recording.recording_id]?.status === 'running' && uploadStatusMap[recording.recording_id]?.current_file}
                    <span class="max-w-[200px] truncate text-[10px] text-slate-400">
                      {uploadStatusMap[recording.recording_id]?.current_file}
                    </span>
                  {/if}
                  {#if uploadStatusMap[recording.recording_id]?.status === 'failed' && uploadStatusMap[recording.recording_id]?.error}
                    <span class="max-w-[260px] truncate text-[10px] text-rose-500">
                      {uploadStatusMap[recording.recording_id]?.error}
                    </span>
                  {/if}
                </div>
              </td>
              <td class="py-3">{formatBytes(recording.size_bytes ?? 0)}</td>
              <td class="py-3">{formatDate(recording.created_at)}</td>
              <td class="py-3 text-right">
                <DropdownMenu.Root>
                  <DropdownMenu.Trigger
                    class="btn-ghost ml-auto h-8 w-8 p-0 text-slate-600"
                    aria-label="操作メニュー"
                    title="操作"
                  >
                    <DotsThree size={18} weight="bold" />
                  </DropdownMenu.Trigger>
                  <DropdownMenu.Portal>
                    <DropdownMenu.Content
                      class="z-50 min-w-[180px] rounded-xl border border-slate-200/80 bg-white/95 p-2 text-xs text-slate-700 shadow-lg backdrop-blur"
                      sideOffset={6}
                      align="end"
                    >
                      <DropdownMenu.Item
                        class="flex items-center rounded-lg px-3 py-2 font-semibold text-slate-700 data-[disabled]:cursor-not-allowed data-[disabled]:text-slate-400 hover:bg-slate-100 data-[disabled]:hover:bg-transparent"
                        disabled={!recording.is_local || isReuploadBusy(recording.recording_id)}
                        closeOnSelect={false}
                        onSelect={() => reuploadRecording(recording)}
                      >
                        {#if isReuploadBusy(recording.recording_id)}
                          {uploadStatusLabel(recording.recording_id)}
                        {:else}
                          再アップロード
                        {/if}
                      </DropdownMenu.Item>
                      <DropdownMenu.Item
                        class="flex items-center rounded-lg px-3 py-2 font-semibold text-rose-600 data-[disabled]:cursor-not-allowed data-[disabled]:text-slate-400 hover:bg-slate-100 data-[disabled]:hover:bg-transparent"
                        disabled={isArchiveBusy(recording.recording_id) || isReuploadBusy(recording.recording_id)}
                        onSelect={() => archiveRecording(recording)}
                      >
                        {#if isArchiveBusy(recording.recording_id)}
                          アーカイブ中...
                        {:else}
                          アーカイブ
                        {/if}
                      </DropdownMenu.Item>
                      {#if uploadStatusMap[recording.recording_id]?.status === 'running'}
                        <div class="px-3 pb-1 pt-0.5 text-[10px] text-slate-400">
                          {uploadStatusMap[recording.recording_id]?.message || 'アップロード中...'}
                        </div>
                      {/if}
                      {#if !recording.is_local}
                        <div class="px-3 pb-1 pt-0.5 text-[10px] text-slate-400">
                          ローカルデータがないため実行できません
                        </div>
                      {/if}
                    </DropdownMenu.Content>
                  </DropdownMenu.Portal>
                </DropdownMenu.Root>
              </td>
            </tr>
          {/each}
        {:else}
          <tr><td class="py-3" colspan="7">録画がありません。</td></tr>
        {/if}
      </tbody>
    </table>
  </div>
</section>

<OperateStatusCards status={$operateStatusQuery.data} />

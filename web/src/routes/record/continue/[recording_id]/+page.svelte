<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { Button } from 'bits-ui';
  import { toStore } from 'svelte/store';
  import { createQuery } from '@tanstack/svelte-query';
  import {
    api,
    type StartupOperationAcceptedResponse,
    type StartupOperationStatusResponse
  } from '$lib/api/client';
  import { connectStream } from '$lib/realtime/stream';

  const START_PHASE_LABELS: Record<string, string> = {
    queued: 'キュー待機',
    resolve_profile: 'プロファイル解決',
    start_lerobot: 'Lerobot起動',
    prepare_recorder: '録画準備',
    persist: '状態保存',
    done: '完了',
    error: '失敗'
  };

  type RecordingContinuePlan = {
    recording_id: string;
    dataset_name: string;
    task: string;
    profile_name?: string | null;
    episode_count: number;
    target_total_episodes: number;
    remaining_episodes: number;
    episode_time_s: number;
    reset_time_s: number;
    continuable: boolean;
    reason?: string | null;
  };

  const formatBytes = (bytes?: number) => {
    const value = Number(bytes ?? 0);
    if (!Number.isFinite(value) || value <= 0) return '0 B';
    if (value >= 1024 * 1024 * 1024) return `${(value / (1024 * 1024 * 1024)).toFixed(2)} GB`;
    if (value >= 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(2)} MB`;
    if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${Math.round(value)} B`;
  };

  const parseNumber = (value: number | string) => {
    if (typeof value === 'number') return value;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : NaN;
  };

  const recordingId = $derived(page.params.recording_id ?? '');
  const continuePlanQuery = createQuery<RecordingContinuePlan>(
    toStore(() => ({
      queryKey: ['recording', 'continue-plan', recordingId],
      queryFn: () => api.recording.continuePlan(recordingId) as Promise<RecordingContinuePlan>,
      enabled: Boolean(recordingId)
    }))
  );

  const continuePlan = $derived($continuePlanQuery.data ?? null);
  const additionalEpisodes = $derived(continuePlan?.remaining_episodes ?? 0);
  const totalAfterContinue = $derived((continuePlan?.episode_count ?? 0) + additionalEpisodes);

  let episodeTimeSec = $state<number | string>(60);
  let resetWaitSec = $state<number | string>(10);
  let initialized = $state(false);

  let submitting = $state(false);
  let error = $state('');
  let startupStatus = $state<StartupOperationStatusResponse | null>(null);
  let startupStreamError = $state('');
  let stopStartupStream = () => {};

  const stopStartupStreamSubscription = () => {
    stopStartupStream();
    stopStartupStream = () => {};
  };

  const handleStartupStatusUpdate = async (status: StartupOperationStatusResponse) => {
    startupStatus = status;
    if (status.state === 'completed' && status.target_session_id) {
      stopStartupStreamSubscription();
      submitting = false;
      await goto(`/record/sessions/${encodeURIComponent(status.target_session_id)}`);
      return;
    }
    if (status.state === 'failed') {
      submitting = false;
      error = status.error ?? status.message ?? '継続録画セッションの作成に失敗しました。';
    }
  };

  const subscribeStartupStream = (operationId: string) => {
    stopStartupStreamSubscription();
    startupStreamError = '';
    stopStartupStream = connectStream<StartupOperationStatusResponse>({
      path: `/api/stream/startup/operations/${encodeURIComponent(operationId)}`,
      onMessage: (payload) => {
        void handleStartupStatusUpdate(payload);
      },
      onError: () => {
        startupStreamError = '進捗ストリームが一時的に不安定です。再接続します...';
      }
    });
  };

  const startupProgressPercent = $derived(
    Math.min(100, Math.max(0, Number(startupStatus?.progress_percent ?? 0)))
  );
  const startupState = $derived(startupStatus?.state ?? '');
  const startupActive = $derived(startupState === 'queued' || startupState === 'running');
  const showStartupBlock = $derived(Boolean(startupStatus) && (startupActive || startupState === 'failed'));
  const startupPhaseLabel = $derived(START_PHASE_LABELS[startupStatus?.phase ?? ''] ?? (startupStatus?.phase ?? '-'));
  const startupDetail = $derived(startupStatus?.detail ?? {});

  const handleSubmit = async (event?: Event) => {
    event?.preventDefault();
    error = '';
    startupStatus = null;
    startupStreamError = '';

    if (!continuePlan) {
      error = '継続情報を取得できません。';
      return;
    }
    if (!continuePlan.continuable || additionalEpisodes <= 0) {
      error = continuePlan.reason ?? 'このセッションは継続できません。';
      return;
    }

    const episodeTime = parseNumber(episodeTimeSec);
    const resetWait = parseNumber(resetWaitSec);
    if (!Number.isFinite(episodeTime) || episodeTime <= 0) {
      error = 'エピソード秒数は0より大きい数値にしてください。';
      return;
    }
    if (!Number.isFinite(resetWait) || resetWait < 0) {
      error = 'リセット待機秒数は0以上の数値にしてください。';
      return;
    }

    submitting = true;
    try {
      const payload = {
        dataset_name: continuePlan.dataset_name,
        task: continuePlan.task,
        num_episodes: additionalEpisodes,
        episode_time_s: episodeTime,
        reset_time_s: resetWait,
        continue_from_dataset_id: continuePlan.recording_id
      };
      const result = (await api.recording.createSession(payload)) as StartupOperationAcceptedResponse;
      if (!result?.operation_id) {
        throw new Error('開始オペレーションIDを取得できませんでした。');
      }
      subscribeStartupStream(result.operation_id);
      const snapshot = await api.startup.operation(result.operation_id);
      await handleStartupStatusUpdate(snapshot);
    } catch (err) {
      error = err instanceof Error ? err.message : '継続録画セッションの作成に失敗しました。';
      submitting = false;
    }
  };

  $effect(() => {
    if (!continuePlan || initialized) return;
    episodeTimeSec = continuePlan.episode_time_s;
    resetWaitSec = continuePlan.reset_time_s;
    initialized = true;
  });

  $effect(() => {
    recordingId;
    initialized = false;
  });

  $effect(() => {
    return () => {
      stopStartupStreamSubscription();
    };
  });
</script>

<section class="card-strong p-8">
  <p class="section-title">Record</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">継続録画セッション</h1>
      <p class="mt-2 text-sm text-slate-600">前回の続きから録画セッションを作成します。</p>
    </div>
    <Button.Root class="btn-ghost" href="/record">録画一覧に戻る</Button.Root>
  </div>
</section>

<section class="card p-6">
  {#if $continuePlanQuery.isLoading}
    <p class="text-sm text-slate-600">継続情報を読み込み中...</p>
  {:else if !continuePlan}
    <p class="text-sm text-rose-600">継続情報を取得できませんでした。</p>
  {:else}
    <form class="grid gap-4" onsubmit={handleSubmit}>
      <label class="text-sm font-semibold text-slate-700">
        <span class="label">データセット名</span>
        <input class="input mt-2 bg-slate-100/80" type="text" value={continuePlan.dataset_name} readonly />
      </label>
      <label class="text-sm font-semibold text-slate-700">
        <span class="label">タスク説明</span>
        <textarea class="input mt-2 min-h-[120px] bg-slate-100/80" readonly>{continuePlan.task}</textarea>
      </label>
      <label class="text-sm font-semibold text-slate-700">
        <span class="label">今回の追加エピソード数（固定）</span>
        <input class="input mt-2 bg-slate-100/80" type="number" value={additionalEpisodes} readonly />
      </label>
      <div class="rounded-xl border border-slate-200/70 bg-slate-50/70 p-3 text-sm text-slate-700">
        収録済み: {continuePlan.episode_count} / 目標: {continuePlan.target_total_episodes}
        <br />
        継続後合計: {totalAfterContinue} エピソード
      </div>
      <label class="text-sm font-semibold text-slate-700">
        <span class="label">エピソード秒数</span>
        <input class="input mt-2" type="number" min="1" step="1" bind:value={episodeTimeSec} required />
      </label>
      <label class="text-sm font-semibold text-slate-700">
        <span class="label">リセット待機秒数</span>
        <input class="input mt-2" type="number" min="0" step="0.5" bind:value={resetWaitSec} required />
      </label>

      {#if !continuePlan.continuable}
        <p class="text-sm text-rose-600">
          このセッションは継続できません。{continuePlan.reason ? `(${continuePlan.reason})` : ''}
        </p>
      {/if}

      {#if error}
        <p class="text-sm text-rose-600">{error}</p>
      {/if}

      {#if showStartupBlock}
        <div class="rounded-lg border border-emerald-200 bg-emerald-50/60 p-3">
          <div class="flex items-center justify-between gap-3 text-xs text-emerald-800">
            <p>{startupStatus?.message ?? '継続録画セッションを準備中です...'}</p>
            <p class="font-semibold">{Math.round(startupProgressPercent)}%</p>
          </div>
          <p class="mt-1 text-xs text-emerald-900/80">フェーズ: {startupPhaseLabel}</p>
          <div class="mt-2 h-2 overflow-hidden rounded-full bg-emerald-100">
            <div
              class="h-full rounded-full bg-emerald-500 transition-[width] duration-300"
              style={`width: ${startupProgressPercent}%;`}
            ></div>
          </div>
          {#if (startupDetail.total_files ?? 0) > 0 || (startupDetail.total_bytes ?? 0) > 0}
            <p class="mt-2 text-xs text-emerald-900/80">
              {startupDetail.files_done ?? 0}/{startupDetail.total_files ?? 0} files
              · {formatBytes(startupDetail.transferred_bytes)} / {formatBytes(startupDetail.total_bytes)}
              {#if startupDetail.current_file}
                · {startupDetail.current_file}
              {/if}
            </p>
          {/if}
          {#if startupStreamError}
            <p class="mt-2 text-xs text-amber-700">{startupStreamError}</p>
          {/if}
        </div>
      {/if}

      <div class="mt-2 flex flex-wrap gap-3">
        <Button.Root
          class="btn-primary"
          type="submit"
          disabled={submitting || startupActive || !continuePlan.continuable || additionalEpisodes <= 0}
          aria-busy={submitting || startupActive}
        >
          {startupActive ? '準備中...' : '録画セッションを作成'}
        </Button.Root>
        <Button.Root class="btn-ghost" href="/record">キャンセル</Button.Root>
      </div>
    </form>
  {/if}
</section>

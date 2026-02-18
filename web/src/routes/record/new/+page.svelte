<script lang="ts">
  import { goto } from '$app/navigation';
  import { Button } from 'bits-ui';
  import {
    api,
    type StartupOperationAcceptedResponse,
    type StartupOperationStatusResponse
  } from '$lib/api/client';
  import { connectStream } from '$lib/realtime/stream';

  const DATASET_NAME_PATTERN = /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/;
  const START_PHASE_LABELS: Record<string, string> = {
    queued: 'キュー待機',
    resolve_profile: 'プロファイル解決',
    start_lerobot: 'Lerobot起動',
    prepare_recorder: '録画準備',
    persist: '状態保存',
    done: '完了',
    error: '失敗'
  };

  const pad = (value: number) => String(value).padStart(2, '0');
  const buildDefaultName = () => {
    const now = new Date();
    return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(
      now.getMinutes()
    )}${pad(now.getSeconds())}`;
  };

  const formatBytes = (bytes?: number) => {
    const value = Number(bytes ?? 0);
    if (!Number.isFinite(value) || value <= 0) return '0 B';
    if (value >= 1024 * 1024 * 1024) return `${(value / (1024 * 1024 * 1024)).toFixed(2)} GB`;
    if (value >= 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(2)} MB`;
    if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${Math.round(value)} B`;
  };

  let datasetName = $state(buildDefaultName());
  let task = $state('');
  let episodeCount = $state<number | string>(1);
  let episodeTimeSec = $state<number | string>(60);
  let resetWaitSec = $state<number | string>(10);

  let submitting = $state(false);
  let error = $state('');
  let startupStatus = $state<StartupOperationStatusResponse | null>(null);
  let startupStreamError = $state('');
  let stopStartupStream = () => {};

  const validateDatasetName = (value: string) => {
    const trimmed = value.trim();
    const errors: string[] = [];
    if (!trimmed) {
      errors.push('データセット名を入力してください。');
      return errors;
    }
    if (trimmed.length > 64) {
      errors.push('データセット名は64文字以内にしてください。');
    }
    if (!DATASET_NAME_PATTERN.test(trimmed)) {
      errors.push('英数字で開始し、英数字・_・- のみ使用できます。');
    }
    const lower = trimmed.toLowerCase();
    if (lower.startsWith('archive') || lower.startsWith('temp') || trimmed.startsWith('_')) {
      errors.push('archive / temp / _ で始まる名前は使えません。');
    }
    if (trimmed.includes('..') || trimmed.includes('/') || trimmed.includes('\\')) {
      errors.push('パス区切りは使えません。');
    }
    return errors;
  };

  const parseNumber = (value: number | string) => {
    if (typeof value === 'number') return value;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : NaN;
  };

  const stopStartupStreamSubscription = () => {
    stopStartupStream();
    stopStartupStream = () => {};
  };

  const handleStartupStatusUpdate = async (status: StartupOperationStatusResponse) => {
    startupStatus = status;
    if (status.state === 'completed' && status.target_session_id) {
      stopStartupStreamSubscription();
      submitting = false;
      await goto(`/record/sessions/${status.target_session_id}`);
      return;
    }
    if (status.state === 'failed') {
      submitting = false;
      error = status.error ?? status.message ?? '収録データセットの作成に失敗しました。';
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

  const handleRegenerate = () => {
    datasetName = buildDefaultName();
  };

  const handleSubmit = async (event?: Event) => {
    event?.preventDefault();
    error = '';
    startupStatus = null;
    startupStreamError = '';

    const nameErrors = validateDatasetName(datasetName);
    if (nameErrors.length) {
      error = nameErrors[0];
      return;
    }
    if (!task.trim()) {
      error = 'タスク説明を入力してください。';
      return;
    }

    const episodes = Math.floor(parseNumber(episodeCount));
    const episodeTime = parseNumber(episodeTimeSec);
    const resetWait = parseNumber(resetWaitSec);
    if (!Number.isFinite(episodes) || episodes < 1) {
      error = 'エピソード総数は1以上の数値にしてください。';
      return;
    }
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
        dataset_name: datasetName.trim(),
        task: task.trim(),
        num_episodes: episodes,
        episode_time_s: episodeTime,
        reset_time_s: resetWait
      };
      const result = (await api.recording.createSession(payload)) as StartupOperationAcceptedResponse;
      if (!result?.operation_id) {
        throw new Error('開始オペレーションIDを取得できませんでした。');
      }
      subscribeStartupStream(result.operation_id);
      const snapshot = await api.startup.operation(result.operation_id);
      await handleStartupStatusUpdate(snapshot);
    } catch (err) {
      error = err instanceof Error ? err.message : '収録データセットの作成に失敗しました。';
      submitting = false;
    }
  };

  const startupProgressPercent = $derived(
    Math.min(100, Math.max(0, Number(startupStatus?.progress_percent ?? 0)))
  );
  const startupState = $derived(startupStatus?.state ?? '');
  const startupActive = $derived(startupState === 'queued' || startupState === 'running');
  const showStartupBlock = $derived(Boolean(startupStatus) && (startupActive || startupState === 'failed'));
  const startupPhaseLabel = $derived(START_PHASE_LABELS[startupStatus?.phase ?? ''] ?? (startupStatus?.phase ?? '-'));
  const startupDetail = $derived(startupStatus?.detail ?? {});

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
      <h1 class="text-3xl font-semibold text-slate-900">新規データセット収録</h1>
      <p class="mt-2 text-sm text-slate-600">新しい収録データセットを作成します。開始は次の画面で行います。</p>
    </div>
    <Button.Root class="btn-ghost" href="/record">録画一覧に戻る</Button.Root>
  </div>
</section>

<section class="card p-6">
  <form class="grid gap-4" onsubmit={handleSubmit}>
    <label class="text-sm font-semibold text-slate-700">
      <span class="label">データセット名</span>
      <div class="mt-2 flex flex-wrap gap-2">
        <input class="input flex-1" type="text" bind:value={datasetName} required />
        <Button.Root class="btn-ghost" type="button" onclick={handleRegenerate}>自動生成</Button.Root>
      </div>
      <p class="mt-2 text-xs text-slate-500">
        英数字で開始し、英数字・_・- のみ使用可。64文字以内、archive/temp/_ は不可。
      </p>
    </label>
    <label class="text-sm font-semibold text-slate-700">
      <span class="label">タスク説明</span>
      <textarea class="input mt-2 min-h-[120px]" bind:value={task} required></textarea>
      <p class="mt-2 text-xs text-slate-500">例: 物体を掴んで箱に置く / 机の上を移動</p>
    </label>
    <label class="text-sm font-semibold text-slate-700">
      <span class="label">エピソード総数</span>
      <input class="input mt-2" type="number" min="1" step="1" bind:value={episodeCount} required />
    </label>
    <label class="text-sm font-semibold text-slate-700">
      <span class="label">エピソード秒数</span>
      <input class="input mt-2" type="number" min="1" step="1" bind:value={episodeTimeSec} required />
      <p class="mt-2 text-xs text-slate-500">1エピソードの録画時間（秒）</p>
    </label>
    <label class="text-sm font-semibold text-slate-700">
      <span class="label">リセット待機秒数</span>
      <input class="input mt-2" type="number" min="0" step="0.5" bind:value={resetWaitSec} required />
      <p class="mt-2 text-xs text-slate-500">エピソード間の待機時間（秒）</p>
    </label>
    <p class="text-xs text-slate-500">プロフィールは現在の設定が使用されます。</p>
    {#if error}
      <p class="text-sm text-rose-600">{error}</p>
    {/if}
    {#if showStartupBlock}
      <div class="rounded-lg border border-emerald-200 bg-emerald-50/60 p-3">
        <div class="flex items-center justify-between gap-3 text-xs text-emerald-800">
          <p>{startupStatus?.message ?? '収録データセットを準備中です...'}</p>
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
      <Button.Root class="btn-primary" type="submit" disabled={submitting || startupActive} aria-busy={submitting || startupActive}>
        {startupActive ? '準備中...' : '収録データセットを作成'}
      </Button.Root>
      <Button.Root class="btn-ghost" href="/record">キャンセル</Button.Root>
    </div>
  </form>
</section>

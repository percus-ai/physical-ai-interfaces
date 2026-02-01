<script lang="ts">
  import { goto } from '$app/navigation';
  import { Button } from 'bits-ui';
  import { api } from '$lib/api/client';

  type RecordingSessionResponse = {
    success?: boolean;
    message?: string;
    dataset_id?: string;
    status?: Record<string, unknown>;
  };

  const DATASET_NAME_PATTERN = /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/;

  const pad = (value: number) => String(value).padStart(2, '0');
  const buildDefaultName = () => {
    const now = new Date();
    return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(
      now.getMinutes()
    )}${pad(now.getSeconds())}`;
  };

  let datasetName = buildDefaultName();
  let task = '';
  let episodeCount: number | string = 1;
  let episodeTimeSec: number | string = 60;
  let resetWaitSec: number | string = 10;

  let submitting = false;
  let error = '';

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

  const handleRegenerate = () => {
    datasetName = buildDefaultName();
  };

  const handleSubmit = async () => {
    error = '';
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
      const result = (await api.recording.startSession(payload)) as RecordingSessionResponse;
      if (!result?.dataset_id) {
        throw new Error('録画セッションの開始に失敗しました。');
      }
      await goto(`/record/sessions/${result.dataset_id}`);
    } catch (err) {
      error = err instanceof Error ? err.message : '録画セッションの開始に失敗しました。';
    } finally {
      submitting = false;
    }
  };
</script>

<section class="card-strong p-8">
  <p class="section-title">Record</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">新規録画セッション</h1>
      <p class="mt-2 text-sm text-slate-600">録画を開始するためのパラメータを入力します。</p>
    </div>
    <Button.Root class="btn-ghost" href="/record">録画一覧に戻る</Button.Root>
  </div>
</section>

<section class="card p-6">
  <form class="grid gap-4" on:submit|preventDefault={handleSubmit}>
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
    <div class="mt-2 flex flex-wrap gap-3">
      <Button.Root class="btn-primary" type="submit" disabled={submitting} aria-busy={submitting}>
        録画セッションを開始
      </Button.Root>
      <Button.Root class="btn-ghost" href="/record">キャンセル</Button.Root>
    </div>
  </form>
</section>

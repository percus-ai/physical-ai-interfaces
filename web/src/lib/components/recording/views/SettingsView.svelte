<script lang="ts">
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { toStore } from 'svelte/store';
  import toast from 'svelte-french-toast';
  import { api } from '$lib/api/client';
  import {
    subscribeRecorderStatus,
    type RecorderStatus,
    type RosbridgeStatus
  } from '$lib/recording/recorderStatus';

  let {
    sessionId = '',
    title = 'Settings',
    mode = 'recording',
    sessionKind = ''
  }: {
    sessionId?: string;
    title?: string;
    mode?: 'recording' | 'operate';
    sessionKind?: '' | 'recording' | 'inference' | 'teleop';
  } = $props();

  type RunnerStatus = {
    denoising_steps?: number | null;
  };

  type InferenceRunnerStatusResponse = {
    runner_status?: RunnerStatus;
  };

  const inferenceRunnerStatusQuery = createQuery<InferenceRunnerStatusResponse>(
    toStore(() => ({
      queryKey: ['inference', 'runner', 'status', sessionKind],
      queryFn: api.inference.runnerStatus,
      enabled: sessionKind === 'inference'
    }))
  );

  let recorderStatus = $state<RecorderStatus | null>(null);
  let rosbridgeStatus = $state<RosbridgeStatus>('idle');
  let taskInput = $state('');
  let episodeTimeInput = $state('60');
  let resetTimeInput = $state('10');
  let denoisingStepsInput = $state('');
  let applyPending = $state(false);
  let applyError = $state('');
  let lastSyncedSignature = '';

  const asNumber = (value: unknown, fallback = 0) => {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  };
  const asTrimmedText = (value: unknown) => {
    if (typeof value === 'string') return value.trim();
    if (value == null) return '';
    return String(value).trim();
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
  const statusMatches = $derived.by(() => {
    if (!sessionId) return true;
    return statusDatasetId === sessionId;
  });

  const currentTask = $derived.by(() => {
    if (!statusMatches) return '';
    const value = (status as Record<string, unknown>)?.task;
    return typeof value === 'string' ? value : '';
  });
  const currentEpisodeTime = $derived.by(() => {
    if (!statusMatches) return 0;
    return asNumber((status as Record<string, unknown>)?.episode_time_s ?? 0, 0);
  });
  const currentResetTime = $derived.by(() => {
    if (!statusMatches) return 0;
    return asNumber((status as Record<string, unknown>)?.reset_time_s ?? 0, 0);
  });
  const currentDenoisingSteps = $derived.by(() => {
    const value = $inferenceRunnerStatusQuery.data?.runner_status?.denoising_steps;
    if (typeof value === 'number' && Number.isInteger(value) && value > 0) {
      return value;
    }
    return null;
  });

  $effect(() => {
    const signature = [
      currentTask,
      String(currentEpisodeTime),
      String(currentResetTime),
      String(currentDenoisingSteps ?? '')
    ].join('|');
    if (signature === lastSyncedSignature || applyPending) return;
    taskInput = currentTask;
    episodeTimeInput = currentEpisodeTime > 0 ? String(currentEpisodeTime) : '';
    resetTimeInput = currentResetTime >= 0 ? String(currentResetTime) : '';
    denoisingStepsInput = currentDenoisingSteps == null ? '' : String(currentDenoisingSteps);
    lastSyncedSignature = signature;
  });

  const contextLabel = $derived(
    sessionKind === 'inference' ? '推論' : sessionKind === 'recording' ? '録画' : '非対応'
  );
  const supportsDenoising = $derived(sessionKind === 'inference');
  const canApply = $derived(sessionKind === 'inference' || sessionKind === 'recording');
  const connectionWarning = $derived(
    rosbridgeStatus !== 'connected' ? 'rosbridge が切断されています。現在値は更新されません。' : ''
  );

  const handleApply = async () => {
    if (!canApply || applyPending) return;
    applyError = '';
    applyPending = true;
    try {
      const task = asTrimmedText(taskInput);
      const episodeTime = Number(episodeTimeInput);
      const resetTime = Number(resetTimeInput);
      if (!task) {
        throw new Error('task を入力してください。');
      }
      if (!Number.isFinite(episodeTime) || episodeTime <= 0) {
        throw new Error('episode time は 0 より大きい数値で入力してください。');
      }
      if (!Number.isFinite(resetTime) || resetTime < 0) {
        throw new Error('reset time は 0 以上の数値で入力してください。');
      }
      if (sessionKind === 'inference') {
        let denoisingSteps: number | undefined;
        const raw = asTrimmedText(denoisingStepsInput);
        if (raw) {
          const parsed = Number.parseInt(raw, 10);
          if (!Number.isInteger(parsed) || parsed < 1) {
            throw new Error('denoising steps は 1 以上の整数で入力してください。');
          }
          denoisingSteps = parsed;
        }
        await api.inference.applySettings({
          task,
          episode_time_s: episodeTime,
          reset_time_s: resetTime,
          denoising_steps: denoisingSteps
        });
        await $inferenceRunnerStatusQuery.refetch?.();
      } else {
        await api.recording.updateSession({
          task,
          episode_time_s: episodeTime,
          reset_time_s: resetTime
        });
      }
      toast.success('設定を反映しました。');
    } catch (error) {
      applyError = error instanceof Error ? error.message : '設定の反映に失敗しました。';
      toast.error(applyError);
    } finally {
      applyPending = false;
    }
  };
</script>

<div class="flex h-full flex-col gap-3">
  <div class="flex items-center justify-between">
    <p class="text-xs font-semibold uppercase tracking-widest text-slate-500">{title}</p>
    <span class="text-[10px] text-slate-400">{contextLabel}</span>
  </div>

  {#if connectionWarning}
    <p class="text-xs text-amber-600">{connectionWarning}</p>
  {/if}

  <div class="rounded-2xl border border-slate-200/60 bg-white/70 p-3">
    <div class="grid gap-3">
      <label class="text-xs font-semibold text-slate-600">
        <span class="label">Task</span>
        <input class="input mt-2" type="text" bind:value={taskInput} disabled={!canApply || applyPending} />
        <p class="mt-1 text-[11px] text-slate-400">現在値: {currentTask || '-'}</p>
      </label>

      <div class="grid gap-3 sm:grid-cols-2">
        <label class="text-xs font-semibold text-slate-600">
          <span class="label">Episode Time (s)</span>
          <input
            class="input mt-2"
            type="number"
            min="0.1"
            step="0.1"
            bind:value={episodeTimeInput}
            disabled={!canApply || applyPending}
          />
          <p class="mt-1 text-[11px] text-slate-400">現在値: {currentEpisodeTime || '-'}s</p>
        </label>

        <label class="text-xs font-semibold text-slate-600">
          <span class="label">Reset Time (s)</span>
          <input
            class="input mt-2"
            type="number"
            min="0"
            step="0.1"
            bind:value={resetTimeInput}
            disabled={!canApply || applyPending}
          />
          <p class="mt-1 text-[11px] text-slate-400">現在値: {currentResetTime || '-'}s</p>
        </label>
      </div>

      {#if supportsDenoising}
        <label class="text-xs font-semibold text-slate-600">
          <span class="label">Denoising Steps</span>
          <input
            class="input mt-2"
            type="number"
            min="1"
            step="1"
            bind:value={denoisingStepsInput}
            disabled={!canApply || applyPending}
          />
          <p class="mt-1 text-[11px] text-slate-400">
            現在値: {currentDenoisingSteps == null ? 'モデル既定値' : currentDenoisingSteps}
          </p>
        </label>
      {/if}

      <div class="flex items-center gap-2">
        <Button.Root class="btn-primary" type="button" onclick={handleApply} disabled={!canApply || applyPending}>
          {applyPending ? '反映中...' : '反映'}
        </Button.Root>
      </div>
      {#if applyError}
        <p class="text-xs text-rose-600">{applyError}</p>
      {/if}
    </div>
  </div>
</div>

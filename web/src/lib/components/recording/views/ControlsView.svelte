<script lang="ts">
  import { AlertDialog, Button } from 'bits-ui';
  import toast from 'svelte-french-toast';
  import { api } from '$lib/api/client';
  import {
    subscribeRecorderStatus,
    type RecorderStatus,
    type RosbridgeStatus
  } from '$lib/recording/recorderStatus';

  let {
    sessionId = '',
    title = 'Controls',
    mode = 'recording'
  }: {
    sessionId?: string;
    title?: string;
    mode?: 'recording' | 'operate';
  } = $props();

  let recorderStatus = $state<RecorderStatus | null>(null);
  let rosbridgeStatus = $state<RosbridgeStatus>('idle');
  let actionBusy = $state('');
  let confirmOpen = $state(false);
  let confirmTitle = $state('');
  let confirmDescription = $state('');
  let confirmActionLabel = $state('実行');
  let pendingConfirmAction = $state<(() => Promise<boolean>) | null>(null);
  let wasDisconnected = false;
  let wasFinalizing = false;
  let finalizingToastId: string | null = null;

  const runAction = async (
    label: string,
    action: () => Promise<unknown>,
    options: { successToast?: string } = {}
  ): Promise<boolean> => {
    actionBusy = label;
    try {
      await action();
      toast.success(options.successToast ?? `${label}リクエストを受け付けました。`);
      return true;
    } catch (err) {
      const message = err instanceof Error ? err.message : `${label} に失敗しました。`;
      toast.error(message);
      return false;
    } finally {
      actionBusy = '';
    }
  };

  const handlePause = async () =>
    runAction('中断', () => api.recording.pauseSession(), {
      successToast: '一時停止リクエストを受け付けました。'
    });
  const handleResume = async () =>
    runAction('再開', () => api.recording.resumeSession(), {
      successToast: '再開リクエストを受け付けました。'
    });
  const openConfirm = (options: {
    title: string;
    description: string;
    actionLabel: string;
    action: () => Promise<boolean>;
  }) => {
    if (actionBusy) return;
    confirmTitle = options.title;
    confirmDescription = options.description;
    confirmActionLabel = options.actionLabel;
    pendingConfirmAction = options.action;
    confirmOpen = true;
  };
  const handleConfirmAction = async () => {
    if (!pendingConfirmAction) return;
    const action = pendingConfirmAction;
    pendingConfirmAction = null;
    const success = await action();
    if (success) {
      confirmOpen = false;
    }
  };
  const handleConfirmCancel = () => {
    pendingConfirmAction = null;
  };
  const handleStart = async () => {
    if (!sessionId) return;
    await runAction('開始', () => api.recording.startSession({ dataset_id: sessionId }), {
      successToast: '開始リクエストを受け付けました。状態反映を待っています。'
    });
  };
  const handleRetakePrevious = async () => {
    openConfirm({
      title: '直前エピソードを取り直しますか？',
      description: '直前に保存したエピソードを取り消して、録画し直します。',
      actionLabel: '取り直す',
      action: () =>
        runAction('直前取り直し', () => api.recording.redoPreviousEpisode(), {
          successToast: '直前エピソードの取り直しを受け付けました。'
        })
    });
  };
  const handleRetakeCurrent = async () => {
    openConfirm({
      title: '現在のエピソードを取り直しますか？',
      description: '現在のエピソードは破棄され、最初から録画し直します。',
      actionLabel: '取り直す',
      action: () =>
        runAction('取り直し', () => api.recording.cancelEpisode(), {
          successToast: '現在エピソードの取り直しを受け付けました。'
        })
    });
  };
  const handleNext = async () => {
    openConfirm({
      title: '現在のエピソードを保存して次へ進みますか？',
      description: '現在エピソードを保存して、次エピソードのリセットへ進みます。',
      actionLabel: '保存して次へ',
      action: () =>
        runAction('次へ', () => api.recording.nextEpisode(), {
          successToast: '次エピソードへの遷移を受け付けました。状態反映を待っています。'
        })
    });
  };
  const handleStop = async () => {
    openConfirm({
      title: '録画セッションを終了しますか？',
      description: '現在のエピソードは保存された状態で終了します。',
      actionLabel: '終了する',
      action: () =>
        runAction('終了', () =>
          api.recording.stopSession({
            dataset_id: datasetId,
            save_current: true
          }),
          {
            successToast: '終了リクエストを受け付けました。状態反映を待っています。'
          }
        )
    });
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
  const asNumber = (value: unknown, fallback = 0) => {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  };
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
  const datasetId = $derived.by(() => {
    const value = (status as Record<string, unknown>)?.dataset_id;
    return typeof value === 'string' ? value : sessionId;
  });
  const completedEpisodeCount = $derived(
    asNumber((status as Record<string, unknown>)?.episode_count ?? 0, 0)
  );
  const statusPhase = $derived(String((status as Record<string, unknown>)?.phase ?? 'wait'));
  const isFinalizing = $derived(statusPhase === 'finalizing');

  const canPause = $derived(statusState === 'recording' && !isFinalizing);
  const canResume = $derived(statusState === 'paused' && !isFinalizing);
  const canRetakePrevious = $derived.by(() => {
    if (isFinalizing) return false;
    const state = String(statusState);
    if (state === 'resetting') {
      return false;
    }
    if (state === 'paused') {
      return false;
    }
    return state === 'recording' && completedEpisodeCount > 0;
  });
  const canRetakeCurrent = $derived.by(() => {
    if (isFinalizing) return false;
    const state = String(statusState);
    if (state === 'resetting') {
      return false;
    }
    return state === 'recording' || state === 'paused';
  });
  const canNext = $derived(['recording', 'paused'].includes(String(statusState)) && !isFinalizing);
  const canStop = $derived(
    ['recording', 'paused', 'resetting', 'warming'].includes(String(statusState)) && !isFinalizing
  );
  const canStart = $derived(
    Boolean(sessionId) && ['idle', 'completed', 'inactive', ''].includes(String(statusState))
  );

  $effect(() => {
    if (typeof window === 'undefined') return;
    const disconnected = rosbridgeStatus !== 'connected';
    if (disconnected && !wasDisconnected) {
      toast.error('rosbridge が切断されています。状態は更新されません。');
    } else if (!disconnected && wasDisconnected) {
      toast.success('rosbridge 接続が復旧しました。');
    }
    wasDisconnected = disconnected;
  });

  $effect(() => {
    if (typeof window === 'undefined') return;
    if (isFinalizing && !wasFinalizing) {
      finalizingToastId = String(toast.loading('エピソード保存中です...'));
    } else if (!isFinalizing && wasFinalizing) {
      if (finalizingToastId !== null) {
        toast.dismiss(finalizingToastId);
        finalizingToastId = null;
      }
      toast.success('エピソード保存が完了しました。');
    }
    wasFinalizing = isFinalizing;
  });

  $effect(() => {
    return () => {
      if (finalizingToastId !== null) {
        toast.dismiss(finalizingToastId);
        finalizingToastId = null;
      }
    };
  });
</script>

<div class="flex h-full flex-col gap-3">
  <div class="flex items-center justify-between">
    <p class="text-xs font-semibold uppercase tracking-widest text-slate-500">{title}</p>
    <span class="text-[10px] text-slate-400">{statusState || 'unknown'}</span>
  </div>

  {#if mode !== 'recording'}
    <div class="rounded-xl border border-amber-200/70 bg-amber-50/60 p-3 text-xs text-amber-700">
      このビューは録画セッションのみ対応しています。
    </div>
  {:else}
    <div class="grid gap-2 text-sm">
      <div class="grid grid-cols-[1fr_1fr_auto_1fr] items-center gap-2">
        <Button.Root
          class="btn-ghost"
          type="button"
          onclick={handleRetakePrevious}
          disabled={!canRetakePrevious || Boolean(actionBusy)}
        >
          {actionBusy === '直前取り直し' ? '前を取り直し中...' : '⇤'}
        </Button.Root>
        <Button.Root
          class="btn-ghost"
          type="button"
          onclick={handleRetakeCurrent}
          disabled={!canRetakeCurrent || Boolean(actionBusy)}
        >
          {actionBusy === '取り直し' ? '← 実行中...' : '←'}
        </Button.Root>
        <Button.Root
          class="btn-primary min-w-[120px]"
          type="button"
          onclick={canResume ? handleResume : handlePause}
          disabled={(!canResume && !canPause) || Boolean(actionBusy)}
        >
          {#if canResume}
            {actionBusy === '再開' ? '再生中...' : '再生'}
          {:else}
            {actionBusy === '中断' ? '一時停止中...' : '一時停止'}
          {/if}
        </Button.Root>
        <Button.Root class="btn-ghost" type="button" onclick={handleNext} disabled={!canNext || Boolean(actionBusy)}>
          {actionBusy === '次へ' ? '実行中... →' : '→'}
        </Button.Root>
      </div>

      <div class="grid gap-2">
        {#if canStart}
          <Button.Root class="btn-primary" type="button" onclick={handleStart} disabled={Boolean(actionBusy)}>
            {actionBusy === '開始' ? '開始中...' : '開始'}
          </Button.Root>
        {:else}
          <Button.Root class="btn-primary" type="button" onclick={handleStop} disabled={!canStop || Boolean(actionBusy)}>
            {actionBusy === '終了' ? '終了中...' : '終了'}
          </Button.Root>
        {/if}
      </div>

      <p class="text-[11px] text-slate-500">
        ⇤: 直前エピソードを取り直し / ←: 現在エピソードを取り直し / →: 現在エピソードを保存して次へ
      </p>
    </div>
  {/if}
</div>

<AlertDialog.Root bind:open={confirmOpen}>
  <AlertDialog.Portal>
    <AlertDialog.Overlay class="fixed inset-0 z-40 bg-slate-900/50 backdrop-blur-[1px]" />
    <AlertDialog.Content
      class="fixed left-1/2 top-1/2 z-50 w-[min(92vw,28rem)] -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-slate-200 bg-white p-5 shadow-xl"
    >
      <AlertDialog.Title class="text-base font-semibold text-slate-900">{confirmTitle}</AlertDialog.Title>
      <AlertDialog.Description class="mt-2 text-sm text-slate-600">{confirmDescription}</AlertDialog.Description>
      <div class="mt-5 flex items-center justify-end gap-2">
        <AlertDialog.Cancel
          class="btn-ghost"
          type="button"
          disabled={Boolean(actionBusy)}
          onclick={handleConfirmCancel}
        >
          キャンセル
        </AlertDialog.Cancel>
        <AlertDialog.Action
          class="btn-primary"
          type="button"
          disabled={!pendingConfirmAction || Boolean(actionBusy)}
          onclick={handleConfirmAction}
        >
          {confirmActionLabel}
        </AlertDialog.Action>
      </div>
    </AlertDialog.Content>
  </AlertDialog.Portal>
</AlertDialog.Root>

<script lang="ts">
  import { Button } from 'bits-ui';
  import toast from 'svelte-french-toast';
  import { api } from '$lib/api/client';

  let {
    sessionId = '',
    title = 'Controls',
    mode = 'recording',
    recorderStatus = null,
    rosbridgeStatus = 'idle'
  }: {
    sessionId?: string;
    title?: string;
    mode?: 'recording' | 'operate';
    recorderStatus?: Record<string, unknown> | null;
    rosbridgeStatus?: 'idle' | 'connecting' | 'connected' | 'disconnected' | 'error';
  } = $props();

  let actionBusy = $state('');
  let actionError = $state('');
  let actionMessage = $state('');

  const runAction = async (
    label: string,
    action: () => Promise<unknown>,
    options: { successToast?: string } = {}
  ) => {
    actionError = '';
    actionMessage = '';
    actionBusy = label;
    try {
      const result = (await action()) as { message?: string };
      actionMessage = result?.message ?? `${label} を実行しました。`;
      if (options.successToast) {
        toast.success(options.successToast);
      }
    } catch (err) {
      actionError = err instanceof Error ? err.message : `${label} に失敗しました。`;
    } finally {
      actionBusy = '';
    }
  };

  const handlePause = async () => runAction('中断', () => api.recording.pauseSession());
  const handleResume = async () => runAction('再開', () => api.recording.resumeSession());
  const handleStart = async () => {
    if (!sessionId) return;
    await runAction('開始', () => api.recording.startSession({ dataset_id: sessionId }));
  };
  const handleRetakeCurrent = async () => {
    if (!confirm('現在のエピソードを破棄して、取り直しますか？')) return;
    await runAction('取り直し', () => api.recording.cancelEpisode());
  };
  const handleNext = async () => {
    if (!confirm('現在のエピソードを保存して次へ進みますか？')) return;
    await runAction('次へ', () => api.recording.nextEpisode(), {
      successToast: '次エピソードへの遷移を受け付けました。状態反映を待っています。'
    });
  };
  const handleStop = async () => {
    if (!confirm('録画セッションを終了しますか？（現在のエピソードは保存されます）')) return;
    await runAction('終了', () =>
      api.recording.stopSession({
        dataset_id: datasetId,
        save_current: true
      })
    );
  };

  const status = $derived(recorderStatus ?? {});
  const statusState = $derived(
    (status as Record<string, unknown>)?.state ?? (status as Record<string, unknown>)?.status ?? ''
  );
  const datasetId = $derived.by(() => {
    const value = (status as Record<string, unknown>)?.dataset_id;
    return typeof value === 'string' ? value : sessionId;
  });

  const canPause = $derived(statusState === 'recording');
  const canResume = $derived(statusState === 'paused');
  const canRetakeCurrent = $derived(['recording', 'paused'].includes(String(statusState)));
  const canNext = $derived(['recording', 'paused'].includes(String(statusState)));
  const canStop = $derived(['recording', 'paused', 'resetting', 'warming'].includes(String(statusState)));
  const canStart = $derived(
    Boolean(sessionId) && ['idle', 'completed', 'inactive', ''].includes(String(statusState))
  );
  const connectionWarning = $derived(
    rosbridgeStatus !== 'connected' ? 'rosbridge が切断されています。状態は更新されません。' : ''
  );
</script>

<div class="flex h-full flex-col gap-3">
  <div class="flex items-center justify-between">
    <p class="text-xs font-semibold uppercase tracking-widest text-slate-500">{title}</p>
    <span class="text-[10px] text-slate-400">{statusState || 'unknown'}</span>
  </div>

  {#if actionError}
    <p class="text-xs text-rose-600">{actionError}</p>
  {/if}
  {#if actionMessage}
    <p class="text-xs text-emerald-600">{actionMessage}</p>
  {/if}
  {#if connectionWarning}
    <p class="text-xs text-amber-600">{connectionWarning}</p>
  {/if}

  {#if mode !== 'recording'}
    <div class="rounded-xl border border-amber-200/70 bg-amber-50/60 p-3 text-xs text-amber-700">
      このビューは録画セッションのみ対応しています。
    </div>
  {:else}
    <div class="grid gap-2 text-sm">
      <div class="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
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
        ←: 現在エピソードを取り直し / →: 現在エピソードを保存して次へ
      </p>
    </div>
  {/if}
</div>

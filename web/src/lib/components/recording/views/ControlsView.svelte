<script lang="ts">
  import { createQuery } from '@tanstack/svelte-query';
  import { derived, writable } from 'svelte/store';
  import { Button } from 'bits-ui';
  import { api } from '$lib/api/client';

  export let sessionId = '';
  export let title = 'Controls';
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

  let actionBusy = '';
  let actionError = '';
  let actionMessage = '';

  const refresh = async () => {
    await $statusQuery?.refetch?.();
  };

  const runAction = async (label: string, action: () => Promise<unknown>) => {
    actionError = '';
    actionMessage = '';
    actionBusy = label;
    try {
      const result = (await action()) as { message?: string };
      actionMessage = result?.message ?? `${label} を実行しました。`;
    } catch (err) {
      actionError = err instanceof Error ? err.message : `${label} に失敗しました。`;
    } finally {
      actionBusy = '';
      await refresh();
    }
  };

  const handlePause = async () => runAction('中断', () => api.recording.pauseSession());
  const handleResume = async () => runAction('再開', () => api.recording.resumeSession());
  const handleStop = async () => {
    if (!confirm('録画セッションを終了しますか？（現在のエピソードは保存されます）')) return;
    await runAction('終了', () =>
      api.recording.stopSession({
        dataset_id: datasetId,
        save_current: true
      })
    );
  };
  const handleCancelSession = async () => {
    if (!confirm('録画セッションを破棄しますか？（現在のエピソードは保存されません）')) return;
    await runAction('破棄', () => api.recording.cancelSession(datasetId));
  };
  const handleRedoEpisode = async () => {
    if (!confirm('1つ前のエピソードに戻しますか？')) return;
    await runAction('前エピソードへ戻る', () => api.recording.redoEpisode());
  };
  const handleCancelEpisode = async () => {
    if (!confirm('現在のエピソードを破棄しますか？')) return;
    await runAction('エピソード破棄', () => api.recording.cancelEpisode());
  };

  $: status = $statusQuery.data?.status ?? {};
  $: statusState =
    (status as Record<string, unknown>)?.state ?? (status as Record<string, unknown>)?.status ?? '';
  $: datasetId = $statusQuery.data?.dataset_id ?? sessionId;

  $: canPause = statusState === 'recording';
  $: canResume = statusState === 'paused';
  $: canStop = ['recording', 'paused', 'resetting', 'warming'].includes(String(statusState));
  $: canRedo = Boolean(statusState) && !['recording', 'paused'].includes(String(statusState));
  $: canCancelEpisode = statusState === 'recording';
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

  {#if mode !== 'recording'}
    <div class="rounded-xl border border-amber-200/70 bg-amber-50/60 p-3 text-xs text-amber-700">
      このビューは録画セッションのみ対応しています。
    </div>
  {:else}
    <div class="grid gap-2 text-sm">
      <div class="grid gap-2 sm:grid-cols-2">
        <Button.Root class="btn-primary" type="button" onclick={handleResume} disabled={!canResume || Boolean(actionBusy)}>
          {actionBusy === '再開' ? '再開中...' : '再開'}
        </Button.Root>
        <Button.Root class="btn-ghost" type="button" onclick={handlePause} disabled={!canPause || Boolean(actionBusy)}>
          {actionBusy === '中断' ? '中断中...' : '中断'}
        </Button.Root>
        <Button.Root class="btn-primary" type="button" onclick={handleStop} disabled={!canStop || Boolean(actionBusy)}>
          {actionBusy === '終了' ? '終了中...' : '終了'}
        </Button.Root>
        <Button.Root class="btn-ghost" type="button" onclick={handleCancelSession} disabled={!canStop || Boolean(actionBusy)}>
          保存せず終了
        </Button.Root>
      </div>
      <div class="grid gap-2 sm:grid-cols-2">
        <Button.Root class="btn-ghost" type="button" onclick={handleRedoEpisode} disabled={!canRedo || Boolean(actionBusy)}>
          1個前に戻る
        </Button.Root>
        <Button.Root class="btn-ghost" type="button" onclick={handleCancelEpisode} disabled={!canCancelEpisode || Boolean(actionBusy)}>
          エピソード破棄
        </Button.Root>
      </div>
    </div>
  {/if}
</div>

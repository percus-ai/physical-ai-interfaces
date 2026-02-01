<script lang="ts">
  import { Button } from 'bits-ui';
  import { derived } from 'svelte/store';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { formatBytes, formatDate } from '$lib/format';

  type ModelInfo = {
    id: string;
    name?: string;
    project_id?: string;
    dataset_id?: string;
    policy_type?: string;
    status?: string;
    size_bytes?: number;
    created_at?: string;
    updated_at?: string;
  };

  $: modelId = $page.params.modelId;

  const queryClient = useQueryClient();

  const modelQuery = createQuery<ModelInfo>(
    derived(page, ($page) => {
      const currentId = $page.params.modelId;
      return {
        queryKey: ['storage', 'model', currentId],
        queryFn: () => api.storage.model(currentId) as Promise<ModelInfo>,
        enabled: Boolean(currentId)
      };
    })
  );

  $: model = $modelQuery.data;
  $: isArchived = model?.status === 'archived';

  let actionMessage = '';
  let actionError = '';
  let actionLoading = false;

  const refetchModel = async () => {
    if (!modelId) return;
    await queryClient.invalidateQueries({ queryKey: ['storage', 'model', modelId] });
  };

  async function handleArchive() {
    actionMessage = '';
    actionError = '';

    if (!modelId) return;
    const confirmed = confirm(`${modelId} をアーカイブしますか？`);
    if (!confirmed) return;

    actionLoading = true;
    try {
      await api.storage.archiveModel(modelId);
      await refetchModel();
      actionMessage = 'アーカイブしました。';
    } catch (err) {
      actionError = err instanceof Error ? err.message : 'アーカイブに失敗しました。';
    } finally {
      actionLoading = false;
    }
  }

  async function handleRestore() {
    actionMessage = '';
    actionError = '';

    if (!modelId) return;
    const confirmed = confirm(`${modelId} を復元しますか？`);
    if (!confirmed) return;

    actionLoading = true;
    try {
      await api.storage.restoreModel(modelId);
      await refetchModel();
      actionMessage = '復元しました。';
    } catch (err) {
      actionError = err instanceof Error ? err.message : '復元に失敗しました。';
    } finally {
      actionLoading = false;
    }
  }
</script>

<section class="card-strong p-8">
  <p class="section-title">Storage</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">モデル詳細</h1>
      <p class="mt-2 text-sm text-slate-600">モデルの状態と操作を確認します。</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button.Root class="btn-ghost" href="/storage/models">一覧へ戻る</Button.Root>
      <button class="btn-ghost" type="button" on:click={refetchModel}>更新</button>
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold text-slate-900">基本情報</h2>
  </div>
  {#if $modelQuery.isLoading}
    <p class="mt-4 text-sm text-slate-600">読み込み中...</p>
  {:else if model}
    <div class="mt-4 grid gap-4 text-sm text-slate-600 lg:grid-cols-2">
      <div>
        <p class="label">ID</p>
        <p class="text-base font-semibold text-slate-800">{model.id}</p>
      </div>
      <div>
        <p class="label">プロジェクト</p>
        <p class="text-base font-semibold text-slate-800">{model.project_id}</p>
      </div>
      <div>
        <p class="label">状態</p>
        <p class="text-base font-semibold text-slate-800">{model.status}</p>
      </div>
      <div>
        <p class="label">ポリシー</p>
        <p class="text-base font-semibold text-slate-800">{model.policy_type ?? '-'}</p>
      </div>
      <div>
        <p class="label">データセット</p>
        <p class="text-base font-semibold text-slate-800">{model.dataset_id ?? '-'}</p>
      </div>
      <div>
        <p class="label">サイズ</p>
        <p class="text-base font-semibold text-slate-800">{formatBytes(model.size_bytes)}</p>
      </div>
      <div>
        <p class="label">作成日時</p>
        <p class="text-base font-semibold text-slate-800">{formatDate(model.created_at)}</p>
      </div>
      <div>
        <p class="label">更新日時</p>
        <p class="text-base font-semibold text-slate-800">{formatDate(model.updated_at)}</p>
      </div>
    </div>
    <div class="mt-6 flex flex-wrap gap-2">
      {#if isArchived}
        <button
          class={`btn-primary ${actionLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
          type="button"
          disabled={actionLoading}
          on:click={handleRestore}
        >
          復元
        </button>
      {:else}
        <button
          class={`btn-ghost ${actionLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
          type="button"
          disabled={actionLoading}
          on:click={handleArchive}
        >
          アーカイブ
        </button>
      {/if}
      <button class="btn-ghost" type="button" on:click={() => goto('/storage/archive')}>アーカイブ一覧</button>
    </div>
  {:else}
    <p class="mt-4 text-sm text-slate-600">モデルが見つかりません。</p>
  {/if}
  {#if actionMessage}
    <p class="mt-4 text-sm text-emerald-600">{actionMessage}</p>
  {/if}
  {#if actionError}
    <p class="mt-2 text-sm text-rose-600">{actionError}</p>
  {/if}
</section>

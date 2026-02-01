<script lang="ts">
  import { Button } from 'bits-ui';
  import { derived } from 'svelte/store';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { formatBytes, formatDate } from '$lib/format';

  type ArchiveItem = {
    id: string;
    project_id?: string;
    status?: string;
    size_bytes?: number;
    created_at?: string;
    updated_at?: string;
    dataset_type?: string;
    episode_count?: number;
    policy_type?: string;
    dataset_id?: string;
  };

  $: itemType = $page.params.type;
  $: itemId = $page.params.itemId;
  $: isDataset = itemType === 'dataset';
  $: isModel = itemType === 'model';

  const queryClient = useQueryClient();

  const itemQuery = createQuery<ArchiveItem>(
    derived(page, ($page) => {
      const currentType = $page.params.type;
      const currentId = $page.params.itemId;
      const currentIsDataset = currentType === 'dataset';
      const currentIsModel = currentType === 'model';
      return {
        queryKey: ['storage', 'archive', currentType, currentId],
        queryFn: () => {
          const request = currentIsDataset
            ? api.storage.dataset(currentId)
            : api.storage.model(currentId);
          return request as Promise<ArchiveItem>;
        },
        enabled: Boolean(currentId) && (currentIsDataset || currentIsModel)
      };
    })
  );

  $: item = $itemQuery.data;

  let actionMessage = '';
  let actionError = '';
  let actionLoading = false;

  const refetchItem = async () => {
    if (!itemId) return;
    await queryClient.invalidateQueries({
      queryKey: ['storage', 'archive', itemType, itemId]
    });
  };

  async function handleRestore() {
    actionMessage = '';
    actionError = '';

    if (!itemId) return;
    const confirmed = confirm(`${itemId} を復元しますか？`);
    if (!confirmed) return;

    actionLoading = true;
    try {
      if (isDataset) {
        await api.storage.restoreDataset(itemId);
      } else if (isModel) {
        await api.storage.restoreModel(itemId);
      }
      actionMessage = '復元しました。';
      await goto('/storage/archive');
    } catch (err) {
      actionError = err instanceof Error ? err.message : '復元に失敗しました。';
    } finally {
      actionLoading = false;
    }
  }

  async function handleDelete() {
    actionMessage = '';
    actionError = '';

    if (!itemId) return;
    const confirmed = confirm(`${itemId} を完全に削除しますか？`);
    if (!confirmed) return;

    actionLoading = true;
    try {
      if (isDataset) {
        await api.storage.deleteArchivedDataset(itemId);
      } else if (isModel) {
        await api.storage.deleteArchivedModel(itemId);
      }
      actionMessage = '削除しました。';
      await goto('/storage/archive');
    } catch (err) {
      actionError = err instanceof Error ? err.message : '削除に失敗しました。';
    } finally {
      actionLoading = false;
    }
  }
</script>

<section class="card-strong p-8">
  <p class="section-title">Storage</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">アーカイブ詳細</h1>
      <p class="mt-2 text-sm text-slate-600">アーカイブ済みデータの詳細を確認します。</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button.Root class="btn-ghost" href="/storage/archive">一覧へ戻る</Button.Root>
      <button class="btn-ghost" type="button" on:click={refetchItem}>更新</button>
    </div>
  </div>
</section>

<section class="card p-6">
  {#if !(isDataset || isModel)}
    <p class="text-sm text-rose-600">不明なアーカイブ種別です。</p>
  {:else if $itemQuery.isLoading}
    <p class="text-sm text-slate-600">読み込み中...</p>
  {:else if item}
    <div class="flex items-center justify-between">
      <h2 class="text-xl font-semibold text-slate-900">基本情報</h2>
      <span class="chip">{itemType}</span>
    </div>
    <div class="mt-4 grid gap-4 text-sm text-slate-600 lg:grid-cols-2">
      <div>
        <p class="label">ID</p>
        <p class="text-base font-semibold text-slate-800">{item.id}</p>
      </div>
      <div>
        <p class="label">プロジェクト</p>
        <p class="text-base font-semibold text-slate-800">{item.project_id}</p>
      </div>
      <div>
        <p class="label">状態</p>
        <p class="text-base font-semibold text-slate-800">{item.status}</p>
      </div>
      <div>
        <p class="label">サイズ</p>
        <p class="text-base font-semibold text-slate-800">{formatBytes(item.size_bytes ?? 0)}</p>
      </div>
      <div>
        <p class="label">作成日時</p>
        <p class="text-base font-semibold text-slate-800">{formatDate(item.created_at)}</p>
      </div>
      <div>
        <p class="label">更新日時</p>
        <p class="text-base font-semibold text-slate-800">{formatDate(item.updated_at)}</p>
      </div>
      {#if isDataset}
        <div>
          <p class="label">データセット種別</p>
          <p class="text-base font-semibold text-slate-800">{item.dataset_type}</p>
        </div>
        <div>
          <p class="label">エピソード数</p>
          <p class="text-base font-semibold text-slate-800">{item.episode_count ?? 0}</p>
        </div>
      {:else}
        <div>
          <p class="label">ポリシー</p>
          <p class="text-base font-semibold text-slate-800">{item.policy_type ?? '-'}</p>
        </div>
        <div>
          <p class="label">データセット</p>
          <p class="text-base font-semibold text-slate-800">{item.dataset_id ?? '-'}</p>
        </div>
      {/if}
    </div>
    <div class="mt-6 flex flex-wrap gap-2">
      <button
        class={`btn-primary ${actionLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
        type="button"
        disabled={actionLoading}
        on:click={handleRestore}
      >
        復元
      </button>
      <button
        class={`btn-ghost ${actionLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
        type="button"
        disabled={actionLoading}
        on:click={handleDelete}
      >
        完全削除
      </button>
    </div>
  {:else}
    <p class="text-sm text-slate-600">項目が見つかりません。</p>
  {/if}
  {#if actionMessage}
    <p class="mt-4 text-sm text-emerald-600">{actionMessage}</p>
  {/if}
  {#if actionError}
    <p class="mt-2 text-sm text-rose-600">{actionError}</p>
  {/if}
</section>

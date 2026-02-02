<script lang="ts">
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';

  export let title = 'Topics';

  type ProfileStatusResponse = {
    topics?: string[];
  };

  const topicsQuery = createQuery<ProfileStatusResponse>({
    queryKey: ['profiles', 'instances', 'active', 'status'],
    queryFn: api.profiles.activeStatus
  });
</script>

<div class="flex h-full flex-col gap-3">
  <div class="flex items-center justify-between">
    <p class="text-xs font-semibold uppercase tracking-widest text-slate-500">{title}</p>
    <span class="text-[10px] text-slate-400">{($topicsQuery.data?.topics ?? []).length} 件</span>
  </div>
  <div class="flex-1 rounded-2xl border border-slate-200/60 bg-white/70 p-3 text-xs text-slate-600">
    {#if $topicsQuery.isLoading}
      <p>読み込み中...</p>
    {:else if $topicsQuery.error}
      <p>取得に失敗しました。</p>
    {:else if ($topicsQuery.data?.topics ?? []).length === 0}
      <p>トピックがありません。</p>
    {:else}
      <div class="space-y-1">
        {#each $topicsQuery.data?.topics ?? [] as topic}
          <div class="flex items-center gap-2">
            <span class="h-1.5 w-1.5 rounded-full bg-slate-300"></span>
            <span class="truncate">{topic}</span>
          </div>
        {/each}
      </div>
    {/if}
  </div>
</div>

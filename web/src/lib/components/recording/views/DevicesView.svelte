<script lang="ts">
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';

  export let title = 'Devices';

  type ProfileStatusResponse = {
    cameras?: Array<{ name?: string; connected?: boolean }>;
    arms?: Array<{ name?: string; connected?: boolean }>;
  };

  const statusQuery = createQuery<ProfileStatusResponse>({
    queryKey: ['profiles', 'active', 'status'],
    queryFn: api.profiles.activeStatus
  });
</script>

<div class="flex h-full flex-col gap-3">
  <div class="flex items-center justify-between">
    <p class="text-xs font-semibold uppercase tracking-widest text-slate-500">{title}</p>
    <span class="text-[10px] text-slate-400">{($statusQuery.data?.arms ?? []).length} arms</span>
  </div>
  <div class="flex-1 rounded-2xl border border-slate-200/60 bg-white/70 p-3 text-xs text-slate-600">
    {#if $statusQuery.isLoading}
      <p>読み込み中...</p>
    {:else}
      <div class="space-y-2">
        {#each $statusQuery.data?.arms ?? [] as arm}
          <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-3 py-2">
            <span class="font-semibold text-slate-700">{arm.name ?? 'arm'}</span>
            <span class={`chip ${arm.connected ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
              {arm.connected ? '接続' : '未接続'}
            </span>
          </div>
        {/each}
        {#each $statusQuery.data?.cameras ?? [] as cam}
          <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-3 py-2">
            <span class="font-semibold text-slate-700">{cam.name ?? 'camera'}</span>
            <span class={`chip ${cam.connected ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
              {cam.connected ? '接続' : '未接続'}
            </span>
          </div>
        {/each}
      </div>
    {/if}
  </div>
</div>

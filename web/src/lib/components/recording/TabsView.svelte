<script lang="ts">
  import { createEventDispatcher, type Snippet } from 'svelte';
  import type { TabItem } from '$lib/recording/blueprint';

  let { tabs = [], activeId = '', children }: {
    tabs?: TabItem[];
    activeId?: string;
    children?: Snippet;
  } = $props();

  const dispatch = createEventDispatcher<{ change: { activeId: string } }>();

  const setActive = (id: string) => {
    dispatch('change', { activeId: id });
  };
</script>

<div class="flex h-full flex-col">
  <div class="flex flex-wrap gap-2 border-b border-slate-200/60 pb-2">
    {#each tabs as tab}
      <button
        type="button"
        class={`rounded-full border px-3 py-1 text-xs font-semibold transition ${
          tab.id === activeId
            ? 'border-slate-200 bg-white text-slate-900'
            : 'border-transparent bg-slate-100 text-slate-500 hover:border-slate-200'
        }`}
        onclick={() => setActive(tab.id)}
      >
        {tab.title}
      </button>
    {/each}
  </div>
  <div class="mt-3 flex-1">
    {@render children?.()}
  </div>
</div>

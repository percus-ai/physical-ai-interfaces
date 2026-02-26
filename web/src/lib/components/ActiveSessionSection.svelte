<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    title,
    description = '',
    badges = [],
    actions,
    children
  }: {
    title: string;
    description?: string;
    badges?: string[];
    actions?: Snippet;
    children?: Snippet;
  } = $props();
</script>

<section class="card p-6">
  <div class="flex flex-wrap items-center justify-between gap-4">
    <div>
      <h2 class="text-xl font-semibold text-slate-900">{title}</h2>
      {#if description}
        <p class="mt-1 text-sm text-slate-600">{description}</p>
      {/if}
    </div>
    <div class="flex items-center gap-2">
      {#each badges as badge}
        <span class="chip">{badge}</span>
      {/each}
      {@render actions?.()}
    </div>
  </div>
  <div class="mt-4">
    {@render children?.()}
  </div>
</section>

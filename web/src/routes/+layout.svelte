<script lang="ts">
  import '../app.css';
  import AppShell from '$lib/components/AppShell.svelte';
  import type { Snippet } from 'svelte';
  import { Tooltip } from 'bits-ui';
  import { QueryClientProvider } from '@tanstack/svelte-query';
  import { Toaster } from 'svelte-french-toast';
  import { queryClient } from '$lib/queryClient';

  let { children }: { children?: Snippet } = $props();
</script>

<QueryClientProvider client={queryClient}>
  <Tooltip.Provider>
    <AppShell>
      {@render children?.()}
    </AppShell>
    <Toaster
      position="top-right"
      toastOptions={{
        duration: 2800
      }}
    />
  </Tooltip.Provider>
</QueryClientProvider>

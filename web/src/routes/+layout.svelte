<script lang="ts">
  import '../app.css';
  import AppShell from '$lib/components/AppShell.svelte';
  import { Tooltip } from 'bits-ui';
  import { QueryClientProvider } from '@tanstack/svelte-query';
  import { queryClient } from '$lib/queryClient';
</script>

<QueryClientProvider client={queryClient}>
  <Tooltip.Provider>
    <AppShell>
      <slot />
    </AppShell>
  </Tooltip.Provider>
</QueryClientProvider>

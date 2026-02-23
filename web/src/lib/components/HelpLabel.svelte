<script lang="ts">
  import { Tooltip } from 'bits-ui';

  let { text, help, className = 'label' }: { text: string; help: string; className?: string } = $props();
</script>

<Tooltip.Root>
  <Tooltip.Trigger type={null}>
    {#snippet child({ props })}
      <span
        {...props}
        class={`${className} cursor-help underline decoration-dotted decoration-slate-400/80 underline-offset-2`}
      >
        {text}
      </span>
    {/snippet}
  </Tooltip.Trigger>
  <Tooltip.Portal>
    <Tooltip.Content
      class="z-[80] max-w-[28rem] whitespace-pre-line rounded-lg bg-slate-900/95 px-3 py-2 text-xs text-white shadow-lg"
      sideOffset={6}
    >
      {help}
    </Tooltip.Content>
  </Tooltip.Portal>
</Tooltip.Root>

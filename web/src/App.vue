<script setup lang="ts">
/**
 * Root component. Empty on purpose: the shell owns layout, the router owns which
 * view is mounted, and Pinia/Element Plus are installed in main.ts so there is
 * exactly one place where global plugins are registered.
 */
</script>

<template>
  <RouterView />
</template>

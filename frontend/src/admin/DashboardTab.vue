<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import type { DashboardResource } from '../types'

const dashboard = ref<DashboardResource | null>(null)
const loading = ref(false)
const error = ref('')

async function refresh(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    dashboard.value = await api.admin.dashboard()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Could not load mail activity.'
  } finally {
    loading.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <section class="admin-section" aria-labelledby="dashboard-title">
    <div class="admin-section-heading">
      <div>
        <p class="eyebrow">Mail activity</p>
        <h1 id="dashboard-title">Dashboard</h1>
      </div>
      <button class="secondary-button compact-button" type="button" :disabled="loading" @click="refresh">
        {{ loading ? 'Refreshing' : 'Refresh' }}
      </button>
    </div>

    <div v-if="loading && !dashboard" class="metric-grid" aria-live="polite">
      <span v-for="index in 3" :key="index" class="skeleton metric-skeleton" />
      <span class="sr-only">Loading mail activity</span>
    </div>

    <template v-else-if="dashboard">
      <dl class="metric-grid">
        <div><dt>Stored messages</dt><dd>{{ dashboard.messages.stored }}</dd></div>
        <div><dt>Messages today</dt><dd>{{ dashboard.messages.today }}</dd></div>
        <div><dt>Messages in seven days</dt><dd>{{ dashboard.messages.sevenDays }}</dd></div>
      </dl>
    </template>

    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
  </section>
</template>

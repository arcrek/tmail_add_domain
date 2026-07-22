<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { api } from '../api'
import SandboxFrame from '../components/SandboxFrame.vue'
import type { AdminSettings, AdminSiteSettings } from '../types'

const props = defineProps<{ site: AdminSiteSettings; csrf: string }>()
const emit = defineEmits<{ updated: [settings: AdminSettings] }>()

type AdRow = { name: string; html: string }

function adRows(value: Record<string, unknown>): AdRow[] {
  return Object.entries(value)
    .filter((entry): entry is [string, string] => typeof entry[1] === 'string')
    .map(([name, html]) => ({ name, html }))
}

const draft = reactive({
  headerHtml: props.site.headerHtml,
  footerHtml: props.site.footerHtml,
  contentCss: props.site.contentCss,
  ads: adRows(props.site.adSlots),
})
const pending = ref(false)
const status = ref('')
const error = ref('')

watch(() => props.site, (value) => Object.assign(draft, {
  headerHtml: value.headerHtml,
  footerHtml: value.footerHtml,
  contentCss: value.contentCss,
  ads: adRows(value.adSlots),
}))

function addSlot(): void {
  draft.ads.push({ name: '', html: '' })
}

function removeSlot(index: number): void {
  draft.ads.splice(index, 1)
}

async function save(): Promise<void> {
  error.value = ''
  status.value = ''
  if (draft.ads.some((slot) => !slot.name.trim())) {
    error.value = 'Every ad slot needs a name.'
    return
  }
  pending.value = true
  try {
    const settings = await api.admin.updateSettings({ site: {
      headerHtml: draft.headerHtml,
      footerHtml: draft.footerHtml,
      contentCss: draft.contentCss,
      adSlots: Object.fromEntries(draft.ads.map((slot) => [slot.name.trim(), slot.html])),
    } }, props.csrf)
    emit('updated', settings)
    status.value = 'HTML and ad settings saved.'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Could not save HTML and ads.'
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <section class="admin-section" aria-labelledby="content-title">
    <p class="eyebrow">Sandboxed site content</p>
    <h1 id="content-title">HTML &amp; Ads</h1>
    <p class="admin-note">Scripts in ad HTML run in an isolated origin and cannot access inbox storage.</p>

    <form class="settings-form" @submit.prevent="save">
      <div class="content-editor-grid">
        <div class="field"><label for="header-html">Header HTML</label><textarea id="header-html" v-model="draft.headerHtml" name="headerHtml" rows="10" /></div>
        <div class="preview-field"><span>Header preview</span><SandboxFrame :html="draft.headerHtml" :css="draft.contentCss" mode="content" title="Header content preview" /></div>
      </div>
      <div class="content-editor-grid">
        <div class="field"><label for="footer-html">Footer HTML</label><textarea id="footer-html" v-model="draft.footerHtml" name="footerHtml" rows="10" /></div>
        <div class="preview-field"><span>Footer preview</span><SandboxFrame :html="draft.footerHtml" :css="draft.contentCss" mode="content" title="Footer content preview" /></div>
      </div>
      <div class="field"><label for="content-css">Content-block CSS</label><textarea id="content-css" v-model="draft.contentCss" name="contentCss" rows="10" /></div>

      <section class="ad-settings" aria-labelledby="ad-slots-title">
        <div class="subsection-heading"><h2 id="ad-slots-title">Named ad slots</h2><button class="secondary-button compact-button" type="button" @click="addSlot">Add slot</button></div>
        <div v-for="(slot, index) in draft.ads" :key="index" class="content-editor-grid ad-editor">
          <div class="field">
            <label :for="`ad-name-${index}`">Slot name</label><input :id="`ad-name-${index}`" v-model.trim="slot.name" required>
            <label :for="`ad-html-${index}`">Ad HTML</label><textarea :id="`ad-html-${index}`" v-model="slot.html" rows="9" />
            <button class="text-button danger-text" type="button" @click="removeSlot(index)">Remove slot</button>
          </div>
          <div class="preview-field"><span>{{ slot.name || 'Ad' }} preview</span><SandboxFrame :html="slot.html" :css="draft.contentCss" mode="content" :title="`${slot.name || 'Ad'} content preview`" /></div>
        </div>
        <p v-if="!draft.ads.length" class="empty-copy">No ad slots configured.</p>
      </section>

      <div class="form-actions"><button class="primary-button" type="submit" :disabled="pending">{{ pending ? 'Saving' : 'Save HTML and ads' }}</button></div>
      <p class="form-status" aria-live="polite">{{ status }}</p>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    </form>
  </section>
</template>

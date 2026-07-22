<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { api } from '../api'
import type { AdminSettings, AdminSiteSettings } from '../types'

const props = defineProps<{ site: AdminSiteSettings; csrf: string }>()
const emit = defineEmits<{ updated: [settings: AdminSettings] }>()

const draft = reactive({ ...props.site })
const pending = ref(false)
const filePending = ref(false)
const status = ref('')
const error = ref('')

watch(() => props.site, (value) => Object.assign(draft, value))

function readFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => typeof reader.result === 'string' ? resolve(reader.result) : reject(new Error('Could not read image.'))
    reader.onerror = () => reject(new Error('Could not read image.'))
    reader.readAsDataURL(file)
  })
}

async function chooseImage(event: Event, key: 'logoDataUrl' | 'faviconDataUrl'): Promise<void> {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  error.value = ''
  if (!file.type.startsWith('image/')) {
    error.value = 'Choose an image file.'
    return
  }
  if (file.size > 1024 * 1024) {
    error.value = 'Images must be no larger than 1 MiB.'
    return
  }
  filePending.value = true
  try {
    draft[key] = await readFile(file)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Could not read image.'
  } finally {
    filePending.value = false
  }
}

async function save(): Promise<void> {
  pending.value = true
  error.value = ''
  status.value = ''
  try {
    const settings = await api.admin.updateSettings({ site: { ...draft } }, props.csrf)
    emit('updated', settings)
    status.value = 'General settings saved.'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Could not save general settings.'
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <section class="admin-section" aria-labelledby="general-title">
    <p class="eyebrow">Appearance and language</p>
    <h1 id="general-title">General</h1>
    <form class="settings-form" @submit.prevent="save">
      <div class="settings-grid">
        <div class="field"><label for="app-name">App name</label><input id="app-name" v-model.trim="draft.appName" name="appName" required></div>
        <div class="field"><label for="language">Language</label><input id="language" v-model.trim="draft.language" name="language" required></div>
        <div class="field"><label for="primary-color">Primary color</label><input id="primary-color" v-model="draft.primaryColor" name="primaryColor" type="color"></div>
        <div class="field"><label for="accent-color">Accent color</label><input id="accent-color" v-model="draft.accentColor" name="accentColor" type="color"></div>
        <div class="field"><label for="logo">Logo image</label><input id="logo" name="logo" type="file" accept="image/*" @change="chooseImage($event, 'logoDataUrl')"><small>Image, 1 MiB maximum.</small></div>
        <div class="field"><label for="favicon">Favicon image</label><input id="favicon" name="favicon" type="file" accept="image/*" @change="chooseImage($event, 'faviconDataUrl')"><small>Image, 1 MiB maximum.</small></div>
      </div>
      <label class="check-field"><input v-model="draft.cookieEnabled" name="cookieEnabled" type="checkbox"> Show cookie notice</label>
      <div class="field"><label for="cookie-text">Cookie notice text</label><textarea id="cookie-text" v-model="draft.cookieText" name="cookieText" rows="4" :disabled="!draft.cookieEnabled" /></div>
      <div class="form-actions"><button class="primary-button" type="submit" :disabled="pending || filePending">{{ pending ? 'Saving' : 'Save general settings' }}</button></div>
      <p class="form-status" aria-live="polite">{{ status }}</p>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    </form>
  </section>
</template>

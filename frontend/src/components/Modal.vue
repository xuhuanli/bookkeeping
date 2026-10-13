<script setup>
import { ref, watch, nextTick, onBeforeUnmount } from 'vue'
import Icon from './Icon.vue'
const props = defineProps({ open: Boolean, title: String, subtitle: String, busy: Boolean, contentKey: Number })
const emit = defineEmits(['close'])
const dialog = ref(null)
watch(() => [props.open, props.contentKey], async ([open]) => { await nextTick(); if (!dialog.value) return; if (open) { if (!dialog.value.open) dialog.value.showModal(); dialog.value.scrollTop = 0 } else if (dialog.value.open) dialog.value.close() }, { immediate: true })
onBeforeUnmount(() => dialog.value?.close())
</script>
<template><dialog ref="dialog" class="form-dialog" @cancel.prevent="!busy && emit('close')"><div class="dialog-header"><div><h2>{{title}}</h2><p>{{subtitle}}</p></div><button class="icon-button" type="button" aria-label="关闭" :disabled="busy" @click="emit('close')"><Icon name="close" /></button></div><slot /></dialog></template>

<script setup>
import Icon from './Icon.vue'
import { money } from '../utils'
defineProps({rows:Array})
const emit=defineEmits(['edit'])
</script>
<template><button v-for="t in rows" :key="t.id" class="recent-line transaction-row" @click="emit('edit',t)"><span class="transaction-icon" :class="{expense:t.type==='expense'}"><Icon :name="t.type==='income'?'arrowdown':'arrowup'" /></span><span class="recent-detail"><strong>{{t.title}}</strong><small>{{t.category}} · {{t.date}}<template v-if="t.orderId"><br>#{{t.orderId}}</template></small></span><strong :class="{expense:t.type==='expense'}">{{t.type==='income'?'+':'−'}} ¥{{money(t.amount)}}</strong></button><div v-if="!rows.length" class="empty-state">没有符合条件的收支记录。</div></template>

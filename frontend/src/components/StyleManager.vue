<script setup>
import { ref, reactive } from 'vue'
import { money } from '../utils'
const props=defineProps({ styles:Array, busy:Boolean, error:String })
const emit=defineEmits(['save','delete','close'])
const editing=ref(null),form=reactive({name:'',price:'',cost:0})
function edit(p){editing.value=p.id;Object.assign(form,{name:p.name,price:p.price??'',cost:p.cost||0})}
function reset(){editing.value=null;Object.assign(form,{name:'',price:'',cost:0})}
async function submit(){emit('save',{id:editing.value,payload:{name:form.name,price:form.price===''?null:Number(form.price),cost:Number(form.cost)},done:reset})}
</script>
<template><div class="dialog-body"><div class="style-management"><div v-for="p in styles" :key="p.id" class="style-row"><div><strong>{{p.name}}</strong><small>{{p.price===null?'未设置单价':'¥'+money(p.price)}}</small></div><button class="btn" type="button" @click="edit(p)">编辑</button><button class="btn" type="button" @click="emit('delete',p)">移除</button></div><p v-if="!styles.length" class="form-note">还没有常用款式，在下面添加吧。</p></div><form id="style-form" @submit.prevent="submit"><h3 class="small-heading">{{editing?'编辑款式':'新增款式'}}</h3><div class="form-grid"><label class="field full">款式名称 *<input name="name" v-model="form.name" maxlength="120" placeholder="如：小花束口包 · 小号" required></label><label class="field">单价（元，可留空）<input name="price" v-model="form.price" type="number" min="0" max="9999999" step="0.01" inputmode="decimal"></label><label class="field">预估直接成本（元）<input name="cost" v-model="form.cost" type="number" min="0" max="9999999" step="0.01" inputmode="decimal" required></label></div><p v-if="error" class="inline-error" role="alert">{{error}}</p><div class="style-save"><button v-if="editing" type="button" class="btn" @click="reset">取消修改</button><button type="submit" class="btn btn-primary" :disabled="busy">{{busy?'正在保存…':editing?'保存款式':'添加款式'}}</button></div></form></div><div class="dialog-footer"><button class="btn btn-primary" type="button" @click="emit('close')">完成</button></div></template>

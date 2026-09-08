<script setup lang="ts">
/**
 * Model-config view (T3.4): CRUD + masked-key display + connectivity preflight
 * + set-default.
 *
 * The "no plaintext key" contract from T3.1 is preserved by construction: the
 * API only ever returns ``masked_api_key`` (see LlmConfig), and this view never
 * asks for a key back from the server — the create/edit form only sends a key on
 * write, and a blank key field means "keep the existing key" on edit.
 */

import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'

import { models as modelsApi } from '../api'
import { ApiError } from '../api/client'
import type { LlmConfig } from '../types'

const configs = ref<LlmConfig[]>([])
const loading = ref(false)
const errorMsg = ref('')

async function load(): Promise<void> {
  loading.value = true
  errorMsg.value = ''
  try {
    configs.value = await modelsApi.list()
  } catch (err) {
    errorMsg.value = err instanceof ApiError ? err.message : '加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)

// ── Create / edit dialog ─────────────────────────────────────────
const dialogVisible = ref(false)
const editingId = ref<string | null>(null)
const saving = ref(false)
const formRef = ref<FormInstance | null>(null)

interface ConfigForm {
  name: string
  base_url: string
  model: string
  /** Empty on edit = keep existing key. Required on create. */
  api_key: string
  params_text: string
  is_default: boolean
}

const emptyForm: ConfigForm = {
  name: '',
  base_url: '',
  model: '',
  api_key: '',
  params_text: '',
  is_default: false,
}

const form = reactive<ConfigForm>({ ...emptyForm })

const rules: FormRules<ConfigForm> = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  base_url: [{ required: true, message: '请输入 Base URL', trigger: 'blur' }],
  model: [{ required: true, message: '请输入模型名', trigger: 'blur' }],
  // api_key required only on create
  api_key: [
    {
      validator: (_r, value: string, cb) => {
        if (!editingId.value && !value) cb(new Error('新建时必须填写 API Key'))
        else cb()
      },
      trigger: 'blur',
    },
  ],
}

function openCreate() {
  editingId.value = null
  Object.assign(form, emptyForm)
  dialogVisible.value = true
  formRef.value?.clearValidate()
}

function openEdit(row: LlmConfig) {
  editingId.value = row.id
  Object.assign(form, {
    name: row.name,
    base_url: row.base_url,
    model: row.model,
    api_key: '', // never prefilled — keep existing server-side
    params_text: row.params ? JSON.stringify(row.params, null, 2) : '',
    is_default: row.is_default,
  })
  dialogVisible.value = true
  formRef.value?.clearValidate()
}

async function onSubmit() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    saving.value = true
    try {
      let params: Record<string, unknown> | null = null
      const text = form.params_text.trim()
      if (text) {
        try {
          params = JSON.parse(text)
        } catch {
          ElMessage.error('参数(JSON) 格式错误')
          saving.value = false
          return
        }
      }
      if (editingId.value) {
        await modelsApi.update(editingId.value, {
          name: form.name,
          base_url: form.base_url,
          model: form.model,
          // only send key when the user actually typed one
          ...(form.api_key ? { api_key: form.api_key } : {}),
          params,
          is_default: form.is_default,
        })
        ElMessage.success('已更新')
      } else {
        await modelsApi.create({
          name: form.name,
          base_url: form.base_url,
          model: form.model,
          api_key: form.api_key,
          params,
          is_default: form.is_default,
        })
        ElMessage.success('已创建')
      }
      dialogVisible.value = false
      await load()
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : '保存失败'
      ElMessage.error(msg)
    } finally {
      saving.value = false
    }
  })
}

async function onDelete(row: LlmConfig) {
  try {
    await ElMessageBox.confirm(
      `确定删除配置「${row.name}」？${row.is_default ? '该配置为默认配置，删除后需重新设置。' : ''}`,
      '删除模型配置',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await modelsApi.remove(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (err) {
    const msg = err instanceof ApiError ? err.message : '删除失败'
    ElMessage.error(msg)
  }
}

// ── Set default ──────────────────────────────────────────────────
async function onSetDefault(row: LlmConfig) {
  if (row.is_default) return
  try {
    await modelsApi.update(row.id, { is_default: true })
    ElMessage.success(`已将「${row.name}」设为默认`)
    await load()
  } catch (err) {
    const msg = err instanceof ApiError ? err.message : '设默认失败'
    ElMessage.error(msg)
  }
}

// ── Connectivity preflight ───────────────────────────────────────
const testingId = ref<string | null>(null)

async function onTest(row: LlmConfig) {
  testingId.value = row.id
  try {
    const res = await modelsApi.test(row.id)
    if (res.ok) {
      ElMessage.success(`连通性正常：${res.detail}`)
    } else {
      // backend detail is a key-free summary by contract
      ElMessage.warning(`预检未通过：${res.detail}`)
    }
  } catch (err) {
    const msg = err instanceof ApiError ? err.message : '预检请求失败'
    ElMessage.error(msg)
  } finally {
    testingId.value = null
  }
}
</script>

<template>
  <div class="models">
    <el-card shadow="never" class="models__card">
      <template #header>
        <div class="models__header">
          <span>模型配置</span>
          <div class="models__actions">
            <el-button size="small" :loading="loading" @click="load">刷新</el-button>
            <el-button size="small" type="primary" @click="openCreate">新增配置</el-button>
          </div>
        </div>
      </template>

      <el-alert v-if="errorMsg" :title="errorMsg" type="error" :closable="false" />

      <el-table :data="configs" v-loading="loading" size="small" empty-text="暂无配置，点击「新增配置」">
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column prop="base_url" label="Base URL" min-width="200" show-overflow-tooltip />
        <el-table-column prop="model" label="模型" min-width="140" />
        <el-table-column label="API Key" min-width="140">
          <template #default="{ row }">
            <code class="masked">{{ row.masked_api_key }}</code>
          </template>
        </el-table-column>
        <el-table-column label="连通性" min-width="90" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.last_verify_ok === true" size="small" type="success">已验证</el-tag>
            <el-tag v-else-if="row.last_verify_ok === false" size="small" type="danger">失败</el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="默认" width="70" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.is_default" size="small" type="success">默认</el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="240" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="onTest(row)" :loading="testingId === row.id">
              预检
            </el-button>
            <el-button size="small" text type="primary" @click="onSetDefault(row)" :disabled="row.is_default">
              设默认
            </el-button>
            <el-button size="small" text type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" text type="danger" @click="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑模型配置' : '新增模型配置'"
      width="520px"
      data-testid="config-dialog"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="110px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="如 my-openai" data-testid="cfg-name" />
        </el-form-item>
        <el-form-item label="Base URL" prop="base_url">
          <el-input v-model="form.base_url" placeholder="https://api.openai.com/v1" data-testid="cfg-base-url" />
        </el-form-item>
        <el-form-item label="模型" prop="model">
          <el-input v-model="form.model" placeholder="gpt-4o" data-testid="cfg-model" />
        </el-form-item>
        <el-form-item :label="editingId ? 'API Key(留空不改)' : 'API Key'" prop="api_key">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            :placeholder="editingId ? '留空则保留原 Key' : 'sk-...'"
            autocomplete="new-password"
            data-testid="cfg-api-key"
          />
        </el-form-item>
        <el-form-item label="额外参数(JSON)">
          <el-input
            v-model="form.params_text"
            type="textarea"
            :rows="3"
            placeholder='可选，如 {"temperature": 0.7}'
            data-testid="cfg-params"
          />
        </el-form-item>
        <el-form-item label="设为默认">
          <el-switch v-model="form.is_default" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSubmit" data-testid="cfg-save">
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.models__card {
  max-width: 1100px;
  margin: 0 auto;
}

.models__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.models__actions {
  display: flex;
  gap: 8px;
}

.masked {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>

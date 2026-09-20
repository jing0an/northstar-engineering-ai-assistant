const viteEnv = (import.meta as ImportMeta & {env?: {VITE_API_BASE_URL?: string}}).env
export const API_BASE_URL = viteEnv?.VITE_API_BASE_URL ?? 'http://127.0.0.1:8002'

export interface HealthResponse {
  status: string
}

export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/api/health`)
  if (!response.ok) throw new Error(`Health check failed: ${response.status}`)
  return response.json() as Promise<HealthResponse>
}

const TOKEN_KEY = 'northstar.access_token'
const USER_KEY = 'northstar.current_user'
export interface LoginResponse { access_token: string; token_type: string; expires_in: number }
export interface CurrentUser { user_id: string }
export interface RegisterResponse {
  user_id: string
  username: string
  email: string
  email_verified: boolean
  status: string
}
export interface Project {
  project_id: string
  name: string
  status: string
  owner_user_id: string
  created_at: string
  updated_at: string
}

export function getAccessToken(): string | null { return localStorage.getItem(TOKEN_KEY) }
export function getCurrentUser(): CurrentUser | null {
  const value = localStorage.getItem(USER_KEY)
  if (!value) return null
  try { return JSON.parse(value) as CurrentUser } catch { localStorage.removeItem(USER_KEY); return null }
}
export function clearAuth(): void { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY) }
export async function login(identifier: string, password: string): Promise<LoginResponse> {
  const response = await fetch(`${API_BASE_URL}/api/auth/login`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({identifier, password}) })
  if (!response.ok) throw new Error(response.status === 401 ? '用户名或密码错误' : `登录失败（${response.status}）`)
  const data = await response.json() as LoginResponse
  localStorage.setItem(TOKEN_KEY, data.access_token)
  try { const encoded = data.access_token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'); const claims = JSON.parse(atob(encoded + '='.repeat((4 - encoded.length % 4) % 4))); localStorage.setItem(USER_KEY, JSON.stringify({user_id: claims.sub ?? ''})) } catch { localStorage.setItem(USER_KEY, JSON.stringify({user_id: ''})) }
  return data
}

export async function register(username: string, email: string, password: string): Promise<RegisterResponse> {
  const response = await fetch(`${API_BASE_URL}/api/auth/register`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({username, email, password}),
  })
  if (!response.ok) {
    let detail = '注册失败，请稍后重试。'
    try {
      const data = await response.json() as { detail?: string }
      if (typeof data.detail === 'string') detail = data.detail
    } catch {
      // Keep the generic message when the server does not return JSON.
    }
    throw new Error(detail)
  }
  return response.json() as Promise<RegisterResponse>
}
export async function authenticatedFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  const token = getAccessToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(input, {...init, headers})
  if (response.status === 401) { clearAuth(); window.dispatchEvent(new CustomEvent('northstar-auth-expired')) }
  return response
}

export type AssistantStatus = 'answered' | 'no_evidence'

export interface AssistantCitation {
  original_filename: string
  document_version: number | null
  page_number: number | null
  chunk_index: number | null
}

export interface AssistantResponse {
  reply: string
  status: AssistantStatus
  citations: AssistantCitation[]
  sources?: AssistantCitation[]
  tool?: string
}

export interface AssistantErrorPayload {
  error?: {
    code?: string
    message?: string
  }
}

export class AssistantApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'AssistantApiError'
    this.status = status
    this.code = code
  }
}

function assistantErrorMessage(status: number, code?: string): string {
  if (status === 401) return '登录已失效，请重新登录。'
  if (status === 403) return '你没有当前项目的访问权限。'
  if (status === 422) return '请求参数错误，请检查问题和当前项目。'
  if (status === 503 && code === 'rag_unavailable') return '项目资料检索服务当前不可用，请稍后重试。'
  if (status === 503) return 'AI 模型当前不可用，请稍后重试。'
  if (status === 500 && code === 'citation_generation_failed') return '回答来源生成失败，请稍后重试。'
  if (status === 500) return '助理服务发生内部错误，请稍后重试。'
  return `对话请求失败（${status}）`
}

export function createConversationId(): string {
  return crypto.randomUUID()
}

export function conversationIdForProjectChange(
  currentProjectId: string | null,
  nextProjectId: string | null,
  currentConversationId: string,
): string {
  return currentProjectId === nextProjectId ? currentConversationId : createConversationId()
}

export async function requestAssistant(
  message: string,
  projectId: string,
  conversationId: string,
): Promise<AssistantResponse> {
  let response: Response
  try {
    response = await authenticatedFetch(`${API_BASE_URL}/api/assistant`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        message,
        project_id: projectId,
        conversation_id: conversationId,
      }),
    })
  } catch {
    throw new AssistantApiError(0, 'network_error', '网络异常，对话请求失败，请检查连接后重试。')
  }

  let data: AssistantResponse | AssistantErrorPayload | null = null
  try {
    data = await response.json() as AssistantResponse | AssistantErrorPayload
  } catch {
    // Fall through to the status-specific safe message.
  }

  if (!response.ok) {
    const error = data && 'error' in data ? data.error : undefined
    const code = error?.code ?? 'request_failed'
    throw new AssistantApiError(response.status, code, assistantErrorMessage(response.status, code))
  }

  const success = data as Partial<AssistantResponse> | null
  return {
    reply: typeof success?.reply === 'string' ? success.reply : '',
    status: success?.status === 'no_evidence' ? 'no_evidence' : 'answered',
    citations: Array.isArray(success?.citations) ? success.citations : [],
    sources: Array.isArray(success?.sources) ? success.sources : undefined,
    tool: typeof success?.tool === 'string' ? success.tool : undefined,
  }
}

async function authenticatedJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await authenticatedFetch(`${API_BASE_URL}${path}`, init)
  if (!response.ok) throw new Error(`Project request failed (${response.status})`)
  return response.json() as Promise<T>
}

export function getProjects(): Promise<Project[]> {
  return authenticatedJson<Project[]>('/api/projects')
}

export function createProject(name: string): Promise<Project> {
  return authenticatedJson<Project>('/api/projects', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name}),
  })
}

export function getProject(projectId: string): Promise<Project> {
  return authenticatedJson<Project>(`${'/api/projects/'}${encodeURIComponent(projectId)}`)
}

export interface FileMetadata {
  file_id: string
  project_id?: string
  original_filename: string
  file_type: string
  size: number
  uploaded_at: string
  document_version: number | null
  is_current: boolean | null
  is_duplicate?: boolean
  duplicate_of_file_id?: string | null
  ingestion_status?: 'processing' | 'completed' | 'failed'
  chunk_count?: number | null
  vector_count?: number | null
  ingestion_error?: {
    stage?: string
    message?: string
  } | null
  ingestion_started_at?: string | null
  ingestion_completed_at?: string | null
}

export interface FilesResponse {
  project_id: string
  files: FileMetadata[]
}

export interface UploadIngestionResult {
  status: 'completed'
  chunk_count: number
  vector_count: number
}

export interface ReingestFileResponse extends FileMetadata {
  project_id: string
  stored_filename: string
  ingestion: UploadIngestionResult
}

export interface UploadFileResponse extends FileMetadata {
  project_id: string
  stored_filename: string
  is_duplicate: boolean
  duplicate_of_file_id?: string | null
  ingestion: UploadIngestionResult
}

export function getFiles(projectId: string): Promise<FilesResponse> {
  return authenticatedJson<FilesResponse>(`/api/files?project_id=${encodeURIComponent(projectId)}`)
}

export type DocxPreviewBlock =
  | {type: 'heading'; level: number; text: string}
  | {type: 'paragraph'; text: string}
  | {type: 'list'; items: string[]}
  | {type: 'table'; rows: string[][]}
  | {type: 'image'; count: number; available: boolean}

export interface DocxPreview {
  file_id: string
  project_id: string
  document_version: number | null
  file_type: 'docx'
  original_filename: string
  blocks: DocxPreviewBlock[]
}

export async function getFileContent(projectId: string, fileId: string): Promise<Blob> {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/files/${encodeURIComponent(fileId)}/content?project_id=${encodeURIComponent(projectId)}`,
  )
  if (!response.ok) throw new Error(`文档预览请求失败（${response.status}）`)
  const contentType = response.headers.get('content-type')?.split(';', 1)[0].trim().toLowerCase()
  if (contentType !== 'application/pdf') throw new Error('文档预览响应格式不正确')
  return response.blob()
}

export async function getFilePreview(projectId: string, fileId: string): Promise<DocxPreview> {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/files/${encodeURIComponent(fileId)}/preview?project_id=${encodeURIComponent(projectId)}`,
  )
  if (!response.ok) throw new Error(`文档预览请求失败（${response.status}）`)
  const contentType = response.headers.get('content-type')?.split(';', 1)[0].trim().toLowerCase()
  if (contentType !== 'application/json') throw new Error('文档预览响应格式不正确')
  return response.json() as Promise<DocxPreview>
}

function uploadErrorMessage(status: number, detail?: unknown): string {
  if (typeof detail === 'string' && detail.trim() && !/traceback/i.test(detail)) {
    return detail
  }

  switch (status) {
    case 400:
      return '文件上传失败：文件格式或内容不符合要求。'
    case 401:
      return '登录已失效，请重新登录。'
    case 403:
      return '你没有当前项目的上传权限。'
    case 500:
      return '文件上传失败，服务处理异常，请稍后重试。'
    default:
      return `文件上传失败（${status}）`
  }
}

export async function uploadFile(projectId: string, file: File): Promise<UploadFileResponse> {
  const formData = new FormData()
  formData.append('project_id', projectId)
  formData.append('file', file)

  let response: Response
  try {
    response = await authenticatedFetch(`${API_BASE_URL}/api/files/upload`, {
      method: 'POST',
      body: formData,
    })
  } catch {
    throw new Error('网络异常，文件上传失败，请检查连接后重试。')
  }

  if (!response.ok) {
    let detail: unknown
    try {
      detail = (await response.json() as { detail?: unknown }).detail
    } catch {
      // Use the status-specific fallback when the server does not return JSON.
    }
    throw new Error(uploadErrorMessage(response.status, detail))
  }

  return response.json() as Promise<UploadFileResponse>
}

export async function reingestFile(projectId: string, fileId: string): Promise<ReingestFileResponse> {
  const formData = new FormData()
  formData.append('project_id', projectId)

  let response: Response
  try {
    response = await authenticatedFetch(
      `${API_BASE_URL}/api/files/${encodeURIComponent(fileId)}/reingest`,
      {method: 'POST', body: formData},
    )
  } catch {
    throw new Error('网络异常，文件重新入库失败，请检查连接后重试。')
  }

  if (!response.ok) {
    let detail: unknown
    try {
      detail = (await response.json() as { detail?: unknown }).detail
    } catch {
      // Use the status-specific fallback when the server does not return JSON.
    }
    throw new Error(uploadErrorMessage(response.status, detail)?.replace('上传', '重新入库'))
  }

  return response.json() as Promise<ReingestFileResponse>
}

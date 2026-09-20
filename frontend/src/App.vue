<script setup lang="ts">
import {computed, nextTick, onBeforeUnmount, onMounted, ref} from 'vue'
import {marked} from 'marked'
import DOMPurify from 'dompurify'
import * as pdfjsLib from 'pdfjs-dist'
import {API_BASE_URL, authenticatedFetch, clearAuth, conversationIdForProjectChange, createConversationId, createProject as createProjectApi, getAccessToken, getCurrentUser, getProjects, getFiles, getFileContent, getFilePreview, login, register, reingestFile, requestAssistant, uploadFile, type AssistantResponse, type DocxPreview, type FileMetadata, type Project} from './services/api'

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString()

type PdfLoadingTask = ReturnType<typeof pdfjsLib.getDocument>
type PdfDocument = Awaited<PdfLoadingTask['promise']>
type PdfRenderTask = ReturnType<Awaited<ReturnType<PdfDocument['getPage']>>['render']>

const connected = ref(false)
const authenticated = ref(Boolean(getAccessToken()))
const currentUser = ref(getCurrentUser())
const identifier = ref('')
const password = ref('')
const loginError = ref('')
const loginBusy = ref(false)
const registering = ref(false)
const registerUsername = ref('')
const registerEmail = ref('')
const registerPassword = ref('')
const registerPasswordConfirm = ref('')
const registerError = ref('')
const registerSuccess = ref('')
const registerBusy = ref(false)
const activeNav = ref('助理')
const input = ref('')
const messages = ref<string[]>([])
const assistantResponses = ref<(AssistantResponse | null)[]>([])
const conversationId = ref(createConversationId())
const loading = ref(false)
const requestError = ref('')
const selectedFile = ref<File | null>(null)
const selectedFileName = ref('')
const uploadStatus = ref('')
const uploadError = ref('')
const uploadBusy = ref(false)
const showCreateProject = ref(false)
const projectName = ref('')
const projects = ref<Project[]>([])
const currentProjectId = ref<string | null>(null)
const projectLoading = ref(false)
const projectLoadError = ref('')
const projectCreateError = ref('')
const projectSwitcherOpen = ref(false)
const currentProject = computed(() => projects.value.find((project) => project.project_id === currentProjectId.value) ?? null)
const projectTitle = computed(() => currentProject.value?.name ?? '暂无项目')
const files = ref<FileMetadata[]>([])
const filesLoading = ref(false)
const filesError = ref('')
const reingestingFileIds = ref(new Set<string>())
const selectedFileDetail = ref<FileMetadata | null>(null)
const documentPreviewLoading = ref(false)
const documentPreviewError = ref('')
const pdfPages = ref<Array<{pageNumber: number}>>([])
const documentScrollContainer = ref<HTMLElement | null>(null)
const docxPreview = ref<DocxPreview | null>(null)
const pdfCanvasRefs = new Map<number, HTMLCanvasElement>()
const PDF_ZOOM_LEVELS = [0.5, 0.6, 0.75, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3] as const
const pdfZoom = ref(1)
const currentPdfPage = ref(1)
const pdfPageInput = ref('1')
const pdfControlsDisabled = computed(() => documentPreviewLoading.value || Boolean(documentPreviewError.value) || !pdfPages.value.length)
const canZoomOut = computed(() => !pdfControlsDisabled.value && pdfZoom.value > PDF_ZOOM_LEVELS[0])
const canZoomIn = computed(() => !pdfControlsDisabled.value && pdfZoom.value < PDF_ZOOM_LEVELS[PDF_ZOOM_LEVELS.length - 1])
const pdfZoomPercent = computed(() => Math.round(pdfZoom.value * 100))
const pdfZoomIsPreset = computed(() => PDF_ZOOM_LEVELS.some((level) => Math.abs(level - pdfZoom.value) < 0.001))
let previewRequestId = 0
let activePdfLoadingTask: PdfLoadingTask | null = null
let activePdfDocument: PdfDocument | null = null
const activePdfRenderTasks = new Set<PdfRenderTask>()
let pdfRenderGeneration = 0
let pdfScrollFrame: number | null = null

interface LocalConversation {
  conversation_id: string
  project_id: string
  title: string
  pinned: boolean
  created_at: string
  updated_at: string
  messages: string[]
  assistantResponses: (AssistantResponse | null)[]
}

const CONVERSATIONS_STORAGE_KEY = 'northstar-ui-2c-conversations'
const CURRENT_CONVERSATIONS_STORAGE_KEY = 'northstar-ui-2c-current-conversations'

function readStoredConversations(): LocalConversation[] {
  try {
    const value = JSON.parse(localStorage.getItem(CONVERSATIONS_STORAGE_KEY) ?? '[]') as unknown
    if (!Array.isArray(value)) return []
    return value.filter((item): item is LocalConversation => {
      if (!item || typeof item !== 'object') return false
      const conversation = item as Partial<LocalConversation>
      return typeof conversation.conversation_id === 'string'
        && typeof conversation.project_id === 'string'
        && typeof conversation.title === 'string'
        && Array.isArray(conversation.messages)
        && Array.isArray(conversation.assistantResponses)
    })
  } catch {
    return []
  }
}

function readCurrentConversationMap(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(CURRENT_CONVERSATIONS_STORAGE_KEY) ?? '{}') as Record<string, string>
  } catch {
    return {}
  }
}

const conversations = ref<LocalConversation[]>(typeof localStorage === 'undefined' ? [] : readStoredConversations())
const currentConversationByProject = ref<Record<string, string>>(typeof localStorage === 'undefined' ? {} : readCurrentConversationMap())
const editingConversationId = ref<string | null>(null)
const editingConversationTitle = ref('')
const selectedSetting = ref('账号')

type ThemePreference = 'light' | 'dark' | 'system'

const UI_STORAGE_KEY = 'northstar-ui-2a-layout'
const THEME_STORAGE_KEY = 'northstar-theme'
const viewportWidth = ref(typeof window === 'undefined' ? 1440 : window.innerWidth)
const searchOpen = ref(false)
const notificationOpen = ref(false)
const themeMenuOpen = ref(false)
const userMenuOpen = ref(false)
const searchQuery = ref('')
const searchInput = ref<HTMLInputElement | null>(null)

function storedNumber(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function readStoredLayout() {
  try {
    return JSON.parse(localStorage.getItem(UI_STORAGE_KEY) ?? '{}') as Record<string, unknown>
  } catch {
    return {} as Record<string, unknown>
  }
}

const storedLayout = typeof localStorage === 'undefined' ? {} : readStoredLayout()
const availableWorkspaceWidth = Math.max(viewportWidth.value - 248, 760)
const sidebarCollapsed = ref(storedLayout.sidebarCollapsed === true)
const contextPanelWidth = ref(storedNumber(storedLayout.contextPanelWidth ?? storedLayout.rightWidth, Math.round(availableWorkspaceWidth * .25)))
const contextPanelOpen = ref((storedLayout.contextPanelOpen ?? storedLayout.rightOpen) !== false)
const storedTheme = typeof localStorage === 'undefined' ? null : localStorage.getItem(THEME_STORAGE_KEY)
const themePreference = ref<ThemePreference>(
  storedTheme === 'light' || storedTheme === 'dark' || storedTheme === 'system'
    ? storedTheme
    : 'system',
)

const sidebarEffectivelyCollapsed = computed(() => sidebarCollapsed.value || viewportWidth.value <= 768)
const contextPanelVisible = computed(() => contextPanelOpen.value && viewportWidth.value >= 768)
const latestAssistantResponse = computed(() => {
  for (let index = assistantResponses.value.length - 1; index >= 0; index -= 1) {
    const response = assistantResponses.value[index]
    if (response) return response
  }
  return null
})
const workspaceGridStyle = computed(() => {
  if (!contextPanelVisible.value) return { gridTemplateColumns: 'minmax(360px, 1fr)' }
  const width = Math.min(Math.max(contextPanelWidth.value, 240), 420)
  return { gridTemplateColumns: `minmax(360px, 1fr) 6px minmax(240px, ${width}px)` }
})
const panelTitle = computed(() => ({
  项目: '我的项目',
  资料: '项目资料',
  助理: '我的对话',
  风险: '风险列表',
  设置: '设置分类',
}[activeNav.value] ?? '列表'))
const projectConversations = computed(() => conversations.value
  .filter((conversation) => conversation.project_id === currentProjectId.value)
  .sort((left, right) => Number(right.pinned) - Number(left.pinned) || right.updated_at.localeCompare(left.updated_at)))
const currentConversation = computed(() => conversations.value.find((conversation) => conversation.conversation_id === conversationId.value) ?? null)

function persistLayout() {
  try {
    localStorage.setItem(UI_STORAGE_KEY, JSON.stringify({
      sidebarCollapsed: sidebarCollapsed.value,
      contextPanelWidth: contextPanelWidth.value,
      contextPanelOpen: contextPanelOpen.value,
    }))
  } catch {
    // Storage may be unavailable in privacy-restricted browser contexts.
  }
}

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  persistLayout()
}

function closeContextPanel() {
  contextPanelOpen.value = false
  persistLayout()
}

function restoreContextPanel() {
  contextPanelOpen.value = true
  persistLayout()
}

function startContextResize(event: PointerEvent) {
  if (event.button !== 0) return
  event.preventDefault()
  const startX = event.clientX
  const startWidth = contextPanelWidth.value
  document.body.classList.add('is-resizing-workbench')

  const move = (moveEvent: PointerEvent) => {
    const delta = moveEvent.clientX - startX
    contextPanelWidth.value = Math.min(Math.max(startWidth - delta, 240), 420)
  }
  const stop = () => {
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', stop)
    document.body.classList.remove('is-resizing-workbench')
    persistLayout()
  }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', stop, { once: true })
}

function closeHeaderPanels() {
  searchOpen.value = false
  notificationOpen.value = false
  themeMenuOpen.value = false
  userMenuOpen.value = false
  projectSwitcherOpen.value = false
}

function openSearch() {
  notificationOpen.value = false
  themeMenuOpen.value = false
  userMenuOpen.value = false
  searchOpen.value = true
  void nextTick(() => searchInput.value?.focus())
}

function toggleHeaderPanel(panel: 'notification' | 'theme' | 'user') {
  const next = panel === 'notification'
    ? !notificationOpen.value
    : panel === 'theme'
      ? !themeMenuOpen.value
      : !userMenuOpen.value
  closeHeaderPanels()
  if (panel === 'notification') notificationOpen.value = next
  if (panel === 'theme') themeMenuOpen.value = next
  if (panel === 'user') userMenuOpen.value = next
}

function applyTheme(theme: ThemePreference) {
  themePreference.value = theme
  document.documentElement.dataset.theme = theme
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme)
  } catch {
    // The selected theme still applies for the current session.
  }
}

function handleGlobalKeydown(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    openSearch()
    return
  }
  if (event.key === 'Escape') closeHeaderPanels()
}

function handleViewportResize() {
  viewportWidth.value = window.innerWidth
}

function handleComposerKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey) return
  event.preventDefault()
  void sendMessage()
}

function persistConversations() {
  try {
    localStorage.setItem(CONVERSATIONS_STORAGE_KEY, JSON.stringify(conversations.value))
    localStorage.setItem(CURRENT_CONVERSATIONS_STORAGE_KEY, JSON.stringify(currentConversationByProject.value))
  } catch {
    // Keep the conversation list available for this session if storage is unavailable.
  }
}

function saveCurrentConversationSnapshot() {
  if (!currentProjectId.value) return
  const conversation = conversations.value.find((item) => item.conversation_id === conversationId.value)
  if (!conversation) return
  conversation.messages = [...messages.value]
  conversation.assistantResponses = [...assistantResponses.value]
  persistConversations()
}

function createLocalConversation(projectId: string, id = createConversationId()): LocalConversation {
  const now = new Date().toISOString()
  return {
    conversation_id: id,
    project_id: projectId,
    title: '新对话',
    pinned: false,
    created_at: now,
    updated_at: now,
    messages: [],
    assistantResponses: [],
  }
}

function openConversation(conversation: LocalConversation) {
  if (conversation.project_id !== currentProjectId.value || loading.value) return
  saveCurrentConversationSnapshot()
  conversationId.value = conversation.conversation_id
  currentConversationByProject.value[conversation.project_id] = conversation.conversation_id
  messages.value = [...conversation.messages]
  assistantResponses.value = [...conversation.assistantResponses]
  input.value = ''
  requestError.value = ''
  editingConversationId.value = null
  persistConversations()
}

function activateProjectConversation(previousProjectId: string | null, projectId: string) {
  const preferredId = currentConversationByProject.value[projectId]
  const existing = conversations.value.find((item) => item.project_id === projectId && item.conversation_id === preferredId)
    ?? conversations.value.filter((item) => item.project_id === projectId).sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0]
  if (existing) {
    conversationId.value = existing.conversation_id
    currentConversationByProject.value[projectId] = existing.conversation_id
    messages.value = [...existing.messages]
    assistantResponses.value = [...existing.assistantResponses]
  } else {
    const nextId = conversationIdForProjectChange(previousProjectId, projectId, conversationId.value)
    const created = createLocalConversation(projectId, nextId)
    conversations.value.push(created)
    conversationId.value = created.conversation_id
    currentConversationByProject.value[projectId] = created.conversation_id
    messages.value = []
    assistantResponses.value = []
  }
  input.value = ''
  requestError.value = ''
  persistConversations()
}

function newConversation() {
  if (!currentProjectId.value || loading.value) return
  saveCurrentConversationSnapshot()
  const created = createLocalConversation(currentProjectId.value)
  conversations.value.push(created)
  openConversation(created)
}

function beginRenameConversation(conversation: LocalConversation) {
  editingConversationId.value = conversation.conversation_id
  editingConversationTitle.value = conversation.title
}

function commitConversationRename(conversation: LocalConversation) {
  const title = editingConversationTitle.value.trim()
  if (title) {
    conversation.title = title.slice(0, 80)
    conversation.updated_at = new Date().toISOString()
    persistConversations()
  }
  editingConversationId.value = null
}

function toggleConversationPinned(conversation: LocalConversation) {
  conversation.pinned = !conversation.pinned
  persistConversations()
}

function deleteConversation(conversation: LocalConversation) {
  if (!window.confirm(`仅从此设备的对话列表中删除“${conversation.title}”？`)) return
  const wasCurrent = conversation.conversation_id === conversationId.value
  conversations.value = conversations.value.filter((item) => item.conversation_id !== conversation.conversation_id)
  if (wasCurrent) {
    const next = conversations.value
      .filter((item) => item.project_id === conversation.project_id)
      .sort((a, b) => Number(b.pinned) - Number(a.pinned) || b.updated_at.localeCompare(a.updated_at))[0]
    if (next) openConversation(next)
    else {
      const created = createLocalConversation(conversation.project_id)
      conversations.value.push(created)
      openConversation(created)
    }
  } else {
    persistConversations()
  }
}

function setCurrentProject(projectId: string | null) {
  if (projectId === currentProjectId.value) return
  saveCurrentConversationSnapshot()
  clearDocumentPreview()
  const previousProjectId = currentProjectId.value
  currentProjectId.value = projectId
  selectedFileDetail.value = null
  if (projectId) activateProjectConversation(previousProjectId, projectId)
  else {
    conversationId.value = conversationIdForProjectChange(previousProjectId, null, conversationId.value)
    messages.value = []
    assistantResponses.value = []
  }
}

async function loadProjects() {
  projectLoading.value = true
  projectLoadError.value = ''
  try {
    projects.value = await getProjects()
    if (!projects.value.some((project) => project.project_id === currentProjectId.value)) {
      setCurrentProject(projects.value[0]?.project_id ?? null)
    }
  } catch {
    projectLoadError.value = '项目加载失败'
  } finally {
    projectLoading.value = false
  }
}

async function loadFiles() {
  const projectId = currentProjectId.value
  if (!projectId) {
    files.value = []
    filesError.value = '未选择项目'
    filesLoading.value = false
    return
  }
  filesLoading.value = true
  filesError.value = ''

  try {
    const response = await getFiles(projectId)
    if (currentProjectId.value === projectId) {
      files.value = response.files
      if (selectedFileDetail.value) {
        const refreshedFile = response.files.find((file) => file.file_id === selectedFileDetail.value?.file_id) ?? null
        selectedFileDetail.value = refreshedFile
        if (!refreshedFile) clearDocumentPreview()
      }
    }
  } catch (error) {
    if (currentProjectId.value === projectId) {
      filesError.value = error instanceof Error ? error.message : '加载文件列表失败'
    }
  } finally {
    if (currentProjectId.value === projectId) {
      filesLoading.value = false
    }
  }
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatUploadTime(isoString: string): string {
  const date = new Date(isoString)
  if (Number.isNaN(date.getTime())) return isoString
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

function ingestionStatusLabel(file: FileMetadata): string {
  switch (file.ingestion_status) {
    case 'processing': return '处理中'
    case 'completed': return '已完成'
    case 'failed': return '入库失败'
    default: return '状态未知'
  }
}

function ingestionDetails(file: FileMetadata): string {
  if (file.ingestion_status === 'completed') {
    return `${file.chunk_count ?? 0} 文本块 · ${file.vector_count ?? 0} 向量`
  }
  if (file.ingestion_status === 'failed') {
    const stage = file.ingestion_error?.stage
    return stage ? `失败阶段：${stage}` : '未返回失败阶段'
  }
  return ''
}

function ingestionErrorMessage(file: FileMetadata): string {
  return file.ingestion_status === 'failed'
    ? file.ingestion_error?.message || '文件入库失败，请重新入库。'
    : ''
}

function isReingesting(fileId: string): boolean {
  return reingestingFileIds.value.has(fileId)
}

function updateFile(fileId: string, updater: (file: FileMetadata) => FileMetadata) {
  files.value = files.value.map((file) => file.file_id === fileId ? updater(file) : file)
  if (selectedFileDetail.value?.file_id === fileId) selectedFileDetail.value = updater(selectedFileDetail.value)
}

function setPdfCanvasRef(element: unknown, pageNumber: number) {
  if (element instanceof HTMLCanvasElement) pdfCanvasRefs.set(pageNumber, element)
  else pdfCanvasRefs.delete(pageNumber)
}

function isPreviewCurrent(requestId: number, projectId: string, fileId: string): boolean {
  return requestId === previewRequestId
    && currentProjectId.value === projectId
    && selectedFileDetail.value?.file_id === fileId
}

function cancelActivePdfRenders() {
  pdfRenderGeneration += 1
  for (const renderTask of activePdfRenderTasks) renderTask.cancel()
  activePdfRenderTasks.clear()
}

function setCurrentPdfPage(pageNumber: number) {
  currentPdfPage.value = pageNumber
  pdfPageInput.value = String(pageNumber)
}

function clearDocumentPreview() {
  previewRequestId += 1
  if (documentScrollContainer.value) documentScrollContainer.value.scrollTop = 0
  if (pdfScrollFrame !== null) cancelAnimationFrame(pdfScrollFrame)
  pdfScrollFrame = null
  documentPreviewLoading.value = false
  documentPreviewError.value = ''
  pdfPages.value = []
  docxPreview.value = null
  pdfCanvasRefs.clear()
  pdfZoom.value = 1
  setCurrentPdfPage(1)

  cancelActivePdfRenders()
  if (activePdfLoadingTask) void activePdfLoadingTask.destroy()
  if (activePdfDocument) void activePdfDocument.destroy()
  activePdfLoadingTask = null
  activePdfDocument = null
}

async function renderPdfPages(pdfDocument: PdfDocument, requestId: number, projectId: string, fileId: string) {
  if (!isPreviewCurrent(requestId, projectId, fileId)) return
  cancelActivePdfRenders()
  const renderGeneration = pdfRenderGeneration
  const renderScale = pdfZoom.value
  pdfPages.value = Array.from({length: pdfDocument.numPages}, (_, index) => ({pageNumber: index + 1}))
  await nextTick()
  if (!pdfPages.value.length || pdfCanvasRefs.size !== pdfPages.value.length) {
    throw new Error('PDF 页面 canvas 尚未完成挂载')
  }

  for (const {pageNumber} of pdfPages.value) {
    if (renderGeneration !== pdfRenderGeneration || !isPreviewCurrent(requestId, projectId, fileId)) return
    const page = await pdfDocument.getPage(pageNumber)
    if (renderGeneration !== pdfRenderGeneration || !isPreviewCurrent(requestId, projectId, fileId)) return
    const canvas = pdfCanvasRefs.get(pageNumber)
    if (!canvas) throw new Error(`PDF 第 ${pageNumber} 页 canvas 尚未挂载`)

    const viewport = page.getViewport({scale: renderScale})
    const deviceScale = window.devicePixelRatio || 1
    canvas.width = Math.floor(viewport.width * deviceScale)
    canvas.height = Math.floor(viewport.height * deviceScale)
    canvas.style.width = `${viewport.width}px`
    canvas.style.height = `${viewport.height}px`
    const context = canvas.getContext('2d')
    if (!context) throw new Error(`PDF 第 ${pageNumber} 页无法获取 canvas 2D context`)

    const renderTask = page.render({
      canvasContext: context,
      viewport,
      transform: deviceScale === 1 ? undefined : [deviceScale, 0, 0, deviceScale, 0, 0],
    })
    activePdfRenderTasks.add(renderTask)
    try {
      await renderTask.promise
    } catch (error) {
      if (renderGeneration !== pdfRenderGeneration || !isPreviewCurrent(requestId, projectId, fileId)) return
      throw error
    } finally {
      activePdfRenderTasks.delete(renderTask)
    }
  }
}

async function loadPdfPreview(file: FileMetadata, projectId: string, requestId: number) {
  const blob = await getFileContent(projectId, file.file_id)
  if (!isPreviewCurrent(requestId, projectId, file.file_id)) return
  const loadingTask = pdfjsLib.getDocument({data: await blob.arrayBuffer()})
  activePdfLoadingTask = loadingTask
  const pdfDocument = await loadingTask.promise
  if (activePdfLoadingTask === loadingTask) activePdfLoadingTask = null
  if (!isPreviewCurrent(requestId, projectId, file.file_id)) {
    void pdfDocument.destroy()
    return
  }
  activePdfDocument = pdfDocument
  await renderPdfPages(pdfDocument, requestId, projectId, file.file_id)
}

function clampPdfZoom(scale: number): number {
  if (!Number.isFinite(scale)) return pdfZoom.value
  return Math.min(3, Math.max(0.5, Math.round(scale * 100) / 100))
}

function goToPdfPage(pageNumber: number, behavior: ScrollBehavior = 'smooth'): boolean {
  if (!Number.isInteger(pageNumber) || pageNumber < 1 || pageNumber > pdfPages.value.length) {
    pdfPageInput.value = String(currentPdfPage.value)
    return false
  }
  const container = documentScrollContainer.value
  const target = container?.querySelector<HTMLElement>(`[data-pdf-page="${pageNumber}"]`)
  if (!container || !target) {
    pdfPageInput.value = String(currentPdfPage.value)
    return false
  }
  setCurrentPdfPage(pageNumber)
  container.scrollTo({top: Math.max(0, target.offsetTop - 12), behavior})
  return true
}

function handlePdfPageJump() {
  const value = pdfPageInput.value.trim()
  if (!/^\d+$/.test(value) || !goToPdfPage(Number(value))) {
    pdfPageInput.value = String(currentPdfPage.value)
  }
}

function handlePdfScroll() {
  if (pdfScrollFrame !== null) return
  pdfScrollFrame = requestAnimationFrame(() => {
    pdfScrollFrame = null
    const container = documentScrollContainer.value
    if (!container) return
    const containerRect = container.getBoundingClientRect()
    let visiblePage = currentPdfPage.value
    let greatestVisibleArea = -1
    for (const element of container.querySelectorAll<HTMLElement>('[data-pdf-page]')) {
      const rect = element.getBoundingClientRect()
      const visibleHeight = Math.max(0, Math.min(rect.bottom, containerRect.bottom) - Math.max(rect.top, containerRect.top))
      if (visibleHeight > greatestVisibleArea) {
        const pageNumber = Number(element.dataset.pdfPage)
        if (Number.isInteger(pageNumber)) visiblePage = pageNumber
        greatestVisibleArea = visibleHeight
      }
    }
    if (visiblePage !== currentPdfPage.value) setCurrentPdfPage(visiblePage)
  })
}

async function applyPdfZoom(scale: number) {
  const pdfDocument = activePdfDocument
  const projectId = currentProjectId.value
  const file = selectedFileDetail.value
  if (!pdfDocument || !projectId || !file || documentPreviewLoading.value || documentPreviewError.value) return

  const requestId = previewRequestId
  const pageToKeep = currentPdfPage.value
  pdfZoom.value = clampPdfZoom(scale)
  documentPreviewLoading.value = true
  try {
    await renderPdfPages(pdfDocument, requestId, projectId, file.file_id)
    if (!isPreviewCurrent(requestId, projectId, file.file_id)) return
    await nextTick()
    goToPdfPage(pageToKeep, 'auto')
  } catch {
    if (isPreviewCurrent(requestId, projectId, file.file_id)) {
      documentPreviewError.value = '文档预览加载失败，请稍后重试。'
    }
  } finally {
    if (isPreviewCurrent(requestId, projectId, file.file_id)) documentPreviewLoading.value = false
  }
}

function zoomOut() {
  const nextScale = [...PDF_ZOOM_LEVELS].reverse().find((level) => level < pdfZoom.value - 0.001)
  if (nextScale !== undefined) void applyPdfZoom(nextScale)
}

function zoomIn() {
  const nextScale = PDF_ZOOM_LEVELS.find((level) => level > pdfZoom.value + 0.001)
  if (nextScale !== undefined) void applyPdfZoom(nextScale)
}

function handlePdfZoomSelect(event: Event) {
  const value = Number((event.target as HTMLSelectElement).value)
  if (Number.isFinite(value)) void applyPdfZoom(value)
}

async function fitPdfTo(mode: 'width' | 'page') {
  const pdfDocument = activePdfDocument
  const container = documentScrollContainer.value
  const projectId = currentProjectId.value
  const file = selectedFileDetail.value
  if (!pdfDocument || !container || !projectId || !file || pdfControlsDisabled.value) return

  const requestId = previewRequestId
  try {
    const page = await pdfDocument.getPage(currentPdfPage.value)
    if (!isPreviewCurrent(requestId, projectId, file.file_id)) return
    const viewport = page.getViewport({scale: 1})
    const styles = getComputedStyle(container)
    const horizontalPadding = Number.parseFloat(styles.paddingLeft) + Number.parseFloat(styles.paddingRight)
    const verticalPadding = Number.parseFloat(styles.paddingTop) + Number.parseFloat(styles.paddingBottom)
    const widthScale = Math.max(1, container.clientWidth - horizontalPadding) / viewport.width
    const heightScale = Math.max(1, container.clientHeight - verticalPadding - 28) / viewport.height
    await applyPdfZoom(mode === 'width' ? widthScale : Math.min(widthScale, heightScale))
  } catch {
    if (isPreviewCurrent(requestId, projectId, file.file_id)) {
      documentPreviewError.value = '文档预览加载失败，请稍后重试。'
    }
  }
}

async function loadDocxPreview(file: FileMetadata, projectId: string, requestId: number) {
  const preview = await getFilePreview(projectId, file.file_id)
  if (isPreviewCurrent(requestId, projectId, file.file_id)) docxPreview.value = preview
}

async function selectFileForDetail(file: FileMetadata) {
  clearDocumentPreview()
  selectedFileDetail.value = file
  const projectId = currentProjectId.value
  if (!projectId) return

  const requestId = previewRequestId
  const fileType = file.file_type.toLowerCase()
  if (fileType !== 'pdf' && fileType !== 'docx') return
  documentPreviewLoading.value = true

  try {
    if (fileType === 'pdf') await loadPdfPreview(file, projectId, requestId)
    else await loadDocxPreview(file, projectId, requestId)
  } catch {
    if (requestId === previewRequestId) documentPreviewError.value = '文档预览加载失败，请稍后重试。'
  } finally {
    if (requestId === previewRequestId) documentPreviewLoading.value = false
  }
}

function closeFilePreview() {
  clearDocumentPreview()
  selectedFileDetail.value = null
}

function selectProject(project: Project) {
  setCurrentProject(project.project_id)
  projectSwitcherOpen.value = false
  selectedFile.value = null
  selectedFileName.value = ''
  uploadStatus.value = ''
  uploadError.value = ''
  if (activeNav.value === '资料') {
    files.value = []
    filesError.value = ''
    void loadFiles()
  }
}

function formatProjectDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

async function selectNav(item: string) {
  activeNav.value = item
  if (item === '项目') await loadProjects()
  if (item === '资料') await loadFiles()
}

function renderMarkdown(content: string) {
  const html = marked.parse(content, {
    breaks: true,
  })

  return DOMPurify.sanitize(html)
}

const navItems = ['项目', '资料', '助理', '风险', '设置']
const prompts = [
  ['总结当前项目资料', '梳理已有资料中的核心信息'],
  ['查找项目关键文件', '定位与问题相关的重要文件'],
  ['查询项目资料', '从当前项目资料中检索答案'],
  ['分析资料中的风险', '识别资料中可核验的风险线索'],
]

function selectPrompt(prompt: string) {
  input.value = prompt
}

async function submitLogin() {
  if (!identifier.value.trim() || !password.value) return
  loginBusy.value = true
  loginError.value = ''
  try { await login(identifier.value, password.value); currentUser.value = getCurrentUser(); authenticated.value = true; password.value = ''; await loadProjects() }
  catch (error) { loginError.value = error instanceof Error ? error.message : '登录失败，请稍后重试。' }
  finally { loginBusy.value = false }
}
function showRegister() {
  registering.value = true
  registerError.value = ''
  registerSuccess.value = ''
}

function showLogin() {
  registering.value = false
  registerError.value = ''
  registerPassword.value = ''
  registerPasswordConfirm.value = ''
}

async function submitRegister() {
  const username = registerUsername.value.trim()
  const email = registerEmail.value.trim()
  const password = registerPassword.value
  if (!username || !email || !password || password.length < 8) {
    registerError.value = '请填写有效信息，密码至少 8 位。'
    return
  }
  if (password !== registerPasswordConfirm.value) {
    registerError.value = '两次输入的密码不一致。'
    return
  }
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
    registerError.value = '请输入有效的邮箱地址。'
    return
  }
  registerBusy.value = true
  registerError.value = ''
  try {
    await register(username, email, password)
    registering.value = false
    identifier.value = username
    loginError.value = ''
    registerSuccess.value = '注册成功，请登录。'
    registerUsername.value = ''
    registerEmail.value = ''
    registerPassword.value = ''
    registerPasswordConfirm.value = ''
  } catch (error) {
    registerError.value = error instanceof Error ? error.message : '注册失败，请稍后重试。'
  } finally {
    registerBusy.value = false
  }
}
function logout() { saveCurrentConversationSnapshot(); clearDocumentPreview(); clearAuth(); currentUser.value = null; authenticated.value = false }

function clearSelectedFile() {
  selectedFile.value = null
  selectedFileName.value = ''
}

async function uploadSelectedFile() {
  const file = selectedFile.value
  if (!file || uploadBusy.value) return

  const uploadProjectId = currentProjectId.value
  if (!uploadProjectId) {
    uploadStatus.value = ''
    uploadError.value = '请先选择一个项目。'
    return
  }

  uploadBusy.value = true
  uploadError.value = ''
  uploadStatus.value = '正在上传并入库...'

  try {
    const data = await uploadFile(uploadProjectId, file)
    clearSelectedFile()

    if (currentProjectId.value !== uploadProjectId) return

    uploadStatus.value = data.ingestion.status === 'completed'
      ? `已上传并入库：${data.ingestion.chunk_count} 个文本块，${data.ingestion.vector_count} 个向量`
      : '文件已上传'
    if (activeNav.value === '资料') void loadFiles()
  } catch (error) {
    if (currentProjectId.value === uploadProjectId) {
      uploadStatus.value = ''
      uploadError.value = error instanceof Error ? error.message : '文件上传失败，请稍后重试。'
      if (activeNav.value === '资料') void loadFiles()
    }
  } finally {
    uploadBusy.value = false
  }
}

async function reingestSelectedFile(file: FileMetadata) {
  const projectId = currentProjectId.value
  if (!projectId || isReingesting(file.file_id)) return
  if (file.project_id && file.project_id !== projectId) return

  reingestingFileIds.value = new Set(reingestingFileIds.value).add(file.file_id)
  updateFile(file.file_id, (current) => ({
    ...current,
    ingestion_status: 'processing',
    ingestion_error: null,
    chunk_count: null,
    vector_count: null,
  }))

  try {
    await reingestFile(projectId, file.file_id)
    if (currentProjectId.value === projectId && activeNav.value === '资料') {
      await loadFiles()
    }
  } catch (error) {
    if (currentProjectId.value === projectId) {
      updateFile(file.file_id, (current) => ({
        ...current,
        ingestion_status: 'failed',
        ingestion_error: {
          stage: current.ingestion_error?.stage ?? 'reingest',
          message: error instanceof Error ? error.message : '文件重新入库失败，请稍后重试。',
        },
      }))
    }
  } finally {
    reingestingFileIds.value = new Set(
      [...reingestingFileIds.value].filter((fileId) => fileId !== file.file_id),
    )
  }
}

async function sendMessage() {
  const message = input.value.trim()
  if (!message || loading.value) return
  if (uploadBusy.value) {
    requestError.value = '资料正在上传并入库，请完成后再发送问题。'
    return
  }

  const projectId = currentProjectId.value
  if (!projectId) {
    requestError.value = '请先选择一个项目。'
    return
  }
  const requestConversationId = conversationId.value

  messages.value.push(message)
  const messageIndex = messages.value.length - 1
  assistantResponses.value.push(null)
  input.value = ''
  requestError.value = ''
  loading.value = true
  const localConversation = conversations.value.find((item) => item.conversation_id === requestConversationId)
  if (localConversation) {
    if (localConversation.title === '新对话') localConversation.title = message.slice(0, 24)
    localConversation.updated_at = new Date().toISOString()
  }
  saveCurrentConversationSnapshot()

  try {
    const response = await requestAssistant(
      message,
      projectId,
      requestConversationId,
    )
    if (
      currentProjectId.value === projectId
      && conversationId.value === requestConversationId
    ) {
      assistantResponses.value[messageIndex] = response
      saveCurrentConversationSnapshot()
    }
  } catch (error) {
    if (
      currentProjectId.value === projectId
      && conversationId.value === requestConversationId
    ) {
      requestError.value =
          error instanceof Error ? error.message : '对话请求失败，请稍后重试。'
      saveCurrentConversationSnapshot()
    }
  } finally {
    loading.value = false
  }
}

function chooseFile(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0] ?? null

  if (uploadBusy.value) {
    target.value = ''
    return
  }

  selectedFile.value = file
  selectedFileName.value = file?.name ?? ''
  uploadStatus.value = ''
  uploadError.value = ''
  if (file) {
    void uploadSelectedFile()
  }

  // 允许再次选择同一个文件
  target.value = ''
}

async function createProject() {
  const name = projectName.value.trim()
  if (!name) return
  projectCreateError.value = ''
  try {
    const project = await createProjectApi(name)
    projects.value.push(project)
    setCurrentProject(project.project_id)
    files.value = []
    filesError.value = ''
    selectedFile.value = null
    selectedFileName.value = ''
    uploadStatus.value = ''
    uploadError.value = ''
    projectName.value = ''
    showCreateProject.value = false
    if (activeNav.value === '资料') void loadFiles()
  } catch {
    projectCreateError.value = '项目创建失败，请稍后重试'
  }
}

onMounted(async () => {
  const onExpired = () => { clearDocumentPreview(); authenticated.value = false; currentUser.value = null; projects.value = []; currentProjectId.value = null; loginError.value = '登录已失效，请重新登录。' }
  window.addEventListener('northstar-auth-expired', onExpired)
  window.addEventListener('keydown', handleGlobalKeydown)
  window.addEventListener('resize', handleViewportResize)
  applyTheme(themePreference.value)
  if (authenticated.value) await loadProjects()
  try {
    const response = await authenticatedFetch(`${API_BASE_URL}/api/health`)
    connected.value =
        response.ok && (await response.json()).status === 'ok'
  } catch {
    connected.value = false
  }
})

onBeforeUnmount(() => {
  saveCurrentConversationSnapshot()
  clearDocumentPreview()
  window.removeEventListener('keydown', handleGlobalKeydown)
  window.removeEventListener('resize', handleViewportResize)
})
</script>

<template>
  <div v-if="!authenticated" class="auth-shell">
    <form v-if="!registering" class="auth-card" @submit.prevent="submitLogin">
      <div class="brand"><svg class="northstar-mark" viewBox="0 0 48 48" aria-hidden="true"><path d="M24 2l4.4 17.6L46 24l-17.6 4.4L24 46l-4.4-17.6L2 24l17.6-4.4L24 2Z"/><circle cx="24" cy="24" r="3"/></svg><div><strong>Northstar</strong><small>工程项目助理</small></div></div>
      <h1>登录 Northstar</h1><p>使用用户名或邮箱登录以进入项目工作台。</p>
      <label for="identifier">用户名或邮箱</label><input id="identifier" v-model="identifier" autocomplete="username" required />
      <label for="password">密码</label><input id="password" v-model="password" type="password" autocomplete="current-password" required />
      <p v-if="loginError" class="request-error">{{ loginError }}</p>
      <p v-if="registerSuccess" class="auth-success">{{ registerSuccess }}</p>
      <button type="submit" :disabled="loginBusy">{{ loginBusy ? '登录中…' : '登录' }}</button>
      <button type="button" class="auth-link" @click="showRegister">还没有账号？立即注册</button>
    </form>
    <form v-else class="auth-card" @submit.prevent="submitRegister">
      <div class="brand"><svg class="northstar-mark" viewBox="0 0 48 48" aria-hidden="true"><path d="M24 2l4.4 17.6L46 24l-17.6 4.4L24 46l-4.4-17.6L2 24l17.6-4.4L24 2Z"/><circle cx="24" cy="24" r="3"/></svg><div><strong>Northstar</strong><small>工程项目助理</small></div></div>
      <h1>注册 Northstar</h1><p>创建账号后即可登录项目工作台。</p>
      <label for="register-username">用户名</label>
      <input id="register-username" v-model="registerUsername" autocomplete="username" required />
      <label for="register-email">邮箱</label>
      <input id="register-email" v-model="registerEmail" type="email" autocomplete="email" required />
      <label for="register-password">密码</label>
      <input id="register-password" v-model="registerPassword" type="password" autocomplete="new-password" minlength="8" required />
      <label for="register-password-confirm">确认密码</label>
      <input id="register-password-confirm" v-model="registerPasswordConfirm" type="password" autocomplete="new-password" minlength="8" required />
      <p v-if="registerError" class="request-error">{{ registerError }}</p>
      <button type="submit" :disabled="registerBusy">{{ registerBusy ? '注册中…' : '注册' }}</button>
      <button type="button" class="auth-link" @click="showLogin">已有账号？返回登录</button>
    </form>
  </div>  <div v-else class="app-shell" :class="{ 'sidebar-collapsed': sidebarEffectivelyCollapsed }">
    <aside class="sidebar" :aria-label="sidebarEffectivelyCollapsed ? '已折叠的主导航' : '主导航'">
      <div class="star-layer star-layer-one"/><div class="star-layer star-layer-two"/>
      <div class="brand">
        <svg class="northstar-mark" viewBox="0 0 48 48" aria-hidden="true"><path d="M24 2l4.4 17.6L46 24l-17.6 4.4L24 46l-4.4-17.6L2 24l17.6-4.4L24 2Z"/><circle cx="24" cy="24" r="3"/></svg>
        <div class="brand-copy">
          <strong>Northstar</strong>
          <small>工程项目助理</small>
        </div>
        <button
            type="button"
            class="sidebar-toggle"
            :aria-label="sidebarEffectivelyCollapsed ? '展开侧边栏' : '折叠侧边栏'"
            :title="viewportWidth <= 768 ? '窄屏下侧边栏保持折叠' : (sidebarEffectivelyCollapsed ? '展开侧边栏' : '折叠侧边栏')"
            :disabled="viewportWidth <= 768"
            @click="toggleSidebar"
        >{{ sidebarEffectivelyCollapsed ? '»' : '«' }}</button>
      </div>

      <nav>
        <span class="nav-label">工作台</span>

        <a
            v-for="(item, index) in navItems"
            :key="item"
            class="nav-item"
            :class="{ active: activeNav === item, 'is-unavailable': item === '风险' || item === '设置' }"
            href=" "
            :aria-label="item"
            :title="sidebarEffectivelyCollapsed ? item : undefined"
            @click.prevent="selectNav(item)"
        >
          <span class="nav-icon" aria-hidden="true">{{ ['▦', '▤', '✦', '△', '⚙'][index] }}</span>
          <span>{{ item }}</span>
          <b v-if="item === '风险' || item === '设置'" class="nav-soon">即将开放</b>
        </a>
      </nav>

      <div class="sidebar-footer">
        <button
            class="new-project"
            type="button"
            aria-label="新建项目"
            :title="sidebarEffectivelyCollapsed ? '新建项目' : undefined"
            @click="showCreateProject = true"
        >
          <span aria-hidden="true">＋</span><span class="new-project-label">新建项目</span>
        </button>

        <small class="help">Northstar 工程项目 AI 工作台</small>

        <button type="button" class="user" aria-label="打开当前用户菜单" :title="sidebarEffectivelyCollapsed ? '当前用户' : undefined" @click="toggleHeaderPanel('user')">
          <span>用</span>
          <div>
            <strong>当前用户</strong>
          </div>
          <i/>
        </button>
      </div>
    </aside>

    <main class="main-content">
      <header class="topbar">
        <div class="page-heading">
          <span class="page-eyebrow">Northstar 工作台</span>
          <strong>{{ activeNav === '助理' ? 'AI 助理' : activeNav }}</strong>
        </div>

        <div class="header-search-zone">
          <button type="button" class="header-search-trigger" @click="openSearch">
            <span aria-hidden="true">⌕</span>
            <span>搜索项目与资料</span>
            <kbd>Ctrl K</kbd>
          </button>
        </div>

        <div class="top-actions">
          <button
              v-if="!contextPanelOpen && viewportWidth >= 768"
              type="button"
              class="context-restore-button"
              @click="restoreContextPanel"
          >＋ {{ panelTitle }}</button>
          <button type="button" class="header-icon-button" aria-label="通知" title="通知" @click="toggleHeaderPanel('notification')">♢</button>
          <button type="button" class="header-icon-button appearance-button" aria-label="外观" title="外观" @click="toggleHeaderPanel('theme')">◐</button>
          <button type="button" class="header-user-button" aria-label="当前用户" @click="toggleHeaderPanel('user')">
            <span>用</span>
          </button>

          <div v-if="notificationOpen" class="header-popover notification-popover">
            <div class="popover-heading"><strong>通知</strong><button type="button" aria-label="关闭通知" @click="notificationOpen = false">×</button></div>
            <div class="popover-empty">暂无通知</div>
          </div>

          <div v-if="themeMenuOpen" class="header-popover theme-popover">
            <div class="popover-heading"><strong>外观</strong><button type="button" aria-label="关闭外观菜单" @click="themeMenuOpen = false">×</button></div>
            <button type="button" :class="{ selected: themePreference === 'light' }" @click="applyTheme('light')">浅色</button>
            <button type="button" :class="{ selected: themePreference === 'dark' }" @click="applyTheme('dark')">深色</button>
            <button type="button" :class="{ selected: themePreference === 'system' }" @click="applyTheme('system')">跟随系统</button>
          </div>

          <div v-if="userMenuOpen" class="header-popover user-popover">
            <div class="popover-heading"><strong>当前用户</strong><button type="button" aria-label="关闭用户菜单" @click="userMenuOpen = false">×</button></div>
            <button type="button" disabled>个人资料 <small>即将开放</small></button>
            <button type="button" disabled>设置 <small>即将开放</small></button>
            <button type="button" @click="toggleHeaderPanel('theme')">外观</button>
            <button type="button" class="user-logout" @click="logout">退出登录</button>
          </div>
        </div>
      </header>

      <div v-if="searchOpen" class="search-backdrop" @click.self="searchOpen = false">
        <section class="search-panel" role="dialog" aria-modal="true" aria-label="全局搜索">
          <div class="search-input-wrap">
            <span aria-hidden="true">⌕</span>
            <input ref="searchInput" v-model="searchQuery" placeholder="输入项目名称或资料名称进行搜索" />
            <kbd>Esc</kbd>
          </div>
          <div class="search-empty">
            <strong>{{ searchQuery ? '全局搜索功能即将开放' : '搜索项目与资料' }}</strong>
            <p>当前阶段不生成模拟搜索结果。</p>
          </div>
        </section>
      </div>

      <div v-if="true" class="workspace dynamic-workspace" :style="workspaceGridStyle">
        <section v-if="activeNav === '助理'" class="workbench-pane conversation" aria-label="AI Assistant 主工作区">
          <div class="conversation-scroll">
            <div class="conversation-inner">
              <div class="welcome" :class="{ compact: messages.length }">
                <div>
                  <span class="eyebrow">基于当前项目资料</span>
                  <h1>项目 AI 助理</h1>
                  <p>基于当前项目资料回答问题，并提供可核验的文件、版本和页码依据。</p>
                </div>
              </div>

              <template v-if="!messages.length">
                <div class="start-heading">快捷操作 <span/></div>
                <div class="prompt-grid">
                  <button v-for="(prompt, index) in prompts" :key="prompt[0]" type="button" class="prompt-card" @click="selectPrompt(prompt[0])">
                    <b>0{{ index + 1 }}</b>
                    <span><strong>{{ prompt[0] }}</strong><small>{{ prompt[1] }}</small></span>
                    <em>↗</em>
                  </button>
                </div>
              </template>

              <div v-if="messages.length || loading || requestError" class="messages">
                <template v-for="(message, index) in messages" :key="`${message}-${index}`">
                  <div class="message user-message"><strong>你</strong><span>{{ message }}</span></div>
                  <div v-if="assistantResponses[index]" class="message assistant-message">
                    <strong>Northstar</strong>
                    <div v-if="assistantResponses[index]?.status === 'no_evidence'" class="assistant-status">未找到足够项目资料，无法确认。</div>
                    <div class="markdown-body" v-html="renderMarkdown(assistantResponses[index]?.reply ?? '')" />
                    <div v-if="assistantResponses[index]?.citations.length" class="assistant-citations">
                      <span class="citation-heading">回答依据</span>
                      <ul>
                        <li v-for="(citation, citationIndex) in assistantResponses[index]?.citations" :key="`${citation.original_filename}-${citation.document_version}-${citation.page_number}-${citationIndex}`">
                          <span class="citation-icon">▤</span>
                          <span class="citation-copy"><strong>{{ citation.original_filename }}</strong><small>{{ [citation.document_version ? `V${citation.document_version}` : '', citation.page_number ? `第 ${citation.page_number} 页` : ''].filter(Boolean).join(' · ') }}</small></span>
                        </li>
                      </ul>
                    </div>
                  </div>
                </template>
                <div v-if="loading" class="message assistant-message"><strong>Northstar</strong><span class="loading-copy"><i/> 正在检索当前项目资料并组织回答…</span></div>
                <p v-if="requestError" class="request-error">{{ requestError }}</p>
              </div>

              <div class="connection"><i :class="{ online: connected }"/>{{ connected ? '服务已连接' : '服务未连接' }}</div>
            </div>
          </div>

          <div class="composer-wrap">
            <div class="composer">
              <div>
                <label class="clip" for="file-upload" title="上传项目资料">＋ 资料</label>
                <textarea v-model="input" rows="1" :disabled="loading || uploadBusy" placeholder="输入问题；Shift + Enter 换行" @keydown="handleComposerKeydown" />
                <button type="button" :disabled="!input.trim() || loading || uploadBusy" @click="sendMessage">{{ loading ? '…' : '↑' }}</button>
              </div>
              <small>Enter 发送 · Shift + Enter 换行 · 回答基于当前项目资料</small>
              <small v-if="selectedFileName" class="selected-file">已选择：{{ selectedFileName }}</small>
              <small v-if="uploadStatus" class="selected-file">{{ uploadStatus }}</small>
              <p v-if="uploadError" class="request-error">{{ uploadError }}</p>
            </div>
          </div>
        </section>

        <section v-else-if="activeNav === '项目'" class="workbench-pane module-pane">
          <div class="module-scroll"><div class="module-page">
            <div class="module-heading"><div><span class="eyebrow">当前主工作区</span><h1>项目详情</h1><p>查看当前选中项目的真实信息。</p></div><span v-if="currentProject" class="project-status">{{ currentProject.status }}</span></div>
            <div v-if="projectLoading" class="module-empty">项目加载中…</div>
            <div v-else-if="projectLoadError" class="module-empty"><p class="request-error">{{ projectLoadError }}</p><button type="button" @click="loadProjects">重新加载</button></div>
            <article v-else-if="currentProject" class="detail-card">
              <div class="detail-title"><span>▦</span><div><small>项目名称</small><h2>{{ currentProject.name }}</h2></div></div>
              <dl class="detail-grid"><div><dt>项目 ID</dt><dd>{{ currentProject.project_id }}</dd></div><div><dt>状态</dt><dd>{{ currentProject.status }}</dd></div><div><dt>创建时间</dt><dd>{{ formatProjectDate(currentProject.created_at) }}</dd></div><div><dt>更新时间</dt><dd>{{ formatProjectDate(currentProject.updated_at) }}</dd></div></dl>
              <div class="coming-note"><b>✎</b><div><strong>项目编辑</strong><p>当前后端未提供对应的更新接口，编辑功能即将开放。</p></div></div>
            </article>
            <div v-else class="module-empty"><span>▦</span><h2>暂无项目</h2><p>新建项目后，可在这里查看项目详情。</p><button type="button" class="primary-action" @click="showCreateProject = true">＋ 新建项目</button></div>
          </div></div>
        </section>

        <section v-else-if="activeNav === '资料'" class="workbench-pane module-pane document-content-pane">
          <template v-if="selectedFileDetail">
            <header class="document-reader-header">
              <div><h1>{{ selectedFileDetail.original_filename }}</h1><p>{{ selectedFileDetail.document_version === null ? '版本未知' : `V${selectedFileDetail.document_version}` }} · {{ selectedFileDetail.is_current ? '当前版本' : '历史版本' }}</p></div>
              <button type="button" aria-label="关闭当前文档" title="关闭当前文档" @click="closeFilePreview">×</button>
            </header>
            <div v-if="selectedFileDetail.file_type.toLowerCase() === 'pdf'" class="pdf-toolbar" role="toolbar" aria-label="PDF 阅读控制">
              <div class="pdf-toolbar-group">
                <button type="button" title="缩小" aria-label="缩小" :disabled="!canZoomOut" @click="zoomOut">−</button>
                <select :value="pdfZoom" aria-label="当前缩放比例" :disabled="pdfControlsDisabled" @change="handlePdfZoomSelect">
                  <option v-if="!pdfZoomIsPreset" :value="pdfZoom">{{ pdfZoomPercent }}%</option>
                  <option v-for="level in PDF_ZOOM_LEVELS" :key="level" :value="level">{{ Math.round(level * 100) }}%</option>
                </select>
                <button type="button" title="放大" aria-label="放大" :disabled="!canZoomIn" @click="zoomIn">＋</button>
              </div>
              <div class="pdf-toolbar-group pdf-fit-controls">
                <button type="button" :disabled="pdfControlsDisabled" @click="fitPdfTo('width')">适应宽度</button>
                <button type="button" :disabled="pdfControlsDisabled" @click="fitPdfTo('page')">适应页面</button>
              </div>
              <label class="pdf-page-control">
                <span>第</span>
                <input v-model="pdfPageInput" type="text" inputmode="numeric" aria-label="跳转到页码" :disabled="pdfControlsDisabled" @keydown.enter.prevent="handlePdfPageJump" @blur="pdfPageInput = String(currentPdfPage)" />
                <span>/ {{ pdfPages.length || '—' }} 页</span>
              </label>
            </div>
            <div class="document-reader-body">
              <div v-if="documentPreviewError" class="document-reader-state"><strong>{{ documentPreviewError }}</strong><button type="button" @click="selectFileForDetail(selectedFileDetail)">重新加载</button></div>
              <div v-else-if="selectedFileDetail.file_type.toLowerCase() === 'pdf' && pdfPages.length" ref="documentScrollContainer" class="document-scroll-container pdf-preview-content" @scroll.passive="handlePdfScroll">
                <div v-if="documentPreviewLoading" class="document-preview-loading"><span class="pdf-loader"/><strong>正在加载文档预览…</strong></div>
                <article v-for="page in pdfPages" :key="page.pageNumber" class="pdf-page" :data-pdf-page="page.pageNumber" :aria-current="page.pageNumber === currentPdfPage ? 'page' : undefined">
                  <div class="pdf-page-label">第 {{ page.pageNumber }} 页</div>
                  <canvas :ref="(element) => setPdfCanvasRef(element, page.pageNumber)" class="pdf-page-canvas" />
                </article>
              </div>
              <div v-else-if="documentPreviewLoading" class="document-reader-state"><span class="pdf-loader"/><strong>正在加载文档预览…</strong></div>
              <div v-else-if="selectedFileDetail.file_type.toLowerCase() === 'docx' && docxPreview" ref="documentScrollContainer" class="document-scroll-container docx-preview-content">
                <template v-for="(block, blockIndex) in docxPreview.blocks" :key="`${block.type}-${blockIndex}`">
                  <component v-if="block.type === 'heading'" :is="`h${Math.min(6, Math.max(1, block.level))}`" class="docx-heading">{{ block.text }}</component>
                  <p v-else-if="block.type === 'paragraph'" class="docx-paragraph">{{ block.text }}</p>
                  <ul v-else-if="block.type === 'list'" class="docx-list"><li v-for="(item, itemIndex) in block.items" :key="itemIndex">{{ item }}</li></ul>
                  <div v-else-if="block.type === 'table'" class="docx-table-wrap"><table class="docx-table"><tbody><tr v-for="(row, rowIndex) in block.rows" :key="rowIndex"><td v-for="(cell, cellIndex) in row" :key="cellIndex">{{ cell }}</td></tr></tbody></table></div>
                  <p v-else-if="block.type === 'image'" class="docx-image-notice">文档包含图片，当前预览暂不显示图片。</p>
                </template>
              </div>
              <div v-else-if="selectedFileDetail.file_type.toLowerCase() === 'pdf'" class="document-reader-state"><strong>文档没有可预览页面。</strong></div>
              <div v-else-if="selectedFileDetail.file_type.toLowerCase() === 'docx'" class="document-reader-state"><strong>文档没有可预览内容。</strong></div>
              <div v-else class="document-reader-state unsupported-document"><span>▤</span><h2>当前暂不支持在线预览该文件类型。</h2><p>文件已保留在当前项目资料中。</p></div>
            </div>
          </template>
          <div v-else class="document-empty-state"><span>▤</span><h2>选择一个项目资料</h2><p>从右侧项目资料列表中选择文件查看内容</p></div>
        </section>

        <section v-else-if="activeNav === '风险'" class="workbench-pane module-pane coming-page"><span>△</span><small>风险详情</small><h1>风险中心即将开放</h1><p>当前没有可用的风险业务 API，因此不会生成模拟风险数据。</p></section>
        <section v-else class="workbench-pane module-pane coming-page"><span>⚙</span><small>{{ selectedSetting }}</small><h1>{{ selectedSetting }}设置即将开放</h1><p>当前没有对应的后端设置能力，不会显示虚假的保存结果。</p></section>

        <button
            v-if="contextPanelVisible"
            type="button"
            class="pane-resizer"
            :aria-label="`调整主工作区与${panelTitle}的宽度`"
            @pointerdown="startContextResize"
        />

        <aside v-if="contextPanelVisible" class="workbench-pane project-panel dynamic-panel">
          <div class="pane-header">
            <div><span>{{ activeNav }}</span><strong>{{ panelTitle }}</strong></div>
            <button type="button" :aria-label="`关闭${panelTitle}`" @click="closeContextPanel">×</button>
          </div>
          <template v-if="activeNav === '项目'">
            <div class="pane-scroll resource-scroll"><div v-if="projectLoading" class="panel-empty">项目加载中…</div><div v-else-if="projectLoadError" class="panel-empty"><p>{{ projectLoadError }}</p><button type="button" @click="loadProjects">重新加载</button></div><div v-else-if="!projects.length" class="panel-empty">暂无项目</div><div v-else class="resource-list"><button v-for="project in projects" :key="project.project_id" type="button" class="resource-item" :class="{ selected: project.project_id === currentProjectId }" @click="selectProject(project)"><span class="resource-symbol">▦</span><span><strong>{{ project.name }}</strong><small>{{ project.status }} · {{ formatProjectDate(project.updated_at) }}</small></span><i v-if="project.project_id === currentProjectId">✓</i></button></div></div>
            <div class="panel-footer"><button type="button" @click="showCreateProject = true">＋ 新建项目</button></div>
          </template>

          <template v-else-if="activeNav === '资料'">
            <div class="panel-subhead"><strong>{{ currentProject?.name ?? '未选择项目' }}</strong><small>{{ files.length }} 份资料</small></div>
            <div class="pane-scroll resource-scroll"><div v-if="filesLoading" class="panel-empty">资料加载中…</div><div v-else-if="filesError" class="panel-empty"><p>{{ filesError }}</p><button type="button" @click="loadFiles">重新加载</button></div><div v-else-if="!files.length" class="panel-empty"><span>▤</span><p>暂无项目资料</p><small>上传 PDF 或 DOCX 后将显示在这里。</small></div><div v-else class="resource-list"><button v-for="file in files" :key="file.file_id" type="button" class="resource-item file-resource-item" :class="{ selected: selectedFileDetail?.file_id === file.file_id }" @click="selectFileForDetail(file)"><span class="resource-symbol file-symbol">{{ file.file_type === 'pdf' ? 'PDF' : 'DOC' }}</span><span><strong>{{ file.original_filename }}</strong><small>{{ file.document_version === null ? '版本未知' : `V${file.document_version}` }} · {{ file.is_current ? '当前版本' : '历史版本' }}</small><em><b :class="`ingestion-${file.ingestion_status ?? 'unknown'}`"/>{{ ingestionStatusLabel(file) }} · {{ formatUploadTime(file.ingestion_completed_at ?? file.uploaded_at) }}</em></span></button></div></div>
            <div class="panel-footer"><label for="file-upload" :class="{ disabled: uploadBusy || !currentProjectId }">{{ uploadBusy ? '正在上传并入库…' : '＋ 上传项目资料' }}</label></div>
          </template>

          <template v-else-if="activeNav === '助理'">
            <div class="panel-subhead"><strong>{{ projectTitle }}</strong><small>对话仅保存在当前浏览器</small></div>
            <div class="pane-scroll resource-scroll"><div v-if="!currentProjectId" class="panel-empty">请先选择项目</div><div v-else-if="!projectConversations.length" class="panel-empty">暂无对话</div><div v-else class="conversation-list"><div v-for="conversationItem in projectConversations" :key="conversationItem.conversation_id" class="conversation-entry" :class="{ selected: conversationItem.conversation_id === conversationId }"><button type="button" class="conversation-open" @click="openConversation(conversationItem)"><span>◌</span><span v-if="editingConversationId !== conversationItem.conversation_id"><strong>{{ conversationItem.title }}</strong><small>{{ conversationItem.messages.length }} 条提问 · {{ formatProjectDate(conversationItem.updated_at) }}</small></span></button><input v-if="editingConversationId === conversationItem.conversation_id" v-model="editingConversationTitle" class="rename-input" maxlength="80" autofocus @keydown.enter.prevent="commitConversationRename(conversationItem)" @keydown.esc="editingConversationId = null" @blur="commitConversationRename(conversationItem)"/><div v-else class="conversation-actions"><button type="button" :class="{ active: conversationItem.pinned }" :title="conversationItem.pinned ? '取消置顶' : '置顶'" @click="toggleConversationPinned(conversationItem)">⌃</button><button type="button" title="重命名" @click="beginRenameConversation(conversationItem)">✎</button><button type="button" title="仅删除前端对话入口" @click="deleteConversation(conversationItem)">×</button></div></div></div></div>
            <div class="panel-footer"><button type="button" :disabled="!currentProjectId || loading" @click="newConversation">＋ 新建对话</button></div>
          </template>

          <div v-else-if="activeNav === '风险'" class="pane-scroll resource-scroll"><div class="panel-empty"><span>△</span><p>风险中心即将开放</p><small>暂无真实风险数据。</small></div></div>
          <div v-else class="pane-scroll resource-scroll"><div class="setting-list"><button v-for="category in ['账号', '外观', '通知', '系统']" :key="category" type="button" :class="{ selected: selectedSetting === category }" @click="selectedSetting = category"><span>{{ category === '账号' ? '◎' : category === '外观' ? '◐' : category === '通知' ? '♢' : '⚙' }}</span><strong>{{ category }}</strong><small>即将开放</small></button></div></div>
        </aside>
      </div>

      <section v-else-if="activeNav === '项目'" class="projects-page">
        <div class="projects-header">
          <div>
            <span class="panel-label">Northstar 工作台</span>
            <h1>项目</h1>
            <p>查看和切换你有权限访问的项目。</p>
          </div>
          <button type="button" class="primary-action" @click="showCreateProject = true">
            ＋ 新建项目
          </button>
        </div>

        <div v-if="projectLoading" class="project-page-state">
          项目加载中...
        </div>

        <div v-else-if="projectLoadError" class="project-page-state project-page-error">
          <p>{{ projectLoadError }}</p>
          <button type="button" @click="loadProjects">重新加载</button>
        </div>

        <div v-else-if="!projects.length" class="project-page-state">
          <p>暂无项目</p>
          <button type="button" class="primary-action" @click="showCreateProject = true">
            ＋ 新建项目
          </button>
        </div>

        <div v-else class="project-list">
          <button
              v-for="project in projects"
              :key="project.project_id"
              type="button"
              class="project-card"
              :class="{ current: project.project_id === currentProjectId }"
              @click="selectProject(project)"
          >
            <div class="project-card-heading">
              <div>
                <h2>{{ project.name }}</h2>
                <small>ID：{{ project.project_id }}</small>
              </div>
              <span class="project-status-badge">{{ project.status }}</span>
            </div>
            <dl>
              <div>
                <dt>项目 ID</dt>
                <dd class="project-id">{{ project.project_id }}</dd>
              </div>
              <div>
                <dt>创建时间</dt>
                <dd>{{ formatProjectDate(project.created_at) }}</dd>
              </div>
              <div>
                <dt>更新时间</dt>
                <dd>{{ formatProjectDate(project.updated_at) }}</dd>
              </div>
            </dl>
            <span v-if="project.project_id === currentProjectId" class="current-project-badge">✓ 当前项目</span>
          </button>
        </div>
      </section>

      <section v-else-if="activeNav === '资料'" class="files-page">
        <div class="files-page-header">
          <span class="panel-label">项目资料</span>
          <h1>文件列表</h1>
          <div v-if="currentProject && currentProjectId" class="files-project-context">
            <span>项目名称：{{ currentProject.name }}</span>
            <span>项目 ID：{{ currentProjectId }}</span>
          </div>
          <p v-else class="files-project-context">请先选择一个项目</p>
          <div class="files-upload">
            <label
                for="file-upload"
                class="upload-button"
                :class="{ 'upload-button-disabled': uploadBusy || !currentProjectId }"
            >
              {{ uploadBusy ? '正在上传并入库...' : '⇧ 上传 PDF / DOCX' }}
            </label>
            <small v-if="selectedFileName" class="selected-file">已选择：{{ selectedFileName }}</small>
            <small v-if="uploadStatus" class="selected-file">{{ uploadStatus }}</small>
            <p v-if="uploadError" class="request-error">
              {{ uploadError }}
            </p>
          </div>
        </div>

        <div v-if="filesLoading" class="files-page-state">
          加载中...
        </div>

        <div v-else-if="filesError" class="files-page-state files-page-error">
          <p>{{ filesError }}</p>
          <button type="button" @click="loadFiles">重新加载</button>
        </div>

        <div v-else-if="!files.length" class="files-page-state">
          <p>暂无文件</p>
          <p class="files-empty-hint">上传 PDF 或 DOCX 后，文件将显示在这里</p>
        </div>

        <div v-else class="files-table-container">
          <table class="files-table">
            <thead>
              <tr>
                <th>文件名</th>
                <th>类型</th>
                <th>大小</th>
                <th>上传时间</th>
                <th>版本</th>
                <th>入库状态</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="file in files" :key="file.file_id" class="file-row">
                <td class="file-name-cell">
                  <span class="file-icon" :data-type="file.file_type">
                    {{ file.file_type === 'pdf' ? '📄' : '📝' }}
                  </span>
                  <span class="file-name">{{ file.original_filename }}</span>
                </td>
                <td>{{ file.file_type.toUpperCase() }}</td>
                <td class="file-size">{{ formatFileSize(file.size) }}</td>
                <td class="file-time">{{ formatUploadTime(file.uploaded_at) }}</td>
                <td class="file-version">
                  <span class="version-badge">{{ file.document_version === null ? '版本未知' : `V${file.document_version}` }}</span>
                </td>
                <td class="ingestion-cell">
                  <span class="ingestion-badge" :class="`ingestion-${file.ingestion_status ?? 'unknown'}`">
                    {{ ingestionStatusLabel(file) }}
                  </span>
                  <small v-if="ingestionDetails(file)" class="ingestion-details">{{ ingestionDetails(file) }}</small>
                  <small
                      v-if="ingestionErrorMessage(file)"
                      class="ingestion-error"
                      :title="ingestionErrorMessage(file)"
                  >
                    {{ ingestionErrorMessage(file) }}
                  </small>
                </td>
                <td class="file-status">
                  <span v-if="file.is_current" class="current-badge">当前</span>
                  <span v-else class="historical-badge">历史</span>
                </td>
                <td class="file-actions">
                  <button
                      v-if="file.ingestion_status === 'failed'"
                      type="button"
                      class="reingest-button"
                      :disabled="isReingesting(file.file_id) || Boolean(file.project_id && file.project_id !== currentProjectId)"
                      @click="reingestSelectedFile(file)"
                  >
                    {{ isReingesting(file.file_id) ? '重新入库中...' : '重新入库' }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-else class="placeholder-page">
        <span class="panel-label">Northstar 工作台</span>
        <h1>{{ activeNav }}</h1>
        <p>{{ activeNav }}页面暂为占位内容。</p>
      </section>
    </main>
    <input
        id="file-upload"
        class="file-input"
        type="file"
        accept=".pdf,.docx"
        :disabled="uploadBusy || !currentProjectId"
        @change="chooseFile"
    />
  </div>

  <div
      v-if="showCreateProject"
      class="modal-backdrop"
      @click.self="showCreateProject = false"
  >
    <form class="modal" @submit.prevent="createProject">
      <h2>新建项目</h2>

      <label for="project-name">项目名称</label>

      <input
          id="project-name"
          v-model="projectName"
          autofocus
          placeholder="请输入项目名称"
      />
      <p v-if="projectCreateError" class="request-error">{{ projectCreateError }}</p>

      <div class="modal-actions">
        <button
            type="button"
            @click="showCreateProject = false"
        >
          取消
        </button>

        <button type="submit">创建</button>
      </div>
    </form>
  </div>
</template>

<style>
.sidebar {
  position: relative;
}

.project-switcher {
  width: 100%;
  cursor: pointer;
  text-align: left;
}

.project-options {
  position: absolute;
  z-index: 3;
  width: 202px;
  margin-top: 4px;
  padding: 4px;
  border: 1px solid #2a374b;
  border-radius: 7px;
  background: #182438;
  box-shadow: 0 8px 18px rgb(0 0 0 / 18%);
}

.project-options button {
  display: block;
  width: 100%;
  padding: 8px;
  border: 0;
  border-radius: 5px;
  color: #cbd4df;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.project-options button:hover,
.project-options button.selected {
  background: #26364d;
}

.project-options strong,
.project-options small {
  display: block;
}

.project-options strong {
  overflow: hidden;
  color: #edf1f5;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-options small {
  margin-top: 3px;
  color: #8997aa;
  font-size: 8px;
}

.project-empty,
.project-load-error {
  display: block;
  padding: 7px 9px;
  color: #9aa7b8;
  font-size: 9px;
}

.project-load-error button {
  margin-left: 5px;
  padding: 2px 5px;
  border: 0;
  border-radius: 3px;
  color: #dce9f7;
  background: #2f5574;
  font-size: 9px;
  cursor: pointer;
}

.auth-link {
  padding: 0 !important;
  color: #1f4d8f !important;
  background: transparent !important;
  font-size: 11px;
  cursor: pointer;
}

.auth-success {
  margin: 0;
  color: #287b63;
  font-size: 11px;
}

.assistant-status {
  margin-bottom: 8px;
  color: #e8c98d;
  font-size: 11px;
}

.assistant-citations {
  margin-top: 12px;
  padding-top: 9px;
  border-top: 1px solid #2d3d52;
  color: #9aa7b8;
  font-size: 11px;
}

.assistant-citations span {
  color: #cbd4df;
  font-weight: 600;
}

.assistant-citations ul {
  margin: 5px 0 0;
  padding-left: 18px;
}

.assistant-citations li {
  overflow-wrap: anywhere;
  line-height: 1.55;
}

.projects-page {
  min-height: 100%;
  padding: 32px 38px 48px;
  color: #e8eef5;
}

.projects-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 26px;
}

.projects-header h1 {
  margin: 6px 0 5px;
  font-size: 28px;
}

.projects-header p {
  margin: 0;
  color: #92a0b2;
  font-size: 12px;
}

.primary-action {
  padding: 9px 13px;
  border: 1px solid #4b7da7;
  border-radius: 5px;
  color: #f5f8fb;
  background: #2f5574;
  font-size: 11px;
  cursor: pointer;
}

.primary-action:hover {
  background: #3b668c;
}

.project-page-state {
  display: grid;
  place-items: center;
  min-height: 180px;
  padding: 24px;
  border: 1px dashed #35475e;
  border-radius: 7px;
  color: #9aa7b8;
  text-align: center;
  font-size: 13px;
}

.project-page-state p {
  margin: 0 0 14px;
}

.project-page-error {
  color: #f0a6a6;
}

.project-page-state > button:not(.primary-action) {
  padding: 7px 11px;
  border: 1px solid #53677f;
  border-radius: 4px;
  color: #dce9f7;
  background: #26364d;
  font-size: 11px;
  cursor: pointer;
}

.project-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px;
}

.project-card {
  display: block;
  width: 100%;
  padding: 17px;
  border: 1px solid #2d3d52;
  border-radius: 7px;
  color: inherit;
  background: #182438;
  text-align: left;
  cursor: pointer;
}

.project-card:hover,
.project-card.current {
  border-color: #4b7da7;
  background: #1c2c43;
}

.project-card-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.project-card h2 {
  margin: 0 0 7px;
  color: #edf1f5;
  font-size: 15px;
  font-weight: 600;
}

.project-card-heading small {
  display: block;
  overflow-wrap: anywhere;
  color: #8997aa;
  font-size: 10px;
}

.current-project-badge {
  flex: 0 0 auto;
  padding: 4px 6px;
  border-radius: 4px;
  color: #bde8d5;
  background: #245243;
  font-size: 9px;
  white-space: nowrap;
}

.project-card dl {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin: 19px 0 0;
}

.project-card dt {
  margin-bottom: 4px;
  color: #718198;
  font-size: 9px;
}

.project-card dd {
  margin: 0;
  color: #d5deea;
  font-size: 11px;
}

@media (max-width: 720px) {
  .projects-page {
    padding: 24px 18px 36px;
  }

  .projects-header {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>

<style>
/* UI-2-C-1: authenticated PDF document preview */
.document-preview-scroll {
  overflow: hidden;
}

.document-preview-page {
  width: 100%;
  max-width: none;
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 24px clamp(20px, 3vw, 42px) 20px;
}

.document-preview-heading {
  flex: 0 0 auto;
  margin-bottom: 18px;
}

.document-preview-heading > div {
  min-width: 0;
}

.document-preview-heading h1 {
  max-width: 100%;
  font-size: 22px;
  overflow-wrap: anywhere;
}

.pdf-preview-shell {
  min-height: 420px;
  flex: 1 1 auto;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: #525659;
  box-shadow: var(--shadow-sm);
}

.pdf-viewer {
  width: 100%;
  height: 100%;
  min-height: 420px;
  display: block;
  border: 0;
  background: #525659;
}

.pdf-preview-state,
.unsupported-preview {
  min-height: 420px;
  display: grid;
  place-content: center;
  justify-items: center;
  gap: 12px;
  padding: 24px;
  color: var(--color-text-secondary);
  background: var(--color-surface);
  text-align: center;
}

.pdf-preview-state button {
  padding: 8px 13px;
  border: 1px solid var(--color-border);
  border-radius: 7px;
  color: var(--color-text);
  background: var(--color-surface);
}

.pdf-loader {
  width: 24px;
  height: 24px;
  border: 2px solid var(--color-border);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: pdf-preview-spin .8s linear infinite;
}

@keyframes pdf-preview-spin {
  to { transform: rotate(360deg); }
}

.unsupported-preview {
  flex: 1 1 auto;
  border: 1px solid var(--color-border);
  border-radius: 8px;
}

.unsupported-preview > span {
  font-size: 28px;
  color: var(--color-text-muted);
}

.unsupported-preview h2,
.unsupported-preview p {
  margin: 0;
}

.unsupported-preview h2 {
  color: var(--color-text);
  font-size: 17px;
}

.compact-file-info {
  flex: 0 0 auto;
  margin-top: 10px;
  padding: 9px 12px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  color: var(--color-text-secondary);
  background: var(--color-surface);
  font-size: 11px;
}

.compact-file-info summary {
  color: var(--color-text-secondary);
  cursor: pointer;
  font-weight: 700;
}

.compact-file-info dl {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin: 12px 0 0;
}

.compact-file-info dt {
  color: var(--color-text-muted);
}

.compact-file-info dd {
  margin: 3px 0 0;
  color: var(--color-text);
  overflow-wrap: anywhere;
}

@media (max-width: 768px) {
  .document-preview-page { padding: 18px 14px; }
  .pdf-preview-shell, .pdf-viewer, .pdf-preview-state, .unsupported-preview { min-height: 360px; }
  .compact-file-info dl { grid-template-columns: 1fr 1fr; }
}

@media (prefers-reduced-motion: reduce) {
  .pdf-loader { animation: none; }
}
</style>

<style>
/* Keep the UI-2-B header grid authoritative after all legacy style blocks. */
.topbar {
  display: grid;
  grid-template-columns: minmax(150px, auto) minmax(210px, 520px) minmax(180px, auto);
  gap: 24px;
  align-items: center;
}

.header-search-zone {
  display: flex;
  min-width: 0;
  justify-content: center;
}

.header-search-zone .header-search-trigger {
  width: min(100%, 520px);
}

.top-actions {
  justify-content: flex-end;
}

@media (max-width: 1100px) {
  .topbar {
    grid-template-columns: minmax(120px, auto) minmax(180px, 1fr) auto;
    gap: 14px;
  }
}

@media (max-width: 850px) {
  .topbar {
    grid-template-columns: minmax(104px, auto) 38px auto;
    gap: 10px;
  }
}

@media (max-width: 768px) {
  .topbar {
    grid-template-columns: minmax(84px, 1fr) 38px auto;
    gap: 8px;
  }
}
</style>

<style>
/* UI-2-C: Northstar dynamic workbench */
.app-shell {
  --ns-accent: #287fda;
  --ns-accent-soft: #eaf3ff;
  --ns-panel: var(--color-surface);
  height: 100vh;
  min-height: 640px;
  overflow: hidden;
  background: var(--color-bg);
}

.app-shell .sidebar {
  position: relative;
  isolation: isolate;
  width: 236px;
  flex: 0 0 236px;
  overflow: hidden;
  padding: 22px 14px 16px;
  color: #aebbd0;
  background:
    radial-gradient(circle at 18% 12%, rgb(68 91 179 / 20%), transparent 32%),
    radial-gradient(circle at 84% 58%, rgb(51 76 151 / 14%), transparent 36%),
    linear-gradient(168deg, #09152e 0%, #0b1732 45%, #0c1933 100%);
}

.app-shell .sidebar::before {
  content: '';
  position: absolute;
  inset: 0;
  z-index: -2;
  opacity: .42;
  background:
    radial-gradient(ellipse at 20% 35%, rgb(78 106 190 / 18%), transparent 34%),
    radial-gradient(ellipse at 88% 76%, rgb(43 105 150 / 12%), transparent 32%);
}

.star-layer { position: absolute; inset: 0; z-index: -1; pointer-events: none; }
.star-layer::before, .star-layer::after { content: ''; position: absolute; width: 2px; height: 2px; border-radius: 50%; background: #d9e8ff; box-shadow: 26px 54px #fff, 67px 116px #88a6db, 114px 34px #dbe8ff, 161px 88px #7396cd, 204px 142px #fff, 37px 226px #7295cf, 89px 306px #fff, 149px 265px #8aa7d8, 212px 348px #dbe8ff, 24px 431px #fff, 122px 476px #789bd2, 193px 535px #fff, 58px 618px #8ca9d7, 172px 694px #fff, 218px 772px #7697ca; }
.star-layer::before { top: 5px; left: 2px; animation: ns-twinkle 7s ease-in-out infinite; }
.star-layer::after { top: 20px; left: 17px; opacity: .42; transform: scale(.65); animation: ns-twinkle 9s 2s ease-in-out infinite reverse; }
.star-layer-two { transform: translate(9px, 31px) rotate(180deg); opacity: .48; }
@keyframes ns-twinkle { 0%, 100% { opacity: .3; } 50% { opacity: .75; } }

.app-shell.sidebar-collapsed .sidebar { width: 68px; flex-basis: 68px; padding-inline: 10px; }
.sidebar .brand { position: relative; z-index: 1; min-height: 48px; gap: 11px; padding: 0 6px 20px; }
.northstar-mark { width: 32px; height: 32px; flex: 0 0 32px; overflow: visible; color: #d9eaff; fill: currentColor; }
.northstar-mark circle { fill: #6ebcff; }
.brand-copy { min-width: 0; }
.sidebar .brand strong { color: #f7faff; font-size: 16px; letter-spacing: .01em; }
.sidebar .brand small { color: #8191ad; font-size: 10px; }
.sidebar-toggle { margin-left: auto; border-color: rgb(142 164 205 / 22%) !important; color: #9fb1cd !important; background: rgb(17 34 67 / 78%) !important; }
.sidebar nav { position: relative; z-index: 1; margin-top: 24px; }
.sidebar .nav-label { color: #657896; }
.sidebar .nav-item { position: relative; border: 1px solid transparent; color: #aebbd0; background: transparent; }
.sidebar .nav-item:hover { color: #e8f1ff; background: rgb(91 122 177 / 12%); }
.sidebar .nav-item.active { border-color: rgb(115 164 230 / 15%); color: #fff; background: linear-gradient(90deg, rgb(52 116 191 / 28%), rgb(47 85 145 / 15%)); box-shadow: inset 3px 0 #65b3ff; }
.sidebar .nav-icon { color: #8eadd3; }
.sidebar .nav-item.active .nav-icon { color: #88c7ff; }
.sidebar .nav-soon { color: #8fa1bc !important; background: rgb(72 91 126 / 35%) !important; }
.sidebar-footer { position: relative; z-index: 1; }
.sidebar .new-project { border: 1px solid rgb(142 172 217 / 18%); color: #e5efff; background: rgb(43 70 113 / 45%); }
.sidebar .new-project:hover { background: rgb(53 88 142 / 58%); }
.sidebar .help { display: none !important; }
.sidebar .user { width: 100%; border: 0; border-top: 1px solid rgb(133 155 192 / 16%); color: inherit; background: transparent; cursor: pointer; }
.sidebar .user > span { background: linear-gradient(145deg, #5b769f, #354a6d); }
.sidebar .user strong { color: #e3eaf5; }
.sidebar .user i { display: none; }
.sidebar-collapsed .sidebar .brand { justify-content: center; padding-inline: 0; }
.sidebar-collapsed .sidebar .northstar-mark { width: 30px; height: 30px; }

.main-content { display: flex; min-width: 0; height: 100vh; flex-direction: column; }
.topbar { height: 72px; flex: 0 0 72px; gap: 24px; padding: 0 26px; border-color: var(--color-border); background: var(--color-surface); }
.page-heading { display: flex; min-width: 140px; flex-direction: column; gap: 4px; }
.page-heading span { color: var(--color-text-muted); font-size: 10px; letter-spacing: .04em; }
.page-heading strong { color: var(--color-text); font-size: 17px; }
.header-search-zone { margin-left: auto; flex: 0 1 340px; }
.header-search-trigger { width: 100%; justify-content: flex-start; }
.header-search-trigger kbd { margin-left: auto; }
.top-actions { position: relative; gap: 8px; }
.context-restore-button { white-space: nowrap; }
.header-user-button { width: 36px !important; height: 36px !important; padding: 0 !important; border-radius: 50% !important; }
.header-user-button > span { width: 100% !important; height: 100% !important; }
.header-user-button small { display: none !important; }
.user-popover .user-identity { display: none; }

.dynamic-workspace { min-height: 0 !important; height: calc(100vh - 72px); flex: 1; overflow: hidden; background: var(--color-bg); }
.dynamic-workspace > .workbench-pane { min-width: 0; min-height: 0; }
.module-pane { overflow: hidden; background: var(--color-bg); }
.module-scroll { height: 100%; overflow: auto; }
.module-page { width: min(900px, 100%); margin: 0 auto; padding: 48px clamp(28px, 6vw, 74px); }
.module-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 30px; }
.module-heading h1 { margin: 9px 0 7px; color: var(--color-text); font-size: clamp(26px, 3vw, 36px); }
.module-heading p { margin: 0; color: var(--color-text-secondary); font-size: 13px; }
.detail-card { padding: 28px; border: 1px solid var(--color-border); border-radius: 16px; background: var(--color-surface); box-shadow: var(--shadow-sm); }
.detail-title { display: flex; align-items: center; gap: 14px; padding-bottom: 24px; border-bottom: 1px solid var(--color-border); }
.detail-title > span { width: 44px; height: 44px; display: grid; flex: 0 0 44px; place-items: center; border-radius: 12px; color: var(--ns-accent); background: var(--ns-accent-soft); font-weight: 800; }
.detail-title > .file-detail-icon { font-size: 9px; }
.detail-title small, .detail-title h2 { display: block; }
.detail-title small { margin-bottom: 4px; color: var(--color-text-muted); font-size: 11px; }
.detail-title h2 { margin: 0; color: var(--color-text); font-size: 20px; overflow-wrap: anywhere; }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0; margin: 0; padding: 10px 0; }
.detail-grid > div { min-width: 0; padding: 16px 8px; border-bottom: 1px solid var(--color-border); }
.detail-grid dt { margin-bottom: 7px; color: var(--color-text-muted); font-size: 11px; }
.detail-grid dd { margin: 0; color: var(--color-text); font-size: 13px; overflow-wrap: anywhere; }
.coming-note { display: flex; gap: 12px; margin-top: 22px; padding: 15px; border: 1px solid var(--color-border); border-radius: 10px; color: var(--color-text-secondary); background: var(--color-surface-soft); }
.coming-note b { color: var(--ns-accent); }
.coming-note strong { color: var(--color-text); font-size: 12px; }
.coming-note p { margin: 4px 0 0; font-size: 11px; }
.file-facts { margin: 18px 0; padding: 10px 12px; border-radius: 8px; color: var(--color-text-secondary); background: var(--color-surface-soft); font-size: 12px; }
.module-upload { padding: 10px 14px; border: 1px solid var(--color-border); border-radius: 9px; color: var(--color-text); background: var(--color-surface); font-size: 12px; font-weight: 700; }
.module-status { display: block; margin: -17px 0 18px; }
.module-empty { min-height: 360px; display: grid; place-content: center; justify-items: center; gap: 9px; color: var(--color-text-secondary); text-align: center; }
.module-empty > span { font-size: 28px; color: var(--color-text-muted); }
.module-empty h2, .module-empty p { margin: 0; }
.module-empty h2 { color: var(--color-text); font-size: 19px; }
.coming-page { display: grid; place-content: center; justify-items: center; gap: 10px; text-align: center; }
.coming-page > span { width: 54px; height: 54px; display: grid; place-items: center; border-radius: 16px; color: var(--ns-accent); background: var(--ns-accent-soft); font-size: 24px; }
.coming-page small { color: var(--color-text-muted); letter-spacing: .1em; }
.coming-page h1, .coming-page p { margin: 0; }
.coming-page h1 { color: var(--color-text); }
.coming-page p { max-width: 440px; color: var(--color-text-secondary); font-size: 13px; }

.workspace .conversation { max-width: none; margin: 0; padding: 0; background: var(--color-bg); }
.workspace .conversation-inner { width: min(900px, 100%); min-height: 100%; padding: 42px clamp(28px, 6vw, 72px) 34px; }
.workspace .welcome { padding: 12px 0 8px; }
.workspace .welcome h1 { margin-top: 10px; font-size: 31px; }
.workspace .welcome.compact { padding: 0; }
.workspace .welcome.compact h1 { font-size: 20px; }
.workspace .welcome.compact p, .workspace .welcome.compact .eyebrow { display: none; }
.workspace .start-heading { margin-top: 32px; }
.workspace .prompt-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.workspace .prompt-card { min-height: 92px; border-radius: 12px; box-shadow: var(--shadow-sm); }
.workspace .composer-wrap { padding: 12px clamp(18px, 5vw, 62px) 18px; background: linear-gradient(transparent, var(--color-bg) 18%); }
.workspace .composer { max-width: 820px; margin: 0 auto; padding: 9px 11px; border-radius: 14px; box-shadow: 0 12px 34px rgb(15 23 42 / 10%); }
.workspace .composer textarea { min-height: 34px; max-height: 130px; padding: 7px 4px; resize: vertical; }
.workspace .composer .clip { display: flex; gap: 4px; align-items: center; white-space: nowrap; }
.workspace .messages { gap: 16px; }
.workspace .message { padding: 14px 16px; border-radius: 12px; font-size: 13px; }

.workspace .dynamic-panel { position: relative; display: flex; height: 100%; flex-direction: column; background: var(--color-surface); }
.workspace .dynamic-panel .pane-header { flex: 0 0 64px; height: 64px; padding: 0 18px; }
.dynamic-panel .pane-header span { color: var(--color-text-muted); font-size: 9px; letter-spacing: .08em; }
.dynamic-panel .pane-header strong { font-size: 15px; }
.workspace .dynamic-panel .resource-scroll { height: auto; flex: 1 1 auto; padding: 12px; }
.panel-subhead { padding: 13px 18px; border-bottom: 1px solid var(--color-border); background: var(--color-surface-soft); }
.panel-subhead strong, .panel-subhead small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.panel-subhead strong { color: var(--color-text); font-size: 12px; }
.panel-subhead small { margin-top: 4px; color: var(--color-text-muted); font-size: 9px; }
.resource-list { display: flex; flex-direction: column; gap: 6px; }
.resource-item { width: 100%; min-width: 0; display: flex; align-items: center; gap: 10px; padding: 11px 10px; border: 1px solid transparent; border-radius: 10px; color: var(--color-text); background: transparent; text-align: left; }
.resource-item:hover { background: var(--color-surface-soft); }
.resource-item.selected { border-color: color-mix(in srgb, var(--ns-accent) 25%, var(--color-border)); background: var(--ns-accent-soft); }
.resource-symbol { width: 34px; height: 34px; display: grid; flex: 0 0 34px; place-items: center; border-radius: 9px; color: var(--ns-accent); background: var(--color-surface-soft); }
.resource-item.selected .resource-symbol { background: var(--color-surface); }
.resource-item > span:nth-child(2) { min-width: 0; flex: 1; }
.resource-item strong, .resource-item small, .resource-item em { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.resource-item strong { color: var(--color-text); font-size: 11px; }
.resource-item small { margin-top: 4px; color: var(--color-text-secondary); font-size: 9px; }
.resource-item i { color: var(--ns-accent); font-style: normal; }
.file-resource-item { align-items: flex-start; }
.file-symbol { font-size: 7px; font-weight: 800; }
.resource-item em { margin-top: 5px; color: var(--color-text-muted); font-size: 8px; font-style: normal; }
.resource-item em b { width: 5px; height: 5px; display: inline-block; margin-right: 5px; border-radius: 50%; background: var(--color-text-muted); }
.resource-item em b.ingestion-completed { background: var(--color-success); }
.resource-item em b.ingestion-processing { background: var(--color-warning); }
.resource-item em b.ingestion-failed { background: var(--color-danger); }
.panel-empty { min-height: 220px; display: grid; place-content: center; justify-items: center; gap: 7px; color: var(--color-text-secondary); text-align: center; font-size: 11px; }
.panel-empty p { margin: 0; }
.panel-empty small { color: var(--color-text-muted); }
.panel-footer { flex: 0 0 auto; padding: 12px; border-top: 1px solid var(--color-border); background: var(--color-surface); }
.panel-footer button, .panel-footer label { width: 100%; min-height: 38px; display: grid; place-items: center; border: 1px solid var(--color-border); border-radius: 9px; color: var(--color-text); background: var(--color-surface); font-size: 11px; font-weight: 700; cursor: pointer; }
.panel-footer button:hover, .panel-footer label:hover { border-color: var(--ns-accent); color: var(--ns-accent); }
.panel-footer .disabled, .panel-footer button:disabled { opacity: .5; cursor: not-allowed; }

.conversation-list { display: flex; flex-direction: column; gap: 6px; }
.conversation-entry { position: relative; min-width: 0; display: flex; align-items: center; border: 1px solid transparent; border-radius: 10px; background: transparent; }
.conversation-entry:hover { background: var(--color-surface-soft); }
.conversation-entry.selected { border-color: color-mix(in srgb, var(--ns-accent) 24%, var(--color-border)); background: var(--ns-accent-soft); }
.conversation-open { min-width: 0; display: flex; flex: 1; align-items: center; gap: 9px; padding: 11px 7px 11px 10px; border: 0; color: var(--color-text-secondary); background: transparent; text-align: left; }
.conversation-open > span:last-child { min-width: 0; flex: 1; }
.conversation-open strong, .conversation-open small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.conversation-open strong { color: var(--color-text); font-size: 11px; }
.conversation-open small { margin-top: 4px; color: var(--color-text-muted); font-size: 8px; }
.conversation-actions { display: none; gap: 2px; padding-right: 6px; }
.conversation-entry:hover .conversation-actions, .conversation-entry:focus-within .conversation-actions { display: flex; }
.conversation-actions button { width: 24px; height: 24px; padding: 0; border: 0; border-radius: 5px; color: var(--color-text-muted); background: transparent; }
.conversation-actions button:hover, .conversation-actions button.active { color: var(--ns-accent); background: var(--color-surface); }
.rename-input { min-width: 0; width: calc(100% - 12px); margin: 7px 6px; padding: 7px 8px; border: 1px solid var(--ns-accent); border-radius: 6px; color: var(--color-text); background: var(--color-surface); outline: 0; font-size: 11px; }
.setting-list { display: flex; flex-direction: column; gap: 5px; }
.setting-list button { display: grid; grid-template-columns: 30px 1fr auto; align-items: center; gap: 8px; padding: 11px; border: 1px solid transparent; border-radius: 9px; color: var(--color-text-secondary); background: transparent; text-align: left; }
.setting-list button.selected { border-color: var(--color-border); color: var(--ns-accent); background: var(--color-surface-soft); }
.setting-list strong { color: var(--color-text); font-size: 11px; }
.setting-list small { color: var(--color-text-muted); font-size: 8px; }

.auth-card .brand { padding: 0; }
.auth-card .brand strong { color: #172033; }
.auth-card .brand .northstar-mark { color: #235da5; }
.auth-card .brand small { color: #778397; }

@media (max-width: 1050px) {
  .header-search-zone { flex-basis: 270px; }
  .workspace .prompt-grid { grid-template-columns: 1fr; }
  .detail-grid { grid-template-columns: 1fr; }
}

@media (max-width: 768px) {
  .app-shell { min-height: 100vh; }
  .app-shell .sidebar { width: 68px; flex-basis: 68px; }
  .topbar { height: 64px; flex-basis: 64px; padding: 0 14px; }
  .page-heading span { display: none; }
  .header-search-zone { display: none; }
  .dynamic-workspace { height: calc(100vh - 64px); display: block; }
  .module-page { padding: 28px 20px; }
  .module-heading { flex-direction: column; }
  .workspace .conversation-inner { padding: 26px 18px; }
  .workspace .welcome h1 { font-size: 26px; }
}

@media (prefers-reduced-motion: reduce) {
  .star-layer::before, .star-layer::after { animation: none; opacity: .45; }
}
</style>

<style>
/* UI-2-B: global header and navigation refinement. */
.sidebar > nav {
  margin-top: 20px;
  padding-top: 20px;
  border-top: 1px solid rgb(255 255 255 / 7%);
}

.sidebar .sidebar-footer {
  padding-top: 12px;
}

.sidebar .new-project {
  margin-top: 0;
}

.topbar {
  display: grid;
  grid-template-columns: minmax(150px, auto) minmax(210px, 520px) minmax(180px, auto);
  gap: 24px;
  align-items: center;
}

.page-heading {
  min-width: 0;
}

.page-heading strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-search-zone {
  display: flex;
  min-width: 0;
  justify-content: center;
}

.header-search-zone .header-search-trigger {
  width: min(100%, 520px);
}

.top-actions {
  justify-content: flex-end;
}

.context-restore-button {
  min-height: 36px;
  padding: 7px 10px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  color: var(--color-primary);
  background: var(--color-surface);
  font-size: 12px;
  font-weight: 650;
  white-space: nowrap;
}

.context-restore-button:hover {
  border-color: #9abbb7;
  background: var(--color-primary-soft);
}

.header-user-button small {
  max-width: 96px;
}

.workspace .user-message {
  border-color: #b9ddd8;
  background: var(--color-primary-soft);
}

.workspace .assistant-message {
  border-color: var(--color-border);
  background: var(--color-surface);
}

.workspace .assistant-message .markdown-body {
  font-size: 14px;
  line-height: 1.7;
}

.workspace .assistant-citations li,
.workspace .evidence-panel li {
  min-width: 0;
}

.workspace .citation-copy strong,
.workspace .evidence-panel li strong {
  overflow-wrap: anywhere;
  word-break: break-word;
}

@media (max-width: 1100px) {
  .topbar {
    grid-template-columns: minmax(120px, auto) minmax(180px, 1fr) auto;
    gap: 14px;
  }

  .header-user-button small {
    display: none;
  }

  .header-user-button {
    padding-right: 6px;
  }
}

@media (max-width: 850px) {
  .topbar {
    grid-template-columns: minmax(104px, auto) 38px auto;
    gap: 10px;
  }

  .header-search-zone {
    justify-content: flex-end;
  }
}

@media (max-width: 768px) {
  .topbar {
    grid-template-columns: minmax(84px, 1fr) 38px auto;
    gap: 8px;
  }

  .context-restore-button {
    display: none;
  }

  .header-user-button {
    max-width: 38px;
  }
}
</style>

<style>
/* Final UI-2-A layout authority: Sidebar | Assistant | optional Context. */
.app-shell {
  height: 100vh;
  min-height: 0;
  overflow: hidden;
}

.app-shell .sidebar {
  width: 236px;
  height: 100vh;
  flex: 0 0 236px;
}

.app-shell.sidebar-collapsed .sidebar {
  width: 68px;
  flex-basis: 68px;
}

.app-shell:not(.sidebar-collapsed) .sidebar .brand-copy,
.app-shell:not(.sidebar-collapsed) .sidebar .project-switcher > div,
.app-shell:not(.sidebar-collapsed) .sidebar .user > div {
  display: block;
}

.app-shell:not(.sidebar-collapsed) .sidebar .nav-label,
.app-shell:not(.sidebar-collapsed) .sidebar .nav-item > span:not(.nav-icon),
.app-shell:not(.sidebar-collapsed) .sidebar .new-project-label,
.app-shell:not(.sidebar-collapsed) .sidebar .help {
  display: inline;
}

.app-shell:not(.sidebar-collapsed) .sidebar .nav-icon,
.app-shell:not(.sidebar-collapsed) .sidebar .user > i {
  display: inline-grid;
}

.app-shell:not(.sidebar-collapsed) .sidebar .new-project {
  display: flex;
}

.sidebar-toggle:disabled {
  cursor: default;
  opacity: .55;
}

.main-content {
  display: flex;
  height: 100vh;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  flex-direction: column;
}

.topbar {
  flex: 0 0 72px;
}

.workspace {
  display: grid;
  min-width: 0;
  min-height: 0;
  height: auto;
  flex: 1 1 auto;
  overflow: hidden;
}

.workspace .conversation {
  display: flex;
  width: auto;
  max-width: none;
  min-width: 0;
  min-height: 0;
  margin: 0;
  padding: 0;
  overflow: hidden;
  flex-direction: column;
  background: var(--color-bg);
}

.workspace .conversation-scroll {
  min-width: 0;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  flex: 1 1 auto;
  overscroll-behavior: contain;
}

.workspace .conversation-inner {
  width: min(880px, 100%);
  min-width: 0;
  margin: 0 auto;
  padding: 28px clamp(18px, 4vw, 52px) 24px;
}

.workspace .composer-wrap {
  flex: 0 0 auto;
  padding: 12px clamp(18px, 4vw, 52px) 14px;
  border-top: 1px solid var(--color-border);
  background: var(--color-bg);
}

.workspace .composer {
  position: static;
  bottom: auto;
  width: min(776px, 100%);
  margin: 0 auto;
}

.workspace .markdown-body {
  max-width: 100%;
  overflow-x: auto;
  font-size: 14px;
  line-height: 1.7;
}

.workspace .markdown-body pre,
.workspace .markdown-body table {
  max-width: 100%;
}

.workspace .project-panel {
  min-width: 0;
  min-height: 0;
  padding: 0;
  overflow: hidden;
  border-top: 0;
  border-left: 1px solid var(--color-border);
  background: var(--color-surface-soft);
}

.workspace .project-panel .pane-scroll {
  height: calc(100% - 58px);
  padding: 16px;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.workspace .project-panel .project-summary,
.workspace .project-panel dl {
  max-width: none;
}

.workspace .pane-resizer {
  display: block;
  width: 6px;
  min-width: 6px;
}

.projects-page,
.files-page,
.placeholder-page {
  min-height: 0;
  flex: 1 1 auto;
  overflow: auto;
}

@media (max-width: 850px) and (min-width: 769px) {
  .app-shell:not(.sidebar-collapsed) .sidebar {
    width: 236px;
    flex-basis: 236px;
    padding: 24px 16px 16px;
  }

  .app-shell:not(.sidebar-collapsed) .sidebar .brand {
    justify-content: flex-start;
    padding: 0 34px 24px 8px;
  }

  .app-shell:not(.sidebar-collapsed) .sidebar .project-switcher {
    justify-content: flex-start;
    padding: 11px 12px;
  }

  .app-shell:not(.sidebar-collapsed) .sidebar .nav-item {
    justify-content: flex-start;
    padding: 10px 12px;
  }

  .app-shell:not(.sidebar-collapsed) .sidebar .user {
    justify-content: flex-start;
  }

  .app-shell:not(.sidebar-collapsed) .sidebar .project-options {
    display: block;
  }
}

@media (max-width: 768px) {
  .topbar {
    height: 64px;
    flex-basis: 64px;
  }

  .workspace .conversation-inner {
    padding: 22px 16px;
  }

  .workspace .composer-wrap {
    padding: 10px 12px 12px;
  }
}
</style>

<style>
/* Keep the document viewer authoritative over earlier module-page defaults. */
.workspace .document-preview-scroll { overflow: hidden; }
.workspace .document-preview-page {
  width: 100%;
  max-width: none;
  height: 100%;
  margin: 0;
  padding: 24px clamp(20px, 3vw, 42px) 20px;
}
.workspace .document-preview-heading { margin-bottom: 18px; }
@media (max-width: 768px) {
  .workspace .document-preview-page { padding: 18px 14px; }
}
</style>

<style>
/* UI-2-C final cascade guard */
.app-shell .sidebar {
  position: relative;
  isolation: isolate;
  overflow: hidden;
  padding: 22px 14px 16px;
  background:
    radial-gradient(circle at 18% 12%, rgb(68 91 179 / 20%), transparent 32%),
    radial-gradient(circle at 84% 58%, rgb(51 76 151 / 14%), transparent 36%),
    linear-gradient(168deg, #09152e 0%, #0b1732 45%, #0c1933 100%);
}
.app-shell:not(.sidebar-collapsed) .sidebar .help { display: none !important; }
.app-shell:not(.sidebar-collapsed) .sidebar .user > i { display: none; }
.main-content .dynamic-workspace { height: auto; flex: 1 1 auto; }
.workspace .dynamic-panel { display: flex; height: 100%; flex-direction: column; background: var(--color-surface); }
.workspace .dynamic-panel .pane-header { height: 64px; flex: 0 0 64px; }
.workspace .dynamic-panel .resource-scroll { height: auto; flex: 1 1 auto; padding: 12px; }
.workspace .dynamic-panel .panel-footer { flex: 0 0 auto; }
.workspace .module-pane { display: block; min-width: 0; min-height: 0; overflow: hidden; }
.workspace .coming-page { display: grid; }
@media (max-width: 768px) {
  .app-shell .sidebar { width: 68px; flex-basis: 68px; padding-inline: 10px; }
  .main-content .dynamic-workspace { display: block; }
}
</style>

<style>
/* Final UI-2-B header authority. */
.topbar {
  display: grid;
  grid-template-columns: minmax(150px, auto) minmax(210px, 520px) minmax(180px, auto);
  gap: 24px;
  align-items: center;
}

.header-search-zone {
  display: flex;
  min-width: 0;
  justify-content: center;
}

.header-search-zone .header-search-trigger {
  width: min(100%, 520px);
}

.top-actions {
  justify-content: flex-end;
}

@media (max-width: 1100px) {
  .topbar {
    grid-template-columns: minmax(120px, auto) minmax(180px, 1fr) auto;
    gap: 14px;
  }
}

@media (max-width: 850px) {
  .topbar {
    grid-template-columns: minmax(104px, auto) 38px auto;
    gap: 10px;
  }
}

@media (max-width: 768px) {
  .topbar {
    grid-template-columns: minmax(84px, 1fr) 38px auto;
    gap: 8px;
  }
}
</style>

<style>
/* UI-2-A: fixed navigation with a resizable Assistant and Context workspace. */
.app-shell {
  height: 100vh;
  overflow: hidden;
  background: var(--color-bg);
}

.sidebar {
  width: 236px;
  flex: 0 0 236px;
  height: 100vh;
  overflow: visible;
  transition: width .18s ease, flex-basis .18s ease;
}

.sidebar .brand {
  position: relative;
  min-height: 40px;
  padding-right: 34px;
}

.sidebar-toggle {
  position: absolute;
  top: 2px;
  right: 0;
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 1px solid #344155;
  border-radius: 7px;
  color: #9eabba;
  background: #172234;
  font-size: 15px;
}

.sidebar-toggle:hover {
  color: #fff;
  border-color: #526176;
  background: #202d40;
}

.sidebar-collapsed .sidebar {
  width: 68px;
  flex-basis: 68px;
  padding-right: 10px;
  padding-left: 10px;
}

.sidebar-collapsed .sidebar .brand {
  display: grid;
  justify-content: center;
  gap: 8px;
  min-height: 78px;
  padding: 0 0 12px;
}

.sidebar-collapsed .brand-mark {
  width: 34px;
  height: 34px;
}

.sidebar-collapsed .brand-copy,
.sidebar-collapsed .project-switcher > div,
.sidebar-collapsed .project-switcher > span:last-child,
.sidebar-collapsed .nav-label,
.sidebar-collapsed .nav-item > span:not(.nav-icon),
.sidebar-collapsed .nav-soon,
.sidebar-collapsed .new-project-label,
.sidebar-collapsed .help,
.sidebar-collapsed .user > div,
.sidebar-collapsed .user > i {
  display: none;
}

.sidebar-collapsed .sidebar-toggle {
  position: static;
  width: 34px;
}

.sidebar-collapsed .project-switcher {
  display: flex;
  width: 100%;
  min-height: 40px;
  justify-content: center;
  padding: 8px;
}

.sidebar-collapsed .project-switcher::before {
  content: '⌄';
  color: #cbd4df;
  font-size: 16px;
}

.sidebar-collapsed .project-options {
  display: block;
  left: 58px;
  width: 224px;
  margin-top: -42px;
}

.sidebar-collapsed .nav-item {
  justify-content: center;
  padding-right: 0;
  padding-left: 0;
}

.sidebar-collapsed .sidebar .nav-item .nav-icon {
  display: inline-grid;
}

.sidebar-collapsed .new-project {
  display: grid;
  width: 100%;
  min-height: 40px;
  place-items: center;
  padding: 8px;
  font-size: 17px;
}

.sidebar-collapsed .sidebar .user {
  display: flex;
  justify-content: center;
  padding: 12px 0 0;
}

.sidebar-collapsed .sidebar .user > span {
  display: grid;
}

.app-shell:not(.sidebar-collapsed) .sidebar .brand-copy,
.app-shell:not(.sidebar-collapsed) .sidebar .project-switcher > div,
.app-shell:not(.sidebar-collapsed) .sidebar .nav-label,
.app-shell:not(.sidebar-collapsed) .sidebar .nav-item > span,
.app-shell:not(.sidebar-collapsed) .sidebar .new-project,
.app-shell:not(.sidebar-collapsed) .sidebar .help,
.app-shell:not(.sidebar-collapsed) .sidebar .user > div,
.app-shell:not(.sidebar-collapsed) .sidebar .user > i {
  display: initial;
}

.app-shell:not(.sidebar-collapsed) .sidebar .brand-copy,
.app-shell:not(.sidebar-collapsed) .sidebar .project-switcher > div,
.app-shell:not(.sidebar-collapsed) .sidebar .user > div {
  display: block;
}

.app-shell:not(.sidebar-collapsed) .sidebar .nav-item > span,
.app-shell:not(.sidebar-collapsed) .sidebar .user > i {
  display: inline-grid;
}

.app-shell:not(.sidebar-collapsed) .sidebar .new-project {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
}

.project-switcher {
  padding: 11px 12px;
}

.project-switcher > div {
  min-width: 0;
}

.nav-icon {
  display: inline-grid;
  width: 20px;
  place-items: center;
  color: #8794a7;
  font-size: 15px;
}

.nav-item.active .nav-icon {
  color: var(--color-primary);
}

.nav-item.is-unavailable:not(.active) {
  color: #778498;
}

.nav-item.is-unavailable .nav-soon {
  color: #9ba7b8;
  background: #273448;
}

.sidebar .user {
  width: 100%;
  border-right: 0;
  border-bottom: 0;
  border-left: 0;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.sidebar .user:hover {
  background: #182438;
}

.main-content {
  display: flex;
  min-width: 0;
  height: 100vh;
  overflow: hidden;
  flex-direction: column;
}

.topbar {
  position: relative;
  z-index: 20;
  flex: 0 0 72px;
  height: 72px;
  min-width: 0;
  padding: 0 24px;
  background: var(--color-surface);
}

.page-heading {
  flex: 0 0 auto;
}

.top-actions {
  position: relative;
  min-width: 0;
  gap: 8px;
}

.pane-restore-actions {
  display: flex;
  gap: 6px;
}

.pane-restore-actions button,
.header-search-trigger,
.header-icon-button,
.header-user-button {
  min-height: 36px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  color: var(--color-text-secondary);
  background: var(--color-surface);
}

.pane-restore-actions button {
  padding: 7px 9px;
  color: var(--color-primary);
  font-size: 12px;
}

.pane-restore-actions button:hover,
.header-search-trigger:hover,
.header-icon-button:hover,
.header-user-button:hover {
  border-color: #aebbc8;
  background: var(--color-surface-soft);
}

.header-search-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  width: clamp(190px, 20vw, 280px);
  padding: 7px 9px;
  text-align: left;
}

.header-search-trigger > span:nth-child(2) {
  overflow: hidden;
  flex: 1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-search-trigger kbd,
.search-input-wrap kbd {
  padding: 2px 6px;
  border: 1px solid var(--color-border);
  border-radius: 5px;
  color: var(--color-text-muted);
  background: var(--color-bg);
  font: 11px/1.5 inherit;
  white-space: nowrap;
}

.header-icon-button {
  width: 36px;
  padding: 0;
  font-size: 17px;
}

.header-user-button {
  display: flex;
  align-items: center;
  max-width: 150px;
  gap: 7px;
  padding: 5px 9px 5px 6px;
}

.header-user-button > span,
.user-identity > span {
  display: grid;
  width: 26px;
  height: 26px;
  place-items: center;
  flex: 0 0 26px;
  border-radius: 7px;
  color: #fff;
  background: var(--color-primary);
  font-size: 12px;
}

.header-user-button small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-popover {
  position: absolute;
  top: calc(100% + 12px);
  right: 0;
  z-index: 30;
  width: 280px;
  padding: 10px;
  border: 1px solid var(--color-border);
  border-radius: 10px;
  color: var(--color-text);
  background: var(--color-surface);
  box-shadow: 0 18px 44px rgb(15 23 42 / 16%);
}

.popover-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 5px 10px;
  border-bottom: 1px solid var(--color-border);
}

.popover-heading strong {
  color: var(--color-text);
  font-size: 14px;
}

.popover-heading button {
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: 6px;
  color: var(--color-text-secondary);
  background: transparent;
  font-size: 18px;
}

.popover-heading button:hover {
  background: var(--color-surface-soft);
}

.popover-empty {
  padding: 28px 10px;
  color: var(--color-text-muted);
  text-align: center;
  font-size: 13px;
}

.theme-popover {
  width: 190px;
}

.theme-popover > button,
.user-popover > button {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  margin-top: 4px;
  padding: 9px 10px;
  border: 0;
  border-radius: 7px;
  color: var(--color-text-secondary);
  background: transparent;
  text-align: left;
  font-size: 13px;
}

.theme-popover > button:hover,
.theme-popover > button.selected,
.user-popover > button:hover:not(:disabled) {
  color: var(--color-text);
  background: var(--color-surface-soft);
}

.theme-popover > button.selected::after {
  content: '✓';
  color: var(--color-primary);
}

.user-identity {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 10px;
  padding: 14px 6px 10px;
}

.user-identity div {
  min-width: 0;
}

.user-identity strong,
.user-identity small {
  display: block;
}

.user-identity strong {
  color: var(--color-text);
  font-size: 13px;
}

.user-identity small {
  overflow: hidden;
  margin-top: 3px;
  color: var(--color-text-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-popover > button:disabled {
  cursor: not-allowed;
  opacity: .55;
}

.user-popover > button small {
  color: var(--color-text-muted);
  font-size: 11px;
}

.user-popover > .user-logout {
  margin-top: 8px;
  border-top: 1px solid var(--color-border);
  border-radius: 0;
  color: var(--color-danger);
}

.search-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 12vh 24px 24px;
  background: rgb(15 23 42 / 42%);
  backdrop-filter: blur(3px);
}

.search-panel {
  width: min(680px, 100%);
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-modal);
  background: var(--color-surface);
  box-shadow: 0 26px 70px rgb(15 23 42 / 25%);
}

.search-input-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--color-border);
}

.search-input-wrap > span {
  color: var(--color-text-muted);
  font-size: 20px;
}

.search-input-wrap input {
  min-width: 0;
  flex: 1;
  border: 0;
  outline: 0;
  color: var(--color-text);
  background: transparent;
  font-size: 15px;
}

.search-input-wrap:focus-within {
  box-shadow: inset 0 -2px var(--color-primary);
}

.search-empty {
  padding: 40px 24px;
  color: var(--color-text-secondary);
  text-align: center;
}

.search-empty strong {
  color: var(--color-text);
  font-size: 14px;
}

.search-empty p {
  margin: 8px 0 0;
  font-size: 13px;
}

.workspace {
  display: grid;
  min-width: 0;
  min-height: 0;
  height: auto;
  flex: 1 1 auto;
  overflow: hidden;
  background: var(--color-bg);
}

.workbench-pane {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: var(--color-surface);
}

.pane-header {
  display: flex;
  min-height: 58px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
}

.pane-header > div {
  min-width: 0;
}

.pane-header span,
.pane-header strong {
  display: block;
}

.pane-header span {
  color: var(--color-text-muted);
  font-size: 10px;
  font-weight: 650;
  letter-spacing: .08em;
  text-transform: uppercase;
}

.pane-header strong {
  overflow: hidden;
  margin-top: 2px;
  color: var(--color-text);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pane-header > button {
  width: 30px;
  height: 30px;
  border: 0;
  border-radius: 6px;
  color: var(--color-text-secondary);
  background: transparent;
  font-size: 18px;
}

.pane-header > button:hover:not(:disabled) {
  background: var(--color-surface-soft);
}

.pane-header > button:disabled {
  cursor: not-allowed;
  opacity: .35;
}

.pane-scroll {
  height: calc(100% - 58px);
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.reserved-context p {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 12px;
  line-height: 1.6;
}

.pane-resizer {
  position: relative;
  z-index: 4;
  width: 6px;
  min-width: 6px;
  height: 100%;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: var(--color-bg);
  cursor: col-resize;
  touch-action: none;
}

.pane-resizer::after {
  position: absolute;
  inset: 0 2px;
  content: '';
  background: var(--color-border);
  transition: background .14s ease;
}

.pane-resizer:hover::after,
.is-resizing-workbench .pane-resizer::after {
  background: var(--color-primary);
}

.is-resizing-workbench {
  cursor: col-resize;
  user-select: none;
}

.conversation {
  display: flex;
  width: auto;
  max-width: none;
  margin: 0;
  padding: 0;
  flex-direction: column;
  background: var(--color-bg);
}

.conversation-scroll {
  min-width: 0;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  flex: 1 1 auto;
  overscroll-behavior: contain;
}

.conversation-inner {
  width: min(880px, 100%);
  min-width: 0;
  margin: 0 auto;
  padding: 28px clamp(18px, 4vw, 52px) 24px;
}

.welcome h1 {
  font-size: clamp(25px, 2.4vw, 32px);
}

.prompt-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.prompt-card {
  min-width: 0;
}

.messages {
  min-width: 0;
  margin-top: 24px;
}

.message,
.message > span,
.markdown-body,
.assistant-citations,
.citation-copy {
  min-width: 0;
}

.message > span,
.markdown-body,
.citation-copy strong {
  overflow-wrap: anywhere;
}

.assistant-message {
  width: 100%;
  max-width: 100%;
}

.markdown-body {
  overflow-x: auto;
  font-size: 14px;
  line-height: 1.7;
}

.composer-wrap {
  flex: 0 0 auto;
  padding: 12px clamp(18px, 4vw, 52px) 14px;
  border-top: 1px solid var(--color-border);
  background: color-mix(in srgb, var(--color-bg) 92%, transparent);
}

.composer {
  position: static;
  width: min(776px, 100%);
  margin: 0 auto;
  box-shadow: 0 8px 22px rgb(15 23 42 / 9%);
}

.composer textarea {
  min-width: 0;
  min-height: 40px;
  max-height: 120px;
  padding: 10px 0;
  flex: 1;
  resize: vertical;
  border: 0;
  outline: 0;
  color: var(--color-text);
  background: transparent;
  font-size: 14px;
  line-height: 1.45;
}

.composer textarea::placeholder {
  color: var(--color-text-muted);
}

.project-panel {
  padding: 0;
  border-left: 1px solid var(--color-border);
  background: var(--color-surface-soft);
}

.project-panel .pane-scroll {
  padding: 16px;
}

.context-panel-section {
  min-width: 0;
  margin-bottom: 18px;
}

.project-panel .project-summary {
  margin-top: 8px;
}

.project-panel .summary-title > div {
  min-width: 0;
}

.project-panel .summary-title small,
.project-panel dd {
  max-width: none;
  overflow-wrap: anywhere;
  white-space: normal;
}

.context-section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}

.context-section-heading strong {
  display: block;
  margin-top: 5px;
  color: var(--color-text);
  font-size: 14px;
}

.context-section-heading > small {
  padding: 3px 6px;
  border-radius: 5px;
  color: var(--color-text-secondary);
  background: var(--color-bg);
  font-size: 11px;
}

.evidence-panel ul {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.evidence-panel li {
  display: flex;
  min-width: 0;
  gap: 9px;
  padding: 10px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
}

.evidence-panel li > div {
  min-width: 0;
}

.evidence-panel li strong,
.evidence-panel li small {
  display: block;
  overflow-wrap: anywhere;
}

.evidence-panel li strong {
  color: var(--color-text);
  font-size: 12px;
  line-height: 1.45;
}

.evidence-panel li small {
  margin-top: 4px;
  color: var(--color-text-secondary);
  font-size: 11px;
}

.context-empty {
  padding: 16px;
  border: 1px dashed var(--color-border);
  border-radius: 8px;
  color: var(--color-text-muted);
  background: var(--color-surface);
  font-size: 12px;
  line-height: 1.6;
}

.reserved-context {
  padding-top: 16px;
  border-top: 1px solid var(--color-border);
}

.projects-page,
.files-page,
.placeholder-page {
  min-height: 0;
  flex: 1 1 auto;
  overflow: auto;
}

html[data-theme='dark'] .topbar,
html[data-theme='dark'] .pane-header,
html[data-theme='dark'] .workbench-pane,
html[data-theme='dark'] .project-summary,
html[data-theme='dark'] .context-block,
html[data-theme='dark'] .evidence-panel li,
html[data-theme='dark'] .context-empty,
html[data-theme='dark'] .composer,
html[data-theme='dark'] .project-card,
html[data-theme='dark'] .files-table-container,
html[data-theme='dark'] .modal,
html[data-theme='system'] .topbar,
html[data-theme='system'] .pane-header,
html[data-theme='system'] .workbench-pane,
html[data-theme='system'] .project-summary,
html[data-theme='system'] .context-block,
html[data-theme='system'] .evidence-panel li,
html[data-theme='system'] .context-empty,
html[data-theme='system'] .composer,
html[data-theme='system'] .project-card,
html[data-theme='system'] .files-table-container,
html[data-theme='system'] .modal {
  color: var(--color-text);
  background: var(--color-surface);
}

html[data-theme='dark'] .conversation,
html[data-theme='dark'] .projects-page,
html[data-theme='dark'] .files-page,
html[data-theme='dark'] .placeholder-page,
html[data-theme='system'] .conversation,
html[data-theme='system'] .projects-page,
html[data-theme='system'] .files-page,
html[data-theme='system'] .placeholder-page {
  color: var(--color-text);
  background: var(--color-bg);
}

html[data-theme='dark'] .assistant-message,
html[data-theme='system'] .assistant-message {
  background: var(--color-surface);
}

@media (prefers-color-scheme: light) {
  html[data-theme='system'] .topbar,
  html[data-theme='system'] .pane-header,
  html[data-theme='system'] .workbench-pane,
  html[data-theme='system'] .project-summary,
  html[data-theme='system'] .context-block,
  html[data-theme='system'] .evidence-panel li,
  html[data-theme='system'] .context-empty,
  html[data-theme='system'] .composer,
  html[data-theme='system'] .project-card,
  html[data-theme='system'] .files-table-container,
  html[data-theme='system'] .modal {
    background: var(--color-surface);
  }
}

@media (max-width: 1240px) {
  .header-search-trigger {
    width: 190px;
  }
}

@media (max-width: 1100px) {
  .workspace {
    display: grid;
  }

  .prompt-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 850px) {
  .topbar {
    padding: 0 14px;
  }

  .header-search-trigger {
    width: 38px;
    justify-content: center;
    padding: 0;
  }

  .header-search-trigger > span:nth-child(2),
  .header-search-trigger kbd,
  .header-user-button small {
    display: none;
  }

  .header-user-button {
    padding-right: 6px;
  }

  .sidebar .nav-item .nav-icon {
    display: inline-grid;
  }

  .project-switcher {
    min-height: 42px;
    justify-content: center;
    padding: 8px;
  }
}

@media (max-width: 768px) {
  .topbar {
    flex-basis: 64px;
    height: 64px;
  }

  .page-eyebrow {
    display: none;
  }

  .page-heading strong {
    font-size: 15px;
  }

  .appearance-button {
    display: none;
  }

  .conversation-inner {
    padding: 22px 16px;
  }

  .composer-wrap {
    padding: 10px 12px 12px;
  }

  .composer small {
    margin-left: 0;
  }

  .welcome {
    display: block;
  }

  .project-status {
    margin-top: 12px;
  }
}
</style>

<style>
/* Keep the UI-1 documents surface authoritative over the legacy scoped table skin. */
#app .files-page {
  min-height: calc(100vh - 76px);
  padding: 40px 42px 56px;
  color: var(--color-text);
  background: var(--color-bg);
}

#app .files-page-header {
  margin-bottom: 28px;
}

#app .files-page-header .panel-label {
  display: block;
  margin-bottom: 8px;
  color: var(--color-text-muted);
  font-size: 12px;
  font-weight: 650;
  letter-spacing: .08em;
}

#app .files-page-header h1 {
  margin: 0;
  color: var(--color-text);
  font-size: 28px;
  font-weight: 700;
}

#app .files-page-state {
  min-height: 220px;
  padding: 32px;
  border: 1px dashed #c9d2dc;
  border-radius: var(--radius-card);
  color: var(--color-text-secondary);
  background: var(--color-surface);
  font-size: 14px;
}

#app .files-page-error {
  border-color: #efc1bb;
  color: var(--color-danger);
  background: var(--color-danger-soft);
}

#app .files-page-state button {
  min-height: 36px;
  padding: 8px 14px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  color: var(--color-text-secondary);
  background: var(--color-surface);
  font-size: 13px;
}

#app .files-empty-hint {
  color: var(--color-text-muted);
  font-size: 13px;
}

#app .files-table-container {
  overflow-x: auto;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}

#app .files-table {
  min-width: 960px;
  color: var(--color-text);
  font-size: 13px;
}

#app .files-table thead {
  border-color: var(--color-border);
  background: #f0f4f7;
}

#app .files-table th {
  padding: 12px 14px;
  color: var(--color-text-secondary);
  font-size: 12px;
  font-weight: 650;
  letter-spacing: .02em;
  text-transform: none;
}

#app .files-table tbody .file-row {
  display: table-row;
  margin: 0;
  border-color: var(--color-border);
  background: transparent;
  font-size: inherit;
}

#app .files-table tbody .file-row:hover {
  background: var(--color-surface-soft);
}

#app .files-table td {
  padding: 14px;
  color: var(--color-text-secondary);
  vertical-align: middle;
}

#app .files-table .file-name-cell {
  display: table-cell;
  min-width: 240px;
}

#app .files-table .file-size,
#app .files-table .file-time,
#app .files-table .file-version {
  color: var(--color-text-secondary);
  font-size: 13px;
}

#app .files-table .ingestion-badge,
#app .files-table .current-badge,
#app .files-table .historical-badge {
  min-height: 24px;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 650;
}

#app .files-table .ingestion-processing {
  color: var(--color-warning);
  background: var(--color-warning-soft);
}

#app .files-table .ingestion-completed,
#app .files-table .current-badge {
  color: var(--color-success);
  background: var(--color-success-soft);
}

#app .files-table .ingestion-failed {
  color: var(--color-danger);
  background: var(--color-danger-soft);
}

#app .files-table .ingestion-unknown,
#app .files-table .historical-badge {
  color: var(--color-text-secondary);
  background: #eef2f6;
}

#app .files-table .ingestion-details,
#app .files-table .ingestion-error {
  color: var(--color-text-secondary);
  font-size: 12px;
}

#app .files-table .ingestion-error {
  color: var(--color-danger);
}

#app .files-table .reingest-button {
  min-height: 32px;
  padding: 6px 10px;
  border: 1px solid #a9b8c8;
  border-radius: 7px;
  color: var(--color-info);
  background: var(--color-surface);
  font-size: 12px;
}

#app .files-table .reingest-button:hover:not(:disabled) {
  background: var(--color-info-soft);
}

@media (max-width: 1100px) {
  #app .files-page {
    padding: 32px 28px 48px;
  }
}

@media (max-width: 768px) {
  #app .files-page {
    padding: 28px 20px 40px;
  }
}
</style>

<style>
/* UI-1 visual baseline. Business state and request behavior remain unchanged. */
.app-shell {
  min-height: 100vh;
  color: var(--color-text);
  background: var(--color-bg);
}

.sidebar {
  width: 248px;
  flex-basis: 248px;
  padding: 24px 16px 16px;
  color: #aeb8c7;
  background: var(--color-sidebar);
  border-right: 1px solid rgb(255 255 255 / 5%);
}

.brand {
  gap: 12px;
  padding: 0 8px 24px;
}

.brand-mark {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  color: #ffffff;
  background: var(--color-primary);
  box-shadow: 0 0 0 1px rgb(255 255 255 / 12%);
  font-size: 15px;
}

.brand strong {
  color: #f8fafc;
  font-size: 16px;
  letter-spacing: .01em;
}

.brand small {
  margin-top: 4px;
  color: #8491a4;
  font-size: 12px;
}

.project-switcher {
  min-height: 58px;
  gap: 10px;
  padding: 10px;
  border-color: #344155;
  border-radius: var(--radius-control);
  color: #d6dde7;
  background: var(--color-sidebar-soft);
  transition: border-color .16s ease, background .16s ease;
}

.project-switcher:hover {
  border-color: #526176;
  background: #202d40;
}

.project-avatar {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  color: var(--color-primary);
  background: #e6f3f1;
  font-size: 14px;
}

.project-switcher strong {
  color: #f1f5f9;
  font-size: 13px;
}

.project-switcher small,
.project-options small {
  color: #8f9bad;
  font-size: 12px;
}

.project-options {
  width: 216px;
  margin-top: 6px;
  padding: 6px;
  border-color: #344155;
  border-radius: 10px;
  background: #182335;
  box-shadow: 0 18px 36px rgb(0 0 0 / 24%);
}

.project-options button {
  padding: 10px;
  border-radius: 7px;
}

.project-options strong {
  font-size: 13px;
}

nav {
  margin-top: 32px;
}

.nav-label,
.panel-label {
  color: var(--color-text-muted);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: .08em;
}

.nav-label {
  padding: 0 12px 10px;
  color: #738095;
}

.nav-item {
  min-height: 42px;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  color: #aab5c5;
  font-size: 14px;
  transition: color .16s ease, background .16s ease;
}

.nav-item:hover {
  color: #eef2f7;
  background: #1d293b;
}

.nav-item.active {
  color: #d9faf5;
  background: rgb(15 118 110 / 28%);
  box-shadow: inset 3px 0 var(--color-primary);
}

.nav-item .nav-soon {
  margin-left: auto;
  padding: 3px 6px;
  border-radius: 4px;
  color: #8e9aad;
  background: #273346;
  font-size: 10px;
  font-weight: 500;
}

.sidebar-footer {
  padding-top: 20px;
}

.new-project {
  min-height: 40px;
  margin: 0 0 12px;
  border: 1px solid #d7dee7;
  border-radius: var(--radius-control);
  color: #1f2937;
  background: #f8fafc;
  font-size: 13px;
}

.new-project:hover {
  background: #ffffff;
}

.help {
  padding: 8px;
  color: #738095;
  font-size: 12px;
  line-height: 1.5;
}

.user {
  gap: 10px;
  margin-top: 12px;
  padding: 16px 8px 8px;
  border-color: #2a3648;
}

.user > span {
  width: 34px;
  height: 34px;
  background: #3d4b61;
  font-size: 13px;
}

.user strong {
  color: #edf2f7;
  font-size: 13px;
}

.user small {
  display: block;
  max-width: 130px;
  margin-top: 3px;
  overflow: hidden;
  color: #8591a3;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.main-content {
  min-height: 100vh;
  background: var(--color-bg);
}

.topbar {
  height: 72px;
  padding: 0 32px;
  border-color: var(--color-border);
  background: rgb(255 255 255 / 94%);
  box-shadow: var(--shadow-sm);
}

.page-heading {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.page-heading strong {
  color: var(--color-text);
  font-size: 18px;
  font-weight: 700;
}

.page-eyebrow {
  color: var(--color-text-muted);
  font-size: 12px;
}

.top-actions {
  gap: 16px;
}

.header-project {
  max-width: 280px;
  text-align: right;
}

.header-project span,
.header-project small {
  display: block;
}

.header-project span {
  overflow: hidden;
  color: var(--color-text);
  font-size: 13px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-project small {
  margin-top: 3px;
  overflow: hidden;
  color: var(--color-text-muted);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-badge,
.project-status-badge,
.current-project-badge,
.current-badge,
.historical-badge,
.version-badge,
.ingestion-badge {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 650;
  white-space: nowrap;
}

.status-badge,
.project-status-badge,
.current-project-badge,
.current-badge {
  color: var(--color-success);
  background: var(--color-success-soft);
}

.status-badge.muted,
.historical-badge,
.version-badge {
  color: var(--color-text-secondary);
  background: #eef2f6;
}

.workspace {
  grid-template-columns: minmax(0, 1fr) 304px;
  min-height: calc(100vh - 72px);
  background: var(--color-bg);
}

.conversation {
  max-width: 980px;
  padding: 40px 48px 32px;
}

.welcome {
  gap: 24px;
}

.eyebrow {
  color: var(--color-primary);
  font-family: inherit;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .04em;
}

.welcome h1 {
  margin: 10px 0 8px;
  color: var(--color-text);
  font-size: 28px;
  line-height: 1.25;
}

.welcome p {
  max-width: 620px;
  color: var(--color-text-secondary);
  font-size: 14px;
  line-height: 1.6;
}

.project-status {
  padding: 6px 9px;
  border-radius: 6px;
  color: var(--color-success);
  background: var(--color-success-soft);
  font-size: 12px;
}

.start-heading {
  margin-top: 32px;
  color: var(--color-text-muted);
  font-family: inherit;
  font-size: 12px;
  font-weight: 650;
  letter-spacing: .04em;
}

.start-heading span {
  background: var(--color-border);
}

.prompt-grid {
  gap: 12px;
  margin-top: 12px;
}

.prompt-card {
  min-height: 82px;
  padding: 14px;
  border-color: var(--color-border);
  border-radius: 10px;
  color: var(--color-text-secondary);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
  transition: border-color .16s ease, box-shadow .16s ease, transform .16s ease;
}

.prompt-card:hover {
  border-color: #a9c9c5;
  box-shadow: 0 8px 20px rgb(15 23 42 / 7%);
  transform: translateY(-1px);
}

.prompt-card b {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  color: var(--color-primary);
  background: var(--color-primary-soft);
  font-size: 11px;
}

.prompt-card span {
  gap: 5px;
}

.prompt-card strong {
  color: var(--color-text);
  font-size: 13px;
}

.prompt-card small {
  color: var(--color-text-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.messages {
  gap: 16px;
  margin-top: 32px;
}

.message {
  max-width: min(76%, 680px);
  margin-left: auto;
  padding: 12px 16px;
  border: 0;
  border-radius: 10px 10px 2px 10px;
  color: #ffffff;
  background: var(--color-primary);
  box-shadow: var(--shadow-sm);
  font-size: 14px;
  line-height: 1.6;
}

.message > strong {
  color: #d5f5f0;
  font-size: 12px;
}

.assistant-message {
  display: block;
  width: 100%;
  max-width: 100%;
  margin-left: 0;
  padding: 22px 24px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  color: var(--color-text);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}

.assistant-message > strong {
  display: block;
  margin-bottom: 12px;
  color: var(--color-primary);
  font-size: 13px;
  letter-spacing: .01em;
}

.assistant-status {
  margin: 0 0 14px;
  padding: 10px 12px;
  border: 1px solid #efd1cc;
  border-radius: 8px;
  color: var(--color-danger);
  background: var(--color-danger-soft);
  font-size: 13px;
  font-weight: 650;
}

.loading-copy {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: var(--color-text-secondary);
  font-size: 14px;
}

.loading-copy i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-primary);
  box-shadow: 0 0 0 5px rgb(15 118 110 / 10%);
  animation: northstar-pulse 1.25s ease-in-out infinite;
}

@keyframes northstar-pulse {
  50% { opacity: .35; transform: scale(.8); }
}

.markdown-body {
  max-width: 78ch;
  overflow-x: auto;
  color: #334155;
  font-size: 15px;
  line-height: 1.72;
}

.markdown-body h1,
.markdown-body h2,
.markdown-body h3,
.markdown-body h4,
.markdown-body h5,
.markdown-body h6 {
  margin: 24px 0 10px;
  color: var(--color-text);
  line-height: 1.4;
}

.markdown-body h1 { font-size: 22px; }
.markdown-body h2 { font-size: 19px; }
.markdown-body h3 { font-size: 17px; }
.markdown-body h4,
.markdown-body h5,
.markdown-body h6 { font-size: 15px; }
.markdown-body p { margin: 10px 0; }
.markdown-body ul,
.markdown-body ol { margin: 10px 0; padding-left: 24px; }
.markdown-body li { margin: 5px 0; }
.markdown-body strong { color: var(--color-text); }

.markdown-body blockquote {
  margin: 16px 0;
  padding: 12px 16px;
  border-left: 3px solid var(--color-primary);
  border-radius: 0 8px 8px 0;
  color: var(--color-text-secondary);
  background: var(--color-primary-soft);
}

.markdown-body code {
  padding: 2px 5px;
  border-radius: 5px;
  color: #334155;
  background: #eef2f6;
  font-size: 13px;
}

.markdown-body pre {
  margin: 16px 0;
  padding: 16px;
  border-color: #263244;
  border-radius: 10px;
  background: #172033;
}

.markdown-body pre code {
  color: #edf2f7;
  font-size: 13px;
}

.markdown-body table {
  min-width: 560px;
  margin: 16px 0;
  border: 1px solid var(--color-border);
  border-collapse: separate;
  border-spacing: 0;
  border-radius: 8px;
  font-size: 13px;
}

.markdown-body th,
.markdown-body td {
  padding: 10px 12px;
  border: 0;
  border-right: 1px solid var(--color-border);
  border-bottom: 1px solid var(--color-border);
}

.markdown-body th:last-child,
.markdown-body td:last-child { border-right: 0; }
.markdown-body tr:last-child td { border-bottom: 0; }
.markdown-body th {
  color: var(--color-text);
  background: #eef3f6;
}
.markdown-body tr:nth-child(even) { background: var(--color-surface-soft); }

.assistant-citations {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--color-border);
  color: var(--color-text-secondary);
  font-size: 13px;
}

.assistant-citations .citation-heading {
  color: var(--color-text);
  font-size: 13px;
  font-weight: 700;
}

.assistant-citations ul {
  display: grid;
  gap: 8px;
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
}

.assistant-citations li {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface-soft);
}

.citation-icon {
  display: grid;
  place-items: center;
  flex: 0 0 28px;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  color: var(--color-info);
  background: var(--color-info-soft);
}

.citation-copy {
  min-width: 0;
}

.citation-copy strong,
.citation-copy small {
  display: block;
}

.citation-copy strong {
  overflow-wrap: anywhere;
  color: var(--color-text);
  font-size: 13px;
}

.citation-copy small {
  margin-top: 3px;
  color: var(--color-text-secondary);
  font-size: 12px;
}

.composer {
  position: sticky;
  bottom: 20px;
  z-index: 2;
  margin-top: 32px;
  padding: 9px 10px;
  border-color: #cbd5df;
  border-radius: 12px;
  background: var(--color-surface);
  box-shadow: 0 16px 36px rgb(15 23 42 / 12%);
}

.composer > div {
  gap: 10px;
}

.clip {
  padding: 8px 10px;
  border-radius: 7px;
  color: var(--color-primary);
  background: var(--color-primary-soft);
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.composer input {
  min-height: 40px;
  color: var(--color-text);
  font-size: 14px;
}

.composer input::placeholder {
  color: var(--color-text-muted);
}

.composer button {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  color: #ffffff;
  background: var(--color-primary);
  font-size: 18px;
}

.composer button:hover:not(:disabled) {
  background: var(--color-primary-hover);
}

.composer button:disabled {
  color: var(--color-text-muted);
  background: #e7ebef;
  cursor: not-allowed;
}

.composer small {
  margin: 6px 0 0 78px;
  color: var(--color-text-secondary);
  font-size: 12px;
}

.connection {
  margin-top: 12px;
  color: var(--color-text-muted);
  font-size: 12px;
}

.connection i {
  width: 7px;
  height: 7px;
}

.request-error {
  margin: 8px 0 0;
  padding: 10px 12px;
  border: 1px solid #efd1cc;
  border-radius: 8px;
  color: var(--color-danger);
  background: var(--color-danger-soft);
  font-size: 13px;
  line-height: 1.5;
}

.project-panel {
  padding: 32px 24px;
  border-color: var(--color-border);
  background: var(--color-surface-soft);
}

.project-panel h2 {
  margin: 8px 0 24px;
  color: var(--color-text);
  font-size: 20px;
}

.project-summary {
  padding: 16px;
  border: 1px solid var(--color-border);
  border-radius: 10px;
  background: var(--color-surface);
}

.summary-title {
  gap: 12px;
}

.summary-title > span {
  width: 38px;
  height: 38px;
  border-radius: 8px;
  color: var(--color-primary);
  background: var(--color-primary-soft);
}

.summary-title strong {
  color: var(--color-text);
  font-size: 14px;
}

.summary-title small {
  max-width: 170px;
  margin-top: 4px;
  overflow: hidden;
  color: var(--color-text-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.phase {
  margin: 20px 0 0;
  padding-top: 16px;
  border-top: 1px solid var(--color-border);
  color: var(--color-text-secondary);
  font-size: 13px;
}

.phase b {
  padding: 3px 7px;
  border-radius: 5px;
  color: var(--color-success);
  background: var(--color-success-soft);
  font-size: 12px;
}

.project-panel dl {
  gap: 16px;
  padding: 20px 0;
  border-color: var(--color-border);
}

.project-panel dl div {
  display: block;
  font-size: 12px;
}

.project-panel dt {
  margin-bottom: 4px;
  color: var(--color-text-muted);
}

.project-panel dd {
  color: var(--color-text-secondary);
  text-align: left;
  line-height: 1.45;
}

.projects-page,
.files-page,
.placeholder-page {
  min-height: calc(100vh - 72px);
  color: var(--color-text);
  background: var(--color-bg);
}

.projects-page,
.files-page {
  padding: 32px 40px 48px;
}

.projects-header,
.files-page-header {
  margin-bottom: 24px;
}

.projects-header h1,
.files-page-header h1,
.placeholder-page h1 {
  margin: 6px 0 6px;
  color: var(--color-text);
  font-size: 28px;
  line-height: 1.25;
}

.projects-header p,
.files-project-context,
.placeholder-page p {
  color: var(--color-text-secondary);
  font-size: 14px;
}

.primary-action,
.upload-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 40px;
  padding: 9px 14px;
  border: 1px solid var(--color-primary);
  border-radius: var(--radius-control);
  color: #ffffff;
  background: var(--color-primary);
  font-size: 13px;
  font-weight: 650;
}

.primary-action:hover,
.upload-button:hover {
  background: var(--color-primary-hover);
}

.project-list {
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.project-card {
  position: relative;
  padding: 20px;
  border-color: var(--color-border);
  border-radius: var(--radius-card);
  color: var(--color-text);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
  transition: border-color .16s ease, box-shadow .16s ease, transform .16s ease;
}

.project-card:hover,
.project-card.current {
  border-color: #9bc4bf;
  background: var(--color-surface);
  box-shadow: 0 10px 26px rgb(15 23 42 / 8%);
  transform: translateY(-1px);
}

.project-card.current {
  box-shadow: inset 3px 0 var(--color-primary), 0 10px 26px rgb(15 23 42 / 8%);
}

.project-card h2 {
  margin: 0;
  color: var(--color-text);
  font-size: 16px;
}

.project-card-heading small {
  display: none;
}

.project-card dl {
  grid-template-columns: 1fr;
  gap: 12px;
  margin: 20px 0 0;
}

.project-card dt {
  margin-bottom: 4px;
  color: var(--color-text-muted);
  font-size: 12px;
}

.project-card dd {
  color: var(--color-text-secondary);
  font-size: 13px;
}

.project-id {
  overflow-wrap: anywhere;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px !important;
}

.current-project-badge {
  margin-top: 16px;
}

.project-page-state,
.files-page-state {
  min-height: 220px;
  padding: 32px;
  border: 1px dashed #c9d2dc;
  border-radius: var(--radius-card);
  color: var(--color-text-secondary);
  background: var(--color-surface);
  font-size: 14px;
}

.project-page-error,
.files-page-error {
  border-color: #efc1bb;
  color: var(--color-danger);
  background: var(--color-danger-soft);
}

.files-page-header .panel-label {
  margin-bottom: 8px;
  color: var(--color-text-muted);
  font-size: 12px;
}

.files-project-context {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
  margin: 10px 0 0;
}

.files-upload {
  margin-top: 20px;
}

.files-upload .selected-file {
  color: var(--color-success) !important;
  font-size: 13px;
}

.files-table-container {
  overflow-x: auto;
  border-color: var(--color-border);
  border-radius: var(--radius-card);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}

.files-table {
  min-width: 960px;
  color: var(--color-text);
  font-size: 13px;
}

.files-table thead {
  border-color: var(--color-border);
  background: #f0f4f7;
}

.files-table th {
  padding: 12px 14px;
  color: var(--color-text-secondary);
  font-size: 12px;
  letter-spacing: .02em;
  text-transform: none;
}

.files-table tbody .file-row {
  display: table-row;
  margin: 0;
  border-color: var(--color-border);
  background: transparent;
  font-size: inherit;
}

.files-table tbody .file-row:hover {
  background: var(--color-surface-soft);
}

.files-table td {
  padding: 14px;
  color: var(--color-text-secondary);
  vertical-align: middle;
}

.files-table .file-row span {
  display: inline-flex;
  width: auto;
  height: auto;
  margin: 0;
  font-family: inherit;
}

.files-table .file-name-cell {
  display: table-cell;
  min-width: 240px;
}

.files-table .file-icon {
  margin-right: 8px !important;
  font-size: 16px;
  vertical-align: middle;
}

.files-table .file-name {
  display: inline !important;
  color: var(--color-text);
  font-size: 13px;
  font-weight: 650;
  vertical-align: middle;
}

.file-size,
.file-time,
.file-version {
  color: var(--color-text-secondary);
  font-size: 13px;
}

.ingestion-badge {
  min-height: 24px;
  font-size: 12px;
}

.ingestion-processing {
  color: var(--color-warning);
  background: var(--color-warning-soft);
}

.ingestion-completed {
  color: var(--color-success);
  background: var(--color-success-soft);
}

.ingestion-failed {
  color: var(--color-danger);
  background: var(--color-danger-soft);
}

.ingestion-unknown {
  color: var(--color-text-secondary);
  background: #eef2f6;
}

.ingestion-details,
.ingestion-error {
  margin-top: 5px;
  color: var(--color-text-secondary);
  font-size: 12px;
}

.ingestion-error {
  color: var(--color-danger);
}

.reingest-button {
  min-height: 32px;
  padding: 6px 10px;
  border-color: #a9b8c8;
  border-radius: 7px;
  color: var(--color-info);
  background: var(--color-surface);
  font-size: 12px;
}

.reingest-button:hover:not(:disabled) {
  background: var(--color-info-soft);
}

.placeholder-page {
  color: var(--color-text-secondary);
}

.placeholder-page::before {
  content: "即将开放";
  padding: 4px 8px;
  border-radius: 6px;
  color: var(--color-text-secondary);
  background: #e9eef3;
  font-size: 12px;
}

.modal-backdrop {
  background: rgb(15 23 42 / 52%);
  backdrop-filter: blur(3px);
}

.modal {
  padding: 28px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-modal);
  box-shadow: 0 24px 60px rgb(15 23 42 / 24%);
}

.modal h2 {
  color: var(--color-text);
  font-size: 20px;
}

.modal label {
  color: var(--color-text-secondary);
  font-size: 13px;
}

.modal input {
  min-height: 42px;
  padding: 10px 12px;
  border-color: var(--color-border);
  border-radius: var(--radius-control);
  color: var(--color-text);
  font-size: 14px;
}

.modal-actions button {
  min-height: 38px;
  padding: 8px 14px;
  border-radius: var(--radius-control);
  font-size: 13px;
}

.modal-actions button[type='submit'] {
  background: var(--color-primary);
}

.auth-shell {
  padding: 24px;
  background:
    radial-gradient(circle at 20% 20%, rgb(15 118 110 / 9%), transparent 34%),
    var(--color-bg);
}

.auth-card {
  width: min(440px, calc(100vw - 40px));
  gap: 12px;
  padding: 36px;
  border-color: var(--color-border);
  border-radius: var(--radius-modal);
  box-shadow: var(--shadow-md);
}

.auth-card .brand {
  padding: 0 0 12px;
}

.auth-card .brand strong {
  color: var(--color-text);
}

.auth-card .brand small {
  color: var(--color-text-secondary);
}

.auth-card h1 {
  color: var(--color-text);
  font-size: 28px;
}

.auth-card p,
.auth-card label {
  color: var(--color-text-secondary);
  font-size: 13px;
}

.auth-card input {
  min-height: 42px;
  border-color: var(--color-border);
  border-radius: var(--radius-control);
  color: var(--color-text);
  font-size: 14px;
}

.auth-card button {
  min-height: 42px;
  border-radius: var(--radius-control);
  background: var(--color-primary);
  font-size: 14px;
  font-weight: 650;
}

.auth-card button:hover:not(:disabled) {
  background: var(--color-primary-hover);
}

.auth-link {
  color: var(--color-primary) !important;
}

@media (max-width: 1100px) {
  .workspace {
    display: block;
  }

  .project-panel {
    border-top: 1px solid var(--color-border);
    border-left: 0;
  }

  .project-panel .project-summary,
  .project-panel dl {
    max-width: 720px;
  }
}

@media (max-width: 850px) {
  .sidebar {
    width: 72px;
    flex-basis: 72px;
    padding: 20px 10px 14px;
  }

  .brand {
    padding-bottom: 22px;
  }

  .brand-mark {
    width: 36px;
    height: 36px;
  }

  .nav-item {
    min-height: 44px;
  }

  .nav-item .nav-soon,
  .project-options {
    display: none;
  }

  .topbar {
    padding: 0 20px;
  }

  .header-project small {
    display: none;
  }

  .conversation {
    padding: 32px 28px;
  }

  .projects-page,
  .files-page {
    padding: 28px 24px 40px;
  }
}

@media (max-width: 768px) {
  .topbar {
    height: 68px;
  }

  .page-eyebrow,
  .header-project {
    display: none;
  }

  .top-actions {
    gap: 8px;
  }

  .conversation {
    padding: 28px 20px;
  }

  .welcome {
    display: block;
  }

  .project-status {
    display: inline-flex;
    margin-top: 16px;
  }

  .prompt-grid {
    grid-template-columns: 1fr;
  }

  .message {
    max-width: 90%;
  }

  .assistant-message {
    max-width: 100%;
    padding: 18px;
  }

  .composer {
    bottom: 12px;
  }

  .composer small {
    margin-left: 0;
  }

  .projects-header {
    gap: 16px;
  }

  .project-list {
    grid-template-columns: 1fr;
  }

  .files-table-container {
    margin-right: -4px;
  }
}
</style>

<style scoped>
.files-page {
  min-height: 100%;
  padding: 32px 38px 48px;
  color: #e8eef5;
}

.files-page-header {
  margin-bottom: 32px;
}

.files-page-header .panel-label {
  display: block;
  margin-bottom: 12px;
  color: #718198;
  font-size: 9px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.files-page-header h1 {
  margin: 0;
  color: #edf1f5;
  font-size: 24px;
  font-weight: 600;
}

.files-upload {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-top: 16px;
}

.files-upload .request-error {
  width: 100%;
  margin: 0;
}

.upload-button-disabled {
  pointer-events: none;
  cursor: not-allowed;
  opacity: 0.6;
}

.files-page-state {
  padding: 48px 20px;
  border-radius: 8px;
  background: #182438;
  color: #9aa7b8;
  font-size: 13px;
  text-align: center;
}

.files-page-state p {
  margin: 0 0 12px;
}

.files-page-state button {
  padding: 8px 16px;
  border: 0;
  border-radius: 5px;
  color: #dce9f7;
  background: #2f5574;
  font-size: 12px;
  cursor: pointer;
}

.files-page-state button:hover {
  background: #3a6589;
}

.files-page-error {
  border: 1px solid #5a3636;
  background: #2a1e1e;
  color: #e8b4b4;
}

.files-empty-hint {
  color: #718198;
  font-size: 11px;
}

.files-table-container {
  overflow-x: auto;
  border: 1px solid #2d3d52;
  border-radius: 8px;
  background: #182438;
}

.files-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.files-table thead {
  border-bottom: 1px solid #2d3d52;
  background: #1c2c43;
}

.files-table th {
  padding: 12px 16px;
  color: #8997aa;
  font-size: 10px;
  font-weight: 500;
  text-align: left;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.files-table tbody tr {
  border-bottom: 1px solid #2d3d52;
}

.files-table tbody tr:last-child {
  border-bottom: none;
}

.files-table tbody tr:hover {
  background: #1c2c43;
}

.files-table td {
  padding: 14px 16px;
  color: #cbd4df;
}

.file-name-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.file-icon {
  flex: 0 0 auto;
  font-size: 16px;
}

.file-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-size,
.file-time,
.file-version {
  color: #8997aa;
  font-size: 11px;
}

.file-status {
  text-align: right;
}

.ingestion-cell {
  max-width: 240px;
}

.ingestion-badge {
  display: inline-block;
  padding: 3px 8px;
  border-radius: 3px;
  font-size: 9px;
  font-weight: 500;
}

.ingestion-processing {
  color: #d7ca91;
  background: #514b2c;
}

.ingestion-completed {
  color: #bde8d5;
  background: #245243;
}

.ingestion-failed {
  color: #efb1b1;
  background: #5a3035;
}

.ingestion-unknown {
  color: #9aa7b8;
  background: #26364d;
}

.ingestion-details,
.ingestion-error {
  display: block;
  margin-top: 5px;
  overflow: hidden;
  color: #8997aa;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ingestion-error {
  color: #e9a5a5;
}

.file-actions {
  min-width: 92px;
  text-align: right;
}

.reingest-button {
  padding: 6px 9px;
  border: 1px solid #476b8a;
  border-radius: 4px;
  color: #c8e2f6;
  background: transparent;
  font-size: 10px;
  cursor: pointer;
}

.reingest-button:hover:not(:disabled) {
  background: #274866;
}

.reingest-button:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.current-badge {
  display: inline-block;
  padding: 3px 8px;
  border-radius: 3px;
  color: #bde8d5;
  background: #245243;
  font-size: 9px;
  font-weight: 500;
}

.historical-badge {
  display: inline-block;
  padding: 3px 8px;
  border-radius: 3px;
  color: #9aa7b8;
  background: #26364d;
  font-size: 9px;
  font-weight: 500;
}

@media (max-width: 720px) {
  .files-page {
    padding: 24px 18px 36px;
  }

  .files-table-container {
    overflow-x: scroll;
  }
}
</style>

<style>
/* Authoritative final layout overrides after the legacy scoped document styles. */
.workspace .document-preview-scroll { overflow: hidden; }
.workspace .document-preview-page {
  width: 100%;
  max-width: none;
  height: 100%;
  margin: 0;
  padding: 24px clamp(20px, 3vw, 42px) 20px;
}
.workspace .document-preview-heading { margin-bottom: 18px; }
.workspace .document-content-pane {
  display: flex !important;
  min-width: 0;
  min-height: 0;
  overflow: hidden !important;
  flex-direction: column;
  background: var(--color-bg);
}
.document-reader-header {
  min-height: 78px;
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 16px clamp(20px, 3vw, 42px);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
}
.document-reader-header > div { min-width: 0; }
.document-reader-header h1 { margin: 0; color: var(--color-text); font-size: 17px; font-weight: 700; overflow-wrap: anywhere; }
.document-reader-header p { margin: 6px 0 0; color: var(--color-text-secondary); font-size: 11px; }
.document-reader-header button { width: 30px; height: 30px; flex: 0 0 30px; border: 1px solid var(--color-border); border-radius: 7px; color: var(--color-text-secondary); background: var(--color-surface); font-size: 20px; line-height: 1; }
.document-reader-header button:hover { color: var(--color-text); background: var(--color-surface-soft); }
.pdf-toolbar { min-width: 0; min-height: 46px; display: flex; flex: 0 0 auto; align-items: center; gap: 12px; padding: 7px clamp(14px, 2vw, 24px); overflow-x: auto; border-bottom: 1px solid var(--color-border); background: var(--color-surface); scrollbar-width: thin; }
.pdf-toolbar-group { display: flex; flex: 0 0 auto; align-items: center; gap: 5px; }
.pdf-toolbar button, .pdf-toolbar select, .pdf-page-control input { height: 30px; border: 1px solid var(--color-border); border-radius: 6px; color: var(--color-text); background: var(--color-surface); font: inherit; font-size: 12px; letter-spacing: 0; }
.pdf-toolbar button { min-width: 30px; padding: 0 9px; }
.pdf-toolbar button:hover:not(:disabled), .pdf-toolbar select:hover:not(:disabled), .pdf-page-control input:hover:not(:disabled) { border-color: var(--color-accent); background: var(--color-surface-soft); }
.pdf-toolbar button:disabled, .pdf-toolbar select:disabled, .pdf-page-control input:disabled { cursor: not-allowed; opacity: .48; }
.pdf-toolbar select { min-width: 72px; padding: 0 8px; }
.pdf-fit-controls button { white-space: nowrap; }
.pdf-page-control { min-width: 126px; display: flex; flex: 0 0 auto; align-items: center; gap: 6px; margin-left: auto; color: var(--color-text-secondary); font-size: 12px; white-space: nowrap; }
.pdf-page-control input { width: 42px; padding: 0 5px; text-align: center; }
.document-reader-body { min-width: 0; min-height: 0; display: flex; flex: 1 1 auto; overflow: hidden; background: #525659; }
.document-scroll-container { min-width: 0; min-height: 0; flex: 1 1 auto; overflow-x: hidden; overflow-y: auto; }
.pdf-preview-content { display: flex; flex-direction: column; align-items: stretch; gap: 18px; padding: 24px clamp(16px, 3vw, 42px) 32px; overflow-x: auto; background: #525659; }
.pdf-page { width: max-content; min-width: 100%; display: flex; flex-direction: column; align-items: center; align-self: center; gap: 8px; }
.pdf-page-label { color: rgb(255 255 255 / 78%); font-size: 11px; letter-spacing: .02em; }
.pdf-page-canvas { display: block; max-width: none; height: auto; margin: 0 auto; background: #fff; box-shadow: 0 2px 12px rgb(0 0 0 / 24%); }
.pdf-preview-content { position: relative; }
.document-preview-loading { position: sticky; z-index: 1; top: 12px; display: flex; align-items: center; gap: 8px; align-self: center; margin: 0 auto -30px; padding: 8px 12px; border: 1px solid rgb(255 255 255 / 18%); border-radius: 8px; color: #fff; background: rgb(20 24 31 / 76%); font-size: 12px; }
.docx-preview-content { padding: 28px clamp(22px, 4vw, 56px) 44px; background: var(--color-surface); color: var(--color-text); }
.docx-preview-content > * { max-width: 900px; margin-left: auto; margin-right: auto; }
.docx-heading { margin-top: 24px; margin-bottom: 10px; color: var(--color-text); line-height: 1.3; }
.docx-heading:first-child { margin-top: 0; }
.docx-paragraph { margin-top: 0; margin-bottom: 14px; color: var(--color-text-secondary); line-height: 1.75; white-space: pre-wrap; }
.docx-list { margin-top: 0; margin-bottom: 16px; padding-left: 24px; color: var(--color-text-secondary); line-height: 1.75; }
.docx-table-wrap { margin-top: 18px; margin-bottom: 20px; overflow-x: auto; }
.docx-table { width: 100%; border-collapse: collapse; color: var(--color-text-secondary); font-size: 13px; }
.docx-table td { min-width: 100px; padding: 9px 11px; border: 1px solid var(--color-border); vertical-align: top; }
.docx-image-notice { margin-top: 12px; margin-bottom: 16px; padding: 10px 12px; border: 1px dashed var(--color-border); color: var(--color-text-muted); font-size: 12px; }
.document-reader-state { width: 100%; min-height: 0; display: grid; place-content: center; justify-items: center; gap: 12px; padding: 28px; color: var(--color-text-secondary); background: var(--color-surface); text-align: center; }
.document-reader-state button { padding: 8px 13px; border: 1px solid var(--color-border); border-radius: 7px; color: var(--color-text); background: var(--color-surface); }
.unsupported-document span, .document-empty-state > span { color: var(--color-text-muted); font-size: 30px; }
.unsupported-document h2, .unsupported-document p, .document-empty-state h2, .document-empty-state p { margin: 0; }
.unsupported-document h2, .document-empty-state h2 { color: var(--color-text); font-size: 17px; }
.document-empty-state { min-height: 0; display: grid; place-content: center; justify-items: center; gap: 10px; color: var(--color-text-secondary); text-align: center; }
.document-empty-state p { font-size: 12px; }
.workspace .document-content-pane + .pane-resizer { align-self: stretch; }
.workspace .document-content-pane ~ .dynamic-panel { min-height: 0; }
@media (max-width: 768px) {
  .document-reader-header { min-height: 70px; padding: 14px 16px; }
  .document-reader-header h1 { font-size: 15px; }
  .pdf-toolbar { gap: 8px; padding: 7px 12px; }
  .pdf-page-control { margin-left: 0; }
}
.app-shell .sidebar {
  position: relative !important;
  isolation: isolate;
  overflow: hidden !important;
  padding: 22px 14px 16px !important;
  background:
    radial-gradient(circle at 18% 12%, rgb(68 91 179 / 20%), transparent 32%),
    radial-gradient(circle at 84% 58%, rgb(51 76 151 / 14%), transparent 36%),
    linear-gradient(168deg, #09152e 0%, #0b1732 45%, #0c1933 100%) !important;
}
.app-shell:not(.sidebar-collapsed) .sidebar .help { display: none !important; }
.app-shell:not(.sidebar-collapsed) .sidebar .user > i { display: none !important; }
.main-content .dynamic-workspace { height: auto !important; flex: 1 1 auto !important; }
.workspace .dynamic-panel { display: flex !important; height: 100% !important; flex-direction: column !important; background: var(--color-surface) !important; }
.workspace .dynamic-panel .pane-header { height: 64px !important; flex: 0 0 64px !important; }
.workspace .dynamic-panel .resource-scroll { height: auto !important; flex: 1 1 auto !important; padding: 12px !important; }
.workspace .dynamic-panel .panel-footer { flex: 0 0 auto !important; }
.workspace .module-pane { min-width: 0; min-height: 0; overflow: hidden; }
.workspace .coming-page { display: grid; }
.app-shell {
  height: 100vh;
  min-height: 0;
  overflow: hidden;
}

.app-shell .sidebar {
  width: 236px;
  height: 100vh;
  flex: 0 0 236px;
}

.app-shell.sidebar-collapsed .sidebar {
  width: 68px;
  flex-basis: 68px;
}

.app-shell:not(.sidebar-collapsed) .sidebar .brand-copy,
.app-shell:not(.sidebar-collapsed) .sidebar .project-switcher > div,
.app-shell:not(.sidebar-collapsed) .sidebar .user > div {
  display: block;
}

.app-shell:not(.sidebar-collapsed) .sidebar .nav-label,
.app-shell:not(.sidebar-collapsed) .sidebar .nav-item > span:not(.nav-icon),
.app-shell:not(.sidebar-collapsed) .sidebar .new-project-label,
.app-shell:not(.sidebar-collapsed) .sidebar .help {
  display: inline;
}

.app-shell:not(.sidebar-collapsed) .sidebar .nav-icon,
.app-shell:not(.sidebar-collapsed) .sidebar .user > i {
  display: inline-grid;
}

.app-shell:not(.sidebar-collapsed) .sidebar .new-project {
  display: flex;
}

.main-content {
  display: flex;
  height: 100vh;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  flex-direction: column;
}

.topbar {
  flex: 0 0 72px;
}

.workspace {
  display: grid;
  min-width: 0;
  min-height: 0;
  height: auto;
  flex: 1 1 auto;
  overflow: hidden;
}

.workspace .conversation {
  display: flex;
  width: auto;
  max-width: none;
  min-width: 0;
  min-height: 0;
  margin: 0;
  padding: 0;
  overflow: hidden;
  flex-direction: column;
  background: var(--color-bg);
}

.workspace .conversation-scroll {
  min-width: 0;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  flex: 1 1 auto;
  overscroll-behavior: contain;
}

.workspace .conversation-inner {
  width: min(880px, 100%);
  min-width: 0;
  margin: 0 auto;
  padding: 28px clamp(18px, 4vw, 52px) 24px;
}

.workspace .composer-wrap {
  flex: 0 0 auto;
  padding: 12px clamp(18px, 4vw, 52px) 14px;
  border-top: 1px solid var(--color-border);
  background: var(--color-bg);
}

.workspace .composer {
  position: static;
  bottom: auto;
  width: min(776px, 100%);
  margin: 0 auto;
}

.workspace .markdown-body {
  max-width: 100%;
  overflow-x: auto;
  font-size: 14px;
  line-height: 1.7;
}

.workspace .project-panel {
  min-width: 0;
  min-height: 0;
  padding: 0;
  overflow: hidden;
  border-top: 0;
  border-left: 1px solid var(--color-border);
  background: var(--color-surface-soft);
}

.workspace .project-panel .pane-scroll {
  height: calc(100% - 58px);
  padding: 16px;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.workspace .project-panel .project-summary,
.workspace .project-panel dl {
  max-width: none;
}

.workspace .pane-resizer {
  display: block;
  width: 6px;
  min-width: 6px;
}

.projects-page,
.files-page,
.placeholder-page {
  min-height: 0;
  flex: 1 1 auto;
  overflow: auto;
}

@media (max-width: 850px) and (min-width: 769px) {
  .app-shell:not(.sidebar-collapsed) .sidebar {
    width: 236px;
    flex-basis: 236px;
    padding: 24px 16px 16px;
  }

  .app-shell:not(.sidebar-collapsed) .sidebar .brand,
  .app-shell:not(.sidebar-collapsed) .sidebar .project-switcher,
  .app-shell:not(.sidebar-collapsed) .sidebar .nav-item,
  .app-shell:not(.sidebar-collapsed) .sidebar .user {
    justify-content: flex-start;
  }

  .app-shell:not(.sidebar-collapsed) .sidebar .project-options {
    display: block;
  }
}

@media (max-width: 768px) {
  .topbar {
    height: 64px;
    flex-basis: 64px;
  }

  .workspace .conversation-inner {
    padding: 22px 16px;
  }

  .workspace .composer-wrap {
    padding: 10px 12px 12px;
  }
}
</style>

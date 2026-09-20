import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
import test from 'node:test'

const storage = new Map()
globalThis.localStorage = {
  getItem(key) { return storage.get(key) ?? null },
  setItem(key, value) { storage.set(key, value) },
  removeItem(key) { storage.delete(key) },
}
globalThis.window = new EventTarget()

const {
  conversationIdForProjectChange,
  createConversationId,
  requestAssistant,
} = await import('../src/services/api.ts')

test('requestAssistant sends message, project_id, and conversation_id', async () => {
  let requestBody
  globalThis.fetch = async (_input, init) => {
    requestBody = JSON.parse(init.body)
    return new Response(JSON.stringify({
      reply: 'ok',
      status: 'answered',
      citations: [],
    }), {
      status: 200,
      headers: {'Content-Type': 'application/json'},
    })
  }

  const conversationId = '77777777-7777-4777-8777-777777777777'
  await requestAssistant('检查进度', 'project-a', conversationId)

  assert.deepEqual(requestBody, {
    message: '检查进度',
    project_id: 'project-a',
    conversation_id: conversationId,
  })
})

test('project changes create a new conversation while same-project selection is stable', () => {
  const initial = createConversationId()
  const unchanged = conversationIdForProjectChange('project-a', 'project-a', initial)
  const changed = conversationIdForProjectChange('project-a', 'project-b', initial)

  assert.equal(unchanged, initial)
  assert.notEqual(changed, initial)
  assert.match(changed, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i)
})

test('App clears displayed chat through the project transition path', async () => {
  const appSource = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
  const transition = appSource.match(/function setCurrentProject[\s\S]*?\n}/)?.[0] ?? ''
  const sendMessage = appSource.match(/async function sendMessage[\s\S]*?\n}/)?.[0] ?? ''

  assert.match(transition, /conversationIdForProjectChange/)
  assert.match(transition, /messages\.value = \[\]/)
  assert.match(transition, /assistantResponses\.value = \[\]/)
  assert.match(appSource, /function selectProject[\s\S]*?setCurrentProject\(project\.project_id\)/)
  assert.match(appSource, /async function createProject[\s\S]*?setCurrentProject\(project\.project_id\)/)
  assert.match(sendMessage, /const requestConversationId = conversationId\.value/)
  assert.match(sendMessage, /conversationId\.value === requestConversationId/)
})

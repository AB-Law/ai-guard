import { setupServer } from 'msw/node'
import { handlers, resetMockState } from './handlers'

export const server = setupServer(...handlers)

export { resetMockState }

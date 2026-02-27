import { copyFileSync, existsSync, mkdirSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(process.cwd(), '..')
const dataDir = resolve(root, 'data')
const outDir = resolve(process.cwd(), 'public', 'data')
mkdirSync(outDir, { recursive: true })

const files = ['dashboard.json', 'strategy_state.json', 'metrics.json']
for (const f of files) {
  const src = resolve(dataDir, f)
  const dst = resolve(outDir, f)
  if (existsSync(src)) {
    copyFileSync(src, dst)
    console.log(`synced ${f}`)
  }
}

import { expect, test } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import { dirname } from 'node:path'

test('R3F/Drei app renders without console errors and paints canvas', async ({ page }) => {
  const consoleErrors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') {
      consoleErrors.push(message.text())
    }
  })
  page.on('pageerror', (error) => {
    consoleErrors.push(error.message)
  })

  await page.goto('/')
  await page.setViewportSize({ width: 1280, height: 720 })
  const canvas = page.locator('canvas')
  await expect(canvas).toBeVisible()
  await page.waitForTimeout(750)

  const screenshotPath = process.env.EVAL_SCREENSHOT_PATH
  if (screenshotPath) {
    await mkdir(dirname(screenshotPath), { recursive: true })
    await page.screenshot({ path: screenshotPath })
  }

  const paintedPixels = await canvas.evaluate((node) => {
    const canvasNode = node as HTMLCanvasElement
    const context =
      canvasNode.getContext('webgl2') ?? canvasNode.getContext('webgl')
    if (!context) return -1
    const { width, height } = canvasNode
    if (width === 0 || height === 0) return 0
    const sampleWidth = Math.max(1, Math.floor(width))
    const sampleHeight = Math.max(1, Math.floor(height))
    const sample = new Uint8Array(sampleWidth * sampleHeight * 4)
    context.readPixels(
      0,
      0,
      sampleWidth,
      sampleHeight,
      context.RGBA,
      context.UNSIGNED_BYTE,
      sample
    )
    let nonBackground = 0
    for (let index = 0; index < sample.length; index += 4) {
      const r = sample[index]
      const g = sample[index + 1]
      const b = sample[index + 2]
      const a = sample[index + 3]
      if (a > 0 && Math.abs(r - 219) + Math.abs(g - 234) + Math.abs(b - 254) > 24) {
        nonBackground += 1
      }
    }
    return nonBackground
  })

  expect(paintedPixels).toBeGreaterThan(100)
  expect(consoleErrors).toEqual([])
})

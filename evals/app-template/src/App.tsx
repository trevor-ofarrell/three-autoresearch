import { Canvas } from '@react-three/fiber'
import type { ComponentProps } from 'react'
import { SolutionScene, solutionCanvasProps } from './solution'

export function App() {
  const defaultCanvasProps = {
    shadows: true,
    camera: { position: [0, 1.1, 4.2], fov: 45 },
    gl: { antialias: true, alpha: false, preserveDrawingBuffer: true },
    onCreated: ({ gl }) => {
      gl.setClearColor('#dbeafe')
    }
  } satisfies ComponentProps<typeof Canvas>
  const canvasProps = { ...defaultCanvasProps, ...solutionCanvasProps } satisfies ComponentProps<typeof Canvas>

  return (
    <main className="app-shell">
      <section className="viewport" aria-label="Three.js domain eval">
        <Canvas {...canvasProps}>
          <SolutionScene />
        </Canvas>
      </section>
    </main>
  )
}

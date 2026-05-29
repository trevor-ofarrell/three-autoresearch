import { Float, OrbitControls } from '@react-three/drei'
import { Canvas, useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import * as THREE from 'three'

function DomainScene() {
  const meshRef = useRef<THREE.Mesh>(null)
  const material = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color: new THREE.Color('#4f46e5'),
        roughness: 0.42,
        metalness: 0.18
      }),
    []
  )

  useFrame((state, delta) => {
    if (!meshRef.current) return
    meshRef.current.rotation.x += delta * 0.22
    meshRef.current.rotation.y += delta * 0.34
    meshRef.current.position.y = Math.sin(state.clock.elapsedTime) * 0.08
  })

  return (
    <>
      <ambientLight intensity={0.45} />
      <directionalLight position={[3, 4, 5]} intensity={1.6} castShadow />
      <Float speed={1.4} rotationIntensity={0.3} floatIntensity={0.4}>
        <mesh ref={meshRef} material={material} castShadow receiveShadow>
          <icosahedronGeometry args={[1.15, 1]} />
        </mesh>
      </Float>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.35, 0]} receiveShadow>
        <circleGeometry args={[3.2, 64]} />
        <meshStandardMaterial color="#f8fafc" roughness={0.7} />
      </mesh>
      <OrbitControls enablePan={false} minDistance={3} maxDistance={6} />
    </>
  )
}

export function App() {
  return (
    <main className="app-shell">
      <section className="viewport" aria-label="Three.js domain eval">
        <Canvas
          shadows
          camera={{ position: [0, 1.1, 4.2], fov: 45 }}
          gl={{ antialias: true, alpha: false, preserveDrawingBuffer: true }}
          onCreated={({ gl }) => {
            gl.setClearColor('#dbeafe')
          }}
        >
          <DomainScene />
        </Canvas>
      </section>
    </main>
  )
}

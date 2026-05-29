"""Create a tiny local Three/R3F/WebGPU corpus for pipeline smoke tests."""

from __future__ import annotations

import json
from pathlib import Path

from corpus_lib import SHARDS_DIR, content_hash, workspace_rel


DOCS = [
    {
        "split": "train",
        "source_id": "smoke-three",
        "path": "r3f-basic.tsx",
        "language": "tsx",
        "text": """
React Three Fiber renders Three.js scenes through React components.
A minimal scene uses Canvas from @react-three/fiber, mesh geometry, material,
and lights. Hooks such as useFrame must run inside the Canvas tree.

```tsx
import { Canvas, useFrame } from '@react-three/fiber'
import { useRef } from 'react'
import * as THREE from 'three'

function Box() {
  const ref = useRef<THREE.Mesh>(null)
  useFrame((_, delta) => {
    if (ref.current) ref.current.rotation.y += delta
  })
  return (
    <mesh ref={ref}>
      <boxGeometry />
      <meshStandardMaterial color="orange" />
    </mesh>
  )
}

export function App() {
  return <Canvas><ambientLight /><Box /></Canvas>
}
```
""".strip(),
    },
    {
        "split": "train",
        "source_id": "smoke-tsl",
        "path": "tsl-notes.md",
        "language": "markdown",
        "text": """
Three.js Shading Language, often abbreviated TSL, builds shader graphs from
JavaScript or TypeScript expressions. TSL materials can target WebGPU and
WebGL backends. Node expressions should be composed instead of concatenating
shader strings when using the node material system.
""".strip(),
    },
    {
        "split": "val",
        "source_id": "smoke-webgpu",
        "path": "webgpu-fallback.ts",
        "language": "typescript",
        "text": """
WebGPU code should check navigator.gpu before requesting an adapter.
Applications that rely on WebGPURenderer need a fallback path for browsers
without WebGPU support. A good fallback keeps the scene usable instead of
crashing during renderer initialization.
""".strip(),
    },
]


def main() -> None:
    SHARDS_DIR.mkdir(parents=True, exist_ok=True)
    for split in {"train", "val"}:
        rows = []
        for doc in DOCS:
            if doc["split"] != split:
                continue
            digest = content_hash(doc["text"])
            rows.append({
                "text": doc["text"],
                "doc_id": f"{doc['source_id']}:{digest[:16]}",
                "source_id": doc["source_id"],
                "path": doc["path"],
                "canonical_url": f"smoke://{doc['path']}",
                "language": doc["language"],
                "topic_tags": "threejs,r3f,drei,tsl,webgpu",
                "allowed_use": "private_research_training",
                "license_note": "Synthetic smoke-test fixture.",
                "content_hash": digest,
            })
        out_path = SHARDS_DIR / f"shard_{split}_00000.jsonl"
        with out_path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"Wrote {len(rows)} rows to {workspace_rel(out_path)}")


if __name__ == "__main__":
    main()

"""Generate corpus-grounded production task banks for the local data factory."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BASE_CHECKS = [
    "clean_replay",
    "typecheck",
    "build",
    "playwright",
    "no_console_errors",
    "canvas_nonblank",
    "desktop_screenshot",
]
BASE_POINTS = 700
ALLOWED_FILE = "src/solution.tsx"
TASKS_DIR = Path(__file__).resolve().parents[1] / "evals" / "tasks"
POLICY_CHECK = {
    "name": "production_policy",
    "points": 100,
    "regex_none": [
        r"\bfetch\s*\(",
        r"\bXMLHttpRequest\b",
        r"\bWebSocket\b",
        r"\beval\s*\(",
        r"\bFunction\s*\(",
        r"@ts-ignore",
        r"@ts-nocheck",
        r"\bas\s+any\b",
        r"document\.body",
        r"HTMLCanvasElement\.prototype",
        r"WebGLRenderingContext\.prototype",
    ],
}


@dataclass(frozen=True)
class Blueprint:
    slug: str
    title: str
    kind: str
    topics: list[str]
    difficulty: str
    source_refs: list[dict[str, str]]
    objective: str
    constraints: list[str]
    semantic_checks: list[dict[str, Any]]
    train_scenarios: list[str]
    eval_scenario: str
    max_chars: int = 18_000


def check(name: str, points: int, **kwargs: Any) -> dict[str, Any]:
    return {"name": name, "points": points, **kwargs}


def imports_from(package: str, *symbols: str) -> str:
    joined = "|".join(symbols)
    return rf"import\s+{{[^}}]*\b({joined})\b[^}}]*}}\s+from\s+['\"]{package}['\"]"


R3F_IMPORTS = imports_from("@react-three/fiber", "useFrame", "useThree", "useLoader")
DREI_IMPORTS = imports_from(
    "@react-three/drei",
    "OrbitControls",
    "CameraControls",
    "Bounds",
    "Float",
    "Html",
    "ContactShadows",
    "AccumulativeShadows",
    "Environment",
    "Stage",
    "Instances",
    "Instance",
    "MeshReflectorMaterial",
    "MeshTransmissionMaterial",
    "Text",
    "Sparkles",
    "TransformControls",
    "PivotControls",
    "PerformanceMonitor",
    "RenderTexture",
    "PerspectiveCamera",
)


COMMON_CONSTRAINTS = [
    "Use strict TypeScript and keep the implementation deterministic.",
    "Edit only src/solution.tsx and export SolutionScene.",
    "Do not fetch external assets or depend on network URLs.",
    "Keep a visible, inspectable 3D result in the default desktop screenshot.",
    "Do not use eval, Function, prototype monkeypatching, or TypeScript escape hatches.",
]


TRAIN_SCENARIOS = [
    "an industrial monitoring viewport",
    "a product configurator inspection panel",
    "a scientific visualization workbench",
    "a creative coding editor preview",
    "a spatial analytics dashboard",
    "a technical design-review scene",
]


def variants(base: str) -> list[str]:
    return [f"{base} for {scenario}." for scenario in TRAIN_SCENARIOS]


def blueprint(
    slug: str,
    title: str,
    source_url: str,
    objective: str,
    semantic_checks: list[dict[str, Any]],
    topics: list[str],
    difficulty: str,
    kind: str = "generation",
    constraints: list[str] | None = None,
    train: list[str] | None = None,
    eval_scenario: str | None = None,
) -> Blueprint:
    all_checks = [POLICY_CHECK, *semantic_checks]
    return Blueprint(
        slug=slug,
        title=title,
        kind=kind,
        topics=topics,
        difficulty=difficulty,
        source_refs=[{"label": title, "url": source_url}],
        objective=objective,
        constraints=[*COMMON_CONSTRAINTS, *(constraints or [])],
        semantic_checks=all_checks,
        train_scenarios=train or variants(objective),
        eval_scenario=eval_scenario or f"{objective} for a held-out production diagnostics scene.",
    )


BLUEPRINTS: list[Blueprint] = [
    blueprint(
        "buffergeometry-terrain",
        "Three.js BufferGeometry",
        "https://threejs.org/docs/pages/BufferGeometry.html",
        "Build a procedural indexed terrain mesh with computed normals and visible elevation bands",
        [
            check("buffergeometry_indexed", 150, regex_all=[r"new\s+THREE\.BufferGeometry\s*\(", r"\.setAttribute\s*\(\s*['\"]position['\"]", r"\.setIndex\s*\(", r"\.computeVertexNormals\s*\("]),
            check("typed_geometry_arrays", 100, regex_all=[r"Float32Array", r"(Uint16Array|Uint32Array)"]),
        ],
        ["threejs", "buffergeometry", "terrain", "react-three-fiber"],
        "hard",
    ),
    blueprint(
        "drawrange-line-reveal",
        "Three.js webgl_buffergeometry_drawrange",
        "https://threejs.org/examples/webgl_buffergeometry_drawrange.html",
        "Create an animated route or signal path that reveals itself by changing BufferGeometry draw range",
        [
            check("drawrange_animation", 150, regex_all=[r"\.setDrawRange\s*\(", r"useFrame\s*\("]),
            check("line_geometry", 100, regex_any=[[r"<line", r"new\s+THREE\.Line"]]),
        ],
        ["threejs", "buffergeometry", "lines", "animation", "react-three-fiber"],
        "medium",
    ),
    blueprint(
        "points-wave-grid",
        "Three.js webgl_points_waves",
        "https://threejs.org/examples/webgl_points_waves.html",
        "Build a Points-based wave grid that updates a position buffer over time",
        [
            check("points_buffer", 150, regex_all=[r"<points", r"bufferGeometry", r"bufferAttribute"]),
            check("buffer_animation", 150, regex_all=[r"useFrame\s*\(", r"\.needsUpdate\s*=\s*true"]),
        ],
        ["threejs", "points", "animation", "react-three-fiber"],
        "hard",
    ),
    blueprint(
        "canvas-texture",
        "Three.js CanvasTexture",
        "https://threejs.org/docs/pages/CanvasTexture.html",
        "Generate a CanvasTexture in code and map it onto visible geometry",
        [
            check("canvas_texture", 150, regex_all=[r"document\.createElement\s*\(\s*['\"]canvas['\"]", r"new\s+THREE\.CanvasTexture\s*\("]),
            check("texture_usage", 100, regex_any=[[r"map=\{", r"\.map\s*="]]),
        ],
        ["threejs", "textures", "materials", "react-three-fiber"],
        "medium",
        constraints=["Creating an offscreen canvas for CanvasTexture is allowed; do not append it to the DOM."],
    ),
    blueprint(
        "datatexture-noise",
        "Three.js DataTexture",
        "https://threejs.org/docs/pages/DataTexture.html",
        "Create a procedural DataTexture and use wrapping/filtering choices intentionally",
        [
            check("data_texture", 150, regex_all=[r"new\s+THREE\.DataTexture\s*\(", r"Uint8Array", r"\.needsUpdate\s*=\s*true"]),
            check("texture_configuration", 100, regex_any=[[r"\.wrapS\s*=", r"\.wrapT\s*=", r"\.magFilter\s*=", r"\.minFilter\s*="]]),
        ],
        ["threejs", "textures", "materials", "react-three-fiber"],
        "medium",
    ),
    blueprint(
        "instanced-mesh-field",
        "Three.js InstancedMesh",
        "https://threejs.org/docs/api/en/objects/InstancedMesh",
        "Use InstancedMesh with deterministic matrices to render many repeated objects efficiently",
        [
            check("instanced_mesh", 150, regex_all=[r"<instancedMesh", r"\.setMatrixAt\s*\(", r"\.instanceMatrix\.needsUpdate\s*=\s*true"]),
            check("matrix_helper", 100, regex_all=[r"new\s+THREE\.Object3D\s*\(", r"\.updateMatrix\s*\("]),
        ],
        ["threejs", "instancing", "performance", "react-three-fiber"],
        "medium",
    ),
    blueprint(
        "instanced-color-selection",
        "Three.js webgl_instancing_raycast",
        "https://threejs.org/examples/webgl_instancing_raycast.html",
        "Render an instanced field with per-instance color data and a visible selected instance state",
        [
            check("instance_colors", 150, regex_all=[r"\.setColorAt\s*\(", r"\.instanceColor\.needsUpdate\s*=\s*true"]),
            check("selection_pattern", 100, regex_any=[[r"instanceId", r"selectedInstance", r"hoveredInstance"]]),
        ],
        ["threejs", "instancing", "interaction", "react-three-fiber"],
        "hard",
    ),
    blueprint(
        "vertex-color-geometry",
        "Three.js webgl_geometry_colors",
        "https://threejs.org/examples/webgl_geometry_colors.html",
        "Build geometry with vertex colors driven by a deterministic scalar-to-color palette",
        [
            check("vertex_colors", 150, regex_all=[r"\.setAttribute\s*\(\s*['\"]color['\"]", r"vertexColors"]),
            check("color_palette", 100, regex_any=[[r"new\s+THREE\.Color", r"\.setHSL\s*\(", r"\.lerp\s*\("]]),
        ],
        ["threejs", "buffergeometry", "materials", "react-three-fiber"],
        "hard",
    ),
    blueprint(
        "dashed-line-network",
        "Three.js LineDashedMaterial",
        "https://threejs.org/docs/pages/LineDashedMaterial.html",
        "Create a dashed line network with computed line distances and a readable 3D layout",
        [
            check("dashed_lines", 150, regex_all=[r"LineDashedMaterial|lineDashedMaterial", r"computeLineDistances\s*\("]),
            check("line_network", 100, regex_any=[[r"<line", r"LineSegments", r"new\s+THREE\.Line"]]),
        ],
        ["threejs", "lines", "materials", "react-three-fiber"],
        "medium",
    ),
    blueprint(
        "tube-curve-sculpture",
        "Three.js TubeGeometry",
        "https://threejs.org/docs/pages/TubeGeometry.html",
        "Use CatmullRomCurve3 and TubeGeometry to make a smooth routed 3D path sculpture",
        [
            check("tube_curve", 150, regex_all=[r"new\s+THREE\.CatmullRomCurve3\s*\(", r"TubeGeometry|tubeGeometry"]),
            check("memoized_geometry", 100, regex_all=[r"useMemo\s*\("]),
        ],
        ["threejs", "curves", "geometry", "react-three-fiber"],
        "medium",
    ),
    blueprint(
        "extruded-shape-badge",
        "Three.js ExtrudeGeometry",
        "https://threejs.org/docs/pages/ExtrudeGeometry.html",
        "Create an extruded bevelled shape from a custom THREE.Shape without loading fonts or assets",
        [
            check("extrude_shape", 150, regex_all=[r"new\s+THREE\.Shape\s*\(", r"ExtrudeGeometry|extrudeGeometry", r"bevel"]),
            check("shape_commands", 100, regex_any=[[r"\.moveTo\s*\(", r"\.lineTo\s*\(", r"\.quadraticCurveTo\s*\("]]),
        ],
        ["threejs", "geometry", "materials", "react-three-fiber"],
        "medium",
    ),
    blueprint(
        "lathe-profile-vase",
        "Three.js LatheGeometry",
        "https://threejs.org/docs/pages/LatheGeometry.html",
        "Create a lathed profile object from Vector2 control points with clear lighting and scale cues",
        [
            check("lathe_profile", 150, regex_all=[r"new\s+THREE\.Vector2\s*\(", r"LatheGeometry|latheGeometry"]),
            check("profile_points", 100, count_at_least=[{"pattern": r"new\s+THREE\.Vector2\s*\(", "count": 4}]),
        ],
        ["threejs", "geometry", "materials", "react-three-fiber"],
        "medium",
    ),
    blueprint(
        "animation-mixer-keyframes",
        "Three.js AnimationMixer",
        "https://threejs.org/docs/api/en/animation/AnimationMixer.html",
        "Drive object motion with AnimationMixer, AnimationClip, and keyframe tracks instead of ad-hoc state",
        [
            check("animation_mixer", 150, regex_all=[r"new\s+THREE\.AnimationMixer\s*\(", r"new\s+THREE\.AnimationClip\s*\(", r"\.clipAction\s*\("]),
            check("mixer_update", 100, regex_all=[r"useFrame\s*\(", r"\.update\s*\(\s*delta\s*\)"]),
        ],
        ["threejs", "animation", "react-three-fiber"],
        "hard",
    ),
    blueprint(
        "quaternion-orientation",
        "Three.js Quaternion",
        "https://threejs.org/docs/pages/Quaternion.html",
        "Animate orientation with Quaternion slerp toward visible target poses",
        [
            check("quaternion_slerp", 150, regex_all=[r"new\s+THREE\.Quaternion\s*\(", r"\.slerp\s*\("]),
            check("frame_orientation", 100, regex_all=[r"useFrame\s*\(", r"\.quaternion"]),
        ],
        ["threejs", "animation", "math", "react-three-fiber"],
        "medium",
    ),
    blueprint(
        "lod-detail-levels",
        "Three.js LOD",
        "https://threejs.org/docs/api/en/objects/LOD.html",
        "Assemble a distance-aware LOD object with three visible detail levels",
        [
            check("lod_object", 150, regex_all=[r"new\s+THREE\.LOD\s*\(", r"\.addLevel\s*\("]),
            check("three_levels", 100, count_at_least=[{"pattern": r"\.addLevel\s*\(", "count": 3}]),
        ],
        ["threejs", "performance", "camera", "react-three-fiber"],
        "hard",
    ),
    blueprint(
        "rect-area-lighting",
        "Three.js RectAreaLight",
        "https://threejs.org/docs/pages/RectAreaLight.html",
        "Build a product-style lighting setup around RectAreaLight panels and physical materials",
        [
            check("rect_area_light", 150, regex_any=[[r"<rectAreaLight", r"new\s+THREE\.RectAreaLight\s*\("]]),
            check("physical_material", 100, regex_any=[[r"meshPhysicalMaterial", r"MeshPhysicalMaterial"]]),
        ],
        ["threejs", "lighting", "materials", "react-three-fiber"],
        "medium",
    ),
    blueprint(
        "physical-transmission",
        "Three.js MeshPhysicalMaterial transmission",
        "https://threejs.org/examples/webgl_materials_physical_transmission.html",
        "Create a glass/transmission material scene with fallback environment cues and readable silhouettes",
        [
            check("transmission_material", 150, regex_all=[r"meshPhysicalMaterial|MeshPhysicalMaterial", r"transmission"]),
            check("optical_parameters", 100, regex_any=[[r"ior", r"thickness", r"roughness", r"clearcoat"]]),
        ],
        ["threejs", "materials", "lighting", "react-three-fiber"],
        "hard",
    ),
    blueprint(
        "shadow-stage",
        "Three.js shadow map example",
        "https://threejs.org/examples/webgl_shadowmap.html",
        "Compose a shadowed stage with explicit castShadow and receiveShadow ownership",
        [
            check("shadow_scene", 150, regex_all=[r"castShadow", r"receiveShadow"]),
            check("shadow_canvas", 100, regex_any=[[r"shadows:\s*true", r"<ContactShadows", r"<AccumulativeShadows"]]),
        ],
        ["threejs", "lighting", "shadows", "react-three-fiber"],
        "medium",
    ),
    blueprint(
        "r3f-pointer-selection",
        "React Three Fiber events",
        "https://r3f.docs.pmnd.rs/api/events",
        "Use R3F pointer events to highlight and label selectable 3D objects",
        [
            check("pointer_events", 150, regex_any=[[r"onPointerOver=", r"onPointerMove=", r"onClick="]]),
            check("react_state_selection", 100, regex_all=[r"useState\s*\("]),
        ],
        ["react-three-fiber", "interaction", "threejs"],
        "medium",
    ),
    blueprint(
        "voxel-grid-editor",
        "Three.js voxel painter example",
        "https://threejs.org/examples/webgl_interactive_voxelpainter.html",
        "Create a prefilled voxel editor scene with grid snapping concepts and R3F interaction handlers",
        [
            check("voxel_grid", 150, regex_all=[r"gridHelper|<gridHelper", r"onClick="]),
            check("voxel_instances", 100, regex_any=[[r"<instancedMesh", r"\.map\s*\("]]),
        ],
        ["threejs", "interaction", "editor", "react-three-fiber"],
        "hard",
    ),
    blueprint(
        "heightfield-marker",
        "Three.js terrain raycast example",
        "https://threejs.org/examples/webgl_geometry_terrain_raycast.html",
        "Generate a heightfield terrain and show a marker that demonstrates picking or probe placement",
        [
            check("heightfield_geometry", 150, regex_all=[r"planeGeometry|PlaneGeometry", r"position", r"\.needsUpdate\s*=\s*true"]),
            check("probe_marker", 100, regex_any=[[r"Raycaster", r"marker", r"probe"]], case_sensitive=False),
        ],
        ["threejs", "terrain", "interaction", "react-three-fiber"],
        "hard",
    ),
    blueprint(
        "decal-projection",
        "Three.js DecalGeometry",
        "https://threejs.org/examples/webgl_decals.html",
        "Project multiple decals onto a base mesh using DecalGeometry and deterministic placements",
        [
            check("decal_geometry", 150, regex_all=[r"DecalGeometry", r"three/addons/geometries/DecalGeometry"]),
            check("multiple_decals", 100, count_at_least=[{"pattern": r"DecalGeometry", "count": 2}]),
        ],
        ["threejs", "materials", "geometry", "react-three-fiber"],
        "hard",
    ),
    blueprint(
        "convex-hull-crystal",
        "Three.js ConvexGeometry",
        "https://threejs.org/docs/index.html?q=ConvexGeometry",
        "Generate a ConvexGeometry crystal from deterministic Vector3 points",
        [
            check("convex_geometry", 150, regex_all=[r"ConvexGeometry", r"three/addons/geometries/ConvexGeometry"]),
            check("point_cloud_source", 100, count_at_least=[{"pattern": r"new\s+THREE\.Vector3\s*\(", "count": 6}]),
        ],
        ["threejs", "geometry", "materials", "react-three-fiber"],
        "medium",
    ),
    blueprint(
        "mesh-surface-sampler",
        "Three.js MeshSurfaceSampler",
        "https://threejs.org/docs/index.html?q=MeshSurfaceSampler",
        "Sample points from a source mesh surface and render them as an inspectable particle shell",
        [
            check("surface_sampler", 150, regex_all=[r"MeshSurfaceSampler", r"three/addons/math/MeshSurfaceSampler"]),
            check("sample_points", 100, regex_all=[r"\.build\s*\(", r"\.sample\s*\("]),
        ],
        ["threejs", "points", "geometry", "react-three-fiber"],
        "hard",
    ),
    blueprint(
        "clipping-section",
        "Three.js clipping example",
        "https://threejs.org/examples/webgl_clipping.html",
        "Show an object cross-section using material clipping planes with visible reference geometry",
        [
            check("clipping_planes", 150, regex_all=[r"new\s+THREE\.Plane\s*\(", r"clippingPlanes"]),
            check("local_clipping", 100, regex_any=[[r"localClippingEnabled", r"clipIntersection", r"clipShadows"]]),
        ],
        ["threejs", "materials", "geometry", "react-three-fiber"],
        "hard",
    ),
    blueprint(
        "render-texture-portal",
        "Drei RenderTexture",
        "https://drei.docs.pmnd.rs/portals/render-texture",
        "Use Drei RenderTexture to place a live nested scene onto geometry",
        [
            check("render_texture", 150, regex_all=[DREI_IMPORTS, r"<RenderTexture"]),
            check("nested_camera", 100, regex_any=[[r"<PerspectiveCamera", r"PerspectiveCamera"]]),
        ],
        ["drei", "react-three-fiber", "render-targets", "threejs"],
        "hard",
    ),
    blueprint(
        "drei-environment-stage",
        "Drei Environment",
        "https://drei.docs.pmnd.rs/staging/environment",
        "Use Drei Environment or Stage to light an offline scene without network HDR files",
        [
            check("drei_environment", 150, regex_all=[DREI_IMPORTS, r"<(Environment|Stage)"]),
            check("offline_environment", 100, regex_none=[r"files=\{?['\"]https?://"], regex_any=[[r"preset=", r"background", r"environmentIntensity", r"<Stage"]]),
        ],
        ["drei", "lighting", "react-three-fiber", "threejs"],
        "medium",
    ),
    blueprint(
        "camera-controls-bounds",
        "Drei CameraControls",
        "https://drei.docs.pmnd.rs/controls/camera-controls",
        "Use Drei CameraControls or Bounds to frame a complex scene with constrained interaction",
        [
            check("camera_controls", 150, regex_all=[DREI_IMPORTS, r"<(CameraControls|Bounds)"]),
            check("control_constraints", 100, regex_any=[[r"minDistance", r"maxDistance", r"fit", r"makeDefault", r"target"]]),
        ],
        ["drei", "camera", "composition", "react-three-fiber"],
        "medium",
    ),
    blueprint(
        "html-annotations",
        "Drei Html",
        "https://drei.docs.pmnd.rs/misc/html",
        "Attach Drei Html annotations to 3D anchor points without hiding the canvas scene",
        [
            check("html_annotations", 150, regex_all=[DREI_IMPORTS, r"<Html"]),
            check("anchored_labels", 100, count_at_least=[{"pattern": r"<Html", "count": 2}]),
        ],
        ["drei", "annotations", "react-three-fiber", "threejs"],
        "medium",
    ),
    blueprint(
        "transform-pivot-controls",
        "Drei TransformControls",
        "https://drei.docs.pmnd.rs/gizmos/transform-controls",
        "Add a visible transform or pivot control around a selected object in an editor-like scene",
        [
            check("transform_controls", 150, regex_all=[DREI_IMPORTS, r"<(TransformControls|PivotControls)"]),
            check("selected_object", 100, regex_any=[[r"mode=", r"anchor=", r"activeAxes", r"selected"]]),
        ],
        ["drei", "editor", "interaction", "react-three-fiber"],
        "hard",
    ),
    blueprint(
        "drei-instances",
        "Drei Instances",
        "https://drei.docs.pmnd.rs/performances/instances",
        "Use Drei Instances/Instance to render a performant repeated object system",
        [
            check("drei_instances", 150, regex_all=[DREI_IMPORTS, r"<Instances", r"<Instance"]),
            check("many_instances", 100, count_at_least=[{"pattern": r"<Instance", "count": 4}]),
        ],
        ["drei", "instancing", "performance", "react-three-fiber"],
        "medium",
    ),
    blueprint(
        "reflector-material",
        "Drei MeshReflectorMaterial",
        "https://drei.docs.pmnd.rs/shaders/mesh-reflector-material",
        "Create a reflective floor or panel using MeshReflectorMaterial with visible reflected geometry",
        [
            check("reflector_material", 150, regex_all=[DREI_IMPORTS, r"<MeshReflectorMaterial"]),
            check("reflection_settings", 100, regex_any=[[r"blur=", r"resolution=", r"mixBlur=", r"mirror="]]),
        ],
        ["drei", "materials", "lighting", "react-three-fiber"],
        "hard",
    ),
    blueprint(
        "transmission-material-drei",
        "Drei MeshTransmissionMaterial",
        "https://drei.docs.pmnd.rs/shaders/mesh-transmission-material",
        "Use MeshTransmissionMaterial to build a glassy inspectable object with stable fallback lighting",
        [
            check("drei_transmission", 150, regex_all=[DREI_IMPORTS, r"<MeshTransmissionMaterial"]),
            check("transmission_settings", 100, regex_any=[[r"thickness=", r"roughness=", r"transmission=", r"ior="]]),
        ],
        ["drei", "materials", "react-three-fiber", "threejs"],
        "hard",
    ),
    blueprint(
        "contact-accumulative-shadows",
        "Drei ContactShadows",
        "https://drei.docs.pmnd.rs/staging/contact-shadows",
        "Use Drei ContactShadows or AccumulativeShadows to ground multiple objects in a product scene",
        [
            check("drei_shadows", 150, regex_all=[DREI_IMPORTS, r"<(ContactShadows|AccumulativeShadows)"]),
            check("shadow_settings", 100, regex_any=[[r"frames=", r"opacity=", r"scale=", r"blur="]]),
        ],
        ["drei", "shadows", "lighting", "react-three-fiber"],
        "medium",
    ),
    blueprint(
        "drei-text-labels",
        "Drei Text",
        "https://drei.docs.pmnd.rs/abstractions/text",
        "Use Drei Text or Text3D for readable in-scene labels tied to geometry",
        [
            check("drei_text", 150, regex_all=[DREI_IMPORTS, r"<Text(3D)?"]),
            check("text_layout", 100, regex_any=[[r"anchorX=", r"anchorY=", r"fontSize=", r"maxWidth="]]),
        ],
        ["drei", "text", "annotations", "react-three-fiber"],
        "medium",
    ),
    blueprint(
        "r3f-use-three-responsive",
        "React Three Fiber useThree",
        "https://r3f.docs.pmnd.rs/api/hooks",
        "Use useThree selectors to adapt object scale or layout to viewport dimensions",
        [
            check("use_three_selector", 150, regex_all=[R3F_IMPORTS, r"useThree\s*\(\s*\(?\s*state\s*=>"]),
            check("viewport_usage", 100, regex_any=[[r"viewport", r"size", r"camera"]]),
        ],
        ["react-three-fiber", "responsive", "camera", "threejs"],
        "medium",
    ),
    blueprint(
        "r3f-demand-rendering",
        "React Three Fiber scaling performance",
        "https://r3f.docs.pmnd.rs/advanced/scaling-performance",
        "Configure demand rendering and invalidate frames around controlled interaction or animation",
        [
            check("frameloop_demand", 150, regex_all=[r"frameloop:\s*['\"]demand['\"]"]),
            check("invalidate_usage", 100, regex_all=[r"useThree", r"invalidate\s*\("]),
        ],
        ["react-three-fiber", "performance", "camera", "threejs"],
        "hard",
        constraints=["Export solutionCanvasProps with frameloop set to demand and invalidate when the scene changes."],
    ),
    blueprint(
        "r3f-use-loader-data-url",
        "React Three Fiber useLoader",
        "https://r3f.docs.pmnd.rs/api/hooks",
        "Use useLoader with a generated data URL or inline-safe texture source and render a fallback object",
        [
            check("use_loader", 150, regex_all=[R3F_IMPORTS, r"useLoader\s*\("]),
            check("offline_loader_source", 100, regex_any=[[r"data:", r"TextureLoader"]], regex_none=[r"https?://"]),
        ],
        ["react-three-fiber", "assets", "textures", "threejs"],
        "hard",
    ),
    blueprint(
        "r3f-safe-frame-loop",
        "React Three Fiber useFrame",
        "https://r3f.docs.pmnd.rs/api/hooks",
        "Animate with useFrame using refs and reusable temporaries without setting React state per frame",
        [
            check("safe_use_frame", 150, regex_all=[R3F_IMPORTS, r"useFrame\s*\(", r"useRef\s*\("]),
            check("no_frame_set_state", 100, regex_none=[r"useFrame\s*\([^)]*set[A-Z]"]),
        ],
        ["react-three-fiber", "animation", "performance", "threejs"],
        "medium",
    ),
    blueprint(
        "performance-monitor",
        "React Three Fiber scaling performance",
        "https://r3f.docs.pmnd.rs/advanced/scaling-performance",
        "Use Drei PerformanceMonitor or R3F performance state to adapt visual quality",
        [
            check("performance_monitor", 150, regex_any=[[r"PerformanceMonitor", r"usePerformanceMonitor", r"performance\.current"]]),
            check("quality_adaptation", 100, regex_any=[[r"setDpr", r"dpr", r"current", r"onDecline", r"onFallback"]]),
        ],
        ["react-three-fiber", "drei", "performance", "threejs"],
        "hard",
    ),
    blueprint(
        "webgpu-capability-fallback",
        "Three.js WebGPURenderer manual",
        "https://threejs.org/manual/en/webgpurenderer",
        "Detect WebGPU capability safely and render a clear WebGL fallback scene in the current harness",
        [
            check("webgpu_guard", 150, regex_all=[r"typeof\s+navigator", r"navigator\.gpu"]),
            check("fallback_branch", 150, regex_any=[[r"fallback", r"webgl", r"WebGL"]], case_sensitive=False),
        ],
        ["webgpu", "threejs", "react-three-fiber"],
        "hard",
        constraints=["Do not instantiate WebGPURenderer in this WebGL harness; show capability state through visible fallback geometry or labels."],
    ),
    blueprint(
        "webgpu-compute-boids-concept",
        "WebGPU samples computeBoids",
        "https://webgpu.github.io/webgpu-samples/?sample=computeBoids",
        "Adapt the compute-boids idea into a WebGL-safe instanced or points simulation with WebGPU guard metadata",
        [
            check("boids_simulation", 150, regex_any=[[r"boid", r"velocity", r"neighbor", r"flock"]], case_sensitive=False),
            check("webgpu_guarded_fallback", 150, regex_all=[r"navigator\.gpu", r"useFrame\s*\("]),
        ],
        ["webgpu", "simulation", "animation", "react-three-fiber"],
        "hard",
    ),
    blueprint(
        "webgpu-game-of-life-concept",
        "WebGPU samples gameOfLife",
        "https://webgpu.github.io/webgpu-samples/?sample=gameOfLife",
        "Adapt Game of Life compute concepts into a visible DataTexture or instanced-grid fallback",
        [
            check("cellular_grid", 150, regex_any=[[r"Game of Life", r"cell", r"neighbor", r"alive"]], case_sensitive=False),
            check("grid_texture_or_instances", 150, regex_any=[[r"DataTexture", r"<instancedMesh", r"setMatrixAt"]]),
        ],
        ["webgpu", "simulation", "textures", "react-three-fiber"],
        "hard",
    ),
    blueprint(
        "webgpu-textured-cube-concept",
        "WebGPU samples texturedCube",
        "https://webgpu.github.io/webgpu-samples/?sample=texturedCube",
        "Adapt textured-cube sampling concepts into an offline procedural texture scene",
        [
            check("texture_sampling_concept", 150, regex_any=[[r"CanvasTexture", r"DataTexture", r"TextureLoader"]]),
            check("cube_texture_scene", 100, regex_any=[[r"boxGeometry", r"BoxGeometry"]]),
        ],
        ["webgpu", "textures", "threejs", "react-three-fiber"],
        "medium",
    ),
    blueprint(
        "webgpu-points-concept",
        "WebGPU samples points",
        "https://webgpu.github.io/webgpu-samples/?sample=points",
        "Create a points visualization with distance-based sizing concepts and WebGPU capability fallback",
        [
            check("points_visualization", 150, regex_all=[r"<points", r"pointsMaterial|PointsMaterial"]),
            check("webgpu_points_guard", 100, regex_all=[r"navigator\.gpu"]),
        ],
        ["webgpu", "points", "threejs", "react-three-fiber"],
        "medium",
    ),
    blueprint(
        "tsl-safe-import-fallback",
        "Three.js TSL specification",
        "https://threejs.org/docs/TSL.html",
        "Reference TSL imports and node-material concepts while rendering a safe MeshStandardMaterial fallback",
        [
            check("tsl_imports", 150, regex_any=[[r"from\s+['\"]three/tsl['\"]", r"from\s+['\"]three/webgpu['\"]"]]),
            check("safe_fallback_material", 150, regex_all=[r"MeshStandardMaterial|meshStandardMaterial", r"fallback"], case_sensitive=False),
            check("no_node_material_runtime", 100, regex_none=[r"new\s+Mesh(Standard|Basic|Physical)NodeMaterial\s*\("]),
        ],
        ["tsl", "webgpu", "materials", "threejs", "react-three-fiber"],
        "hard",
        constraints=["Because the current harness renders with WebGL, do not mount a NodeMaterial unless it is safely guarded away from runtime."],
    ),
    blueprint(
        "tsl-procedural-terrain-concept",
        "Three.js webgpu_tsl_procedural_terrain",
        "https://threejs.org/examples/webgpu_tsl_procedural_terrain.html",
        "Build a WebGL-safe procedural terrain that documents a TSL noise/material upgrade path",
        [
            check("tsl_reference", 150, regex_any=[[r"three/tsl", r"mx_noise", r"positionLocal", r"Fn\s*\("]]),
            check("terrain_fallback", 150, regex_all=[r"planeGeometry|PlaneGeometry", r"computeVertexNormals|needsUpdate"]),
        ],
        ["tsl", "webgpu", "terrain", "react-three-fiber"],
        "hard",
    ),
    blueprint(
        "tsl-wood-material-concept",
        "Three.js webgpu_tsl_wood",
        "https://threejs.org/examples/webgpu_tsl_wood.html",
        "Create a wood/ring procedural material fallback and include explicit TSL node-building intent",
        [
            check("wood_pattern", 150, regex_any=[[r"wood", r"ring", r"grain"]], case_sensitive=False),
            check("tsl_material_intent", 150, regex_any=[[r"three/tsl", r"color\s*\(", r"positionLocal", r"uniform\s*\("]]),
        ],
        ["tsl", "webgpu", "materials", "react-three-fiber"],
        "medium",
    ),
    blueprint(
        "webgpu-shadowmapping-concept",
        "WebGPU samples shadowMapping",
        "https://webgpu.github.io/webgpu-samples/?sample=shadowMapping",
        "Adapt WebGPU shadow mapping concepts into a WebGL-safe shadow scene with explicit light/caster/receiver roles",
        [
            check("shadow_roles", 150, regex_all=[r"castShadow", r"receiveShadow", r"directionalLight|spotLight"]),
            check("webgpu_shadow_reference", 100, regex_all=[r"navigator\.gpu"]),
        ],
        ["webgpu", "shadows", "lighting", "react-three-fiber"],
        "medium",
    ),
    blueprint(
        "loader-fallback-architecture",
        "React Three Fiber loading models",
        "https://r3f.docs.pmnd.rs/tutorials/loading-models",
        "Demonstrate loader architecture with Suspense-style fallback while keeping all visible assets procedural/offline",
        [
            check("suspense_loader_pattern", 150, regex_any=[[r"<Suspense", r"useLoader\s*\(", r"useTexture", r"useGLTF"]]),
            check("procedural_fallback", 100, regex_any=[[r"fallback", r"Fallback", r"placeholder"]]),
        ],
        ["react-three-fiber", "assets", "loaders", "threejs"],
        "hard",
    ),
]


def task_from_blueprint(bp: Blueprint, split: str, index: int, scenario: str) -> dict[str, Any]:
    semantic_names = [item["name"] for item in bp.semantic_checks]
    semantic_points = sum(int(item.get("points", 100)) for item in bp.semantic_checks)
    source_lines = "; ".join(f"{ref['label']} ({ref['url']})" for ref in bp.source_refs)
    prompt = (
        f"{scenario}\n\n"
        f"Ground the implementation in: {source_lines}.\n"
        f"Build it as a production-quality React Three Fiber scene, not a toy demo. "
        f"The result should be clear from a 1280x720 desktop screenshot."
    )
    return {
        "schema_version": 2,
        "id": f"{split}-{bp.slug}-{index:03d}",
        "split": split,
        "kind": bp.kind,
        "prompt": prompt,
        "constraints": bp.constraints,
        "topics": bp.topics,
        "difficulty": bp.difficulty,
        "allowed_file": ALLOWED_FILE,
        "source_refs": bp.source_refs,
        "checks": [*BASE_CHECKS, *semantic_names],
        "semantic_checks": bp.semantic_checks,
        "required_checks": [*BASE_CHECKS, *semantic_names],
        "score_threshold": BASE_POINTS + semantic_points,
        "max_solution_chars": bp.max_chars,
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True) + "\n")


def main() -> None:
    if len(BLUEPRINTS) != 50:
        raise RuntimeError(f"Expected 50 blueprints, found {len(BLUEPRINTS)}")

    train_rows: list[dict[str, Any]] = []
    train_index = 1
    for bp in BLUEPRINTS:
        if len(bp.train_scenarios) != 6:
            raise RuntimeError(f"{bp.slug}: expected 6 train scenarios")
        for scenario in bp.train_scenarios:
            train_rows.append(task_from_blueprint(bp, "train", train_index, scenario))
            train_index += 1

    eval_rows = [
        task_from_blueprint(bp, "eval", index, bp.eval_scenario)
        for index, bp in enumerate(BLUEPRINTS, start=1)
    ]

    write_jsonl(TASKS_DIR / "train_tasks.jsonl", train_rows)
    write_jsonl(TASKS_DIR / "eval_tasks.jsonl", eval_rows)
    print(json.dumps({"train": len(train_rows), "eval": len(eval_rows)}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

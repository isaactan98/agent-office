// 3D office view (three.js) for components/Office.vue.
// Draws an OfficeState from utils/officeState.ts: it reads the state, never
// changes it. All behaviour (who walks where, who is working) stays in the
// reducer; this file only turns places and statuses into a scene.
//
// Look: a dark office at night seen from above at an angle, glass outer
// walls, a glass meeting room, a lounge, back-to-back desk clusters, warm
// lamps and glowing screens, small cube-headed robots. Everything is built
// from primitives and canvas textures (no model or image files).
import * as THREE from 'three'
import { CSS2DObject, CSS2DRenderer } from 'three/examples/jsm/renderers/CSS2DRenderer.js'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js'
import { DOOR, activeBubble, characterStatus, showsAlert, walkProgress } from './officeState'
import type { Character, CharacterStatus, OfficeState } from './officeState'

// ---- Layout (world units, y up, floor at y = 0) ----
const FLOOR_X = 10 // floor spans -FLOOR_X..FLOOR_X
const FLOOR_Z = 6
const WALL_H = 2.7
const CORRIDOR_Z = 0 // the main walkway, from the door across the room
const DOOR_W = 1.6
const DOOR_POINT = { x: -FLOOR_X + 0.6, z: CORRIDOR_Z }

interface Point { x: number, z: number }

// facing: the direction a seated character looks (radians, 0 = +z).
const BACK = Math.PI // looks at the back wall (-z); its screens face the camera
const FRONT = 0 // looks towards the camera (+z)
interface DeskSpot { x: number, z: number, facing: number, width: number, monitors: number, aisleX?: number }
const CHAIR_GAP = 1.25 // desk centre → chair centre
// Desk cluster in the front half: a row facing the camera (north) and a row
// facing the back wall (south), back to back with a divider.
const NORTH_Z = 2.85
const SOUTH_Z = 3.75
const AISLE_L = -4.1
const AISLE_R = 4.1
const DESKS: Record<string, DeskSpot> = {
  'desk:orchestrator': { x: 6.2, z: -3.7, facing: BACK, width: 2.7, monitors: 3 },
  'desk:writer': { x: -2.2, z: SOUTH_Z, facing: BACK, width: 2.0, monitors: 2, aisleX: AISLE_L },
  'desk:reviewer': { x: 2.2, z: SOUTH_Z, facing: BACK, width: 2.0, monitors: 2, aisleX: AISLE_R },
  'spare:1': { x: -2.2, z: NORTH_Z, facing: FRONT, width: 2.0, monitors: 2 },
  'spare:2': { x: 0, z: NORTH_Z, facing: FRONT, width: 2.0, monitors: 2 },
  'spare:3': { x: 2.2, z: NORTH_Z, facing: FRONT, width: 2.0, monitors: 2 }
}
// A desk nobody is assigned to (keeps the cluster symmetrical).
const EMPTY_DESK: DeskSpot = { x: 0, z: SOUTH_Z, facing: BACK, width: 2.0, monitors: 2 }

// Glass meeting room, back left. Seats 1–3 face the table from the corridor
// side, 4 and 5 sit at the ends, 6–8 on the far side (reached along the left
// wall so nobody walks through the table).
const MEET = { x: -7.3, z: -3.8, w: 3.0, d: 1.3, wallX: -4.5, frontZ: -1.4 }
const MEET_SEATS: Array<{ x: number, z: number, facing: number, via?: Point[] }> = [
  { x: -8.3, z: -2.6, facing: BACK },
  { x: -7.3, z: -2.6, facing: BACK },
  { x: -6.3, z: -2.6, facing: BACK },
  { x: -9.35, z: MEET.z, facing: Math.PI / 2 },
  { x: -5.25, z: MEET.z, facing: -Math.PI / 2 },
  { x: -8.3, z: -5.0, facing: FRONT, via: [{ x: -9.7, z: -5.0 }] },
  { x: -7.3, z: -5.0, facing: FRONT, via: [{ x: -9.7, z: -5.0 }] },
  { x: -6.3, z: -5.0, facing: FRONT, via: [{ x: -9.7, z: -5.0 }] }
]

// Robot colours: lighter versions of the feed's agent tag colours (app.vue).
const COLOURS: Record<string, string> = { orchestrator: '#6b9cff', writer: '#b18cff', reviewer: '#ff9a5c' }
const OTHER_COLOUR = '#e3e7ee'
const ROBOT_SCALE = 1.25

// Where a character sits for a place, which way it faces, and the waypoints
// between the corridor and the seat.
interface Spot { x: number, z: number, facing: number, via: Point[] }

function chairPoint(desk: DeskSpot): Point {
  // The chair is on the side the sitter looks away from.
  return { x: desk.x - Math.sin(desk.facing) * CHAIR_GAP, z: desk.z - Math.cos(desk.facing) * CHAIR_GAP }
}

function spotFor(place: string): Spot {
  if (place === DOOR) return { ...DOOR_POINT, facing: -Math.PI / 2, via: [] }
  const desk = DESKS[place]
  if (desk) {
    const chair = chairPoint(desk)
    return { ...chair, facing: desk.facing, via: desk.aisleX === undefined ? [] : [{ x: desk.aisleX, z: chair.z }] }
  }
  const n = Number(place.split(':')[1]) || 1
  const seat = MEET_SEATS[(n - 1) % MEET_SEATS.length]!
  return { x: seat.x, z: seat.z, facing: seat.facing, via: seat.via ?? [] }
}

// Points from the corridor to the place (inclusive).
function approach(place: string): Point[] {
  const spot = spotFor(place)
  const first = spot.via[0] ?? spot
  return [{ x: first.x, z: CORRIDOR_Z }, ...spot.via, { x: spot.x, z: spot.z }]
}

function pointAlong(path: Point[], progress: number): Point {
  const lengths = path.slice(1).map((p, i) => Math.hypot(p.x - path[i]!.x, p.z - path[i]!.z))
  let left = progress * lengths.reduce((a, b) => a + b, 0)
  for (let i = 0; i < lengths.length; i++) {
    const len = lengths[i]!
    if (left <= len && len > 0) {
      const a = path[i]!
      const b = path[i + 1]!
      return { x: a.x + (b.x - a.x) * (left / len), z: a.z + (b.z - a.z) * (left / len) }
    }
    left -= len
  }
  return path[path.length - 1]!
}

function characterPoint(state: OfficeState, c: Character): Point {
  if (!c.walk) {
    const spot = spotFor(c.desk)
    return { x: spot.x, z: spot.z }
  }
  // Back out to the corridor, along it, then in to the target.
  const path = [...approach(c.walk.from).reverse(), ...approach(c.walk.to)]
  return pointAlong(path, walkProgress(state, c.name))
}

// ---- Small builders ----
function mat(color: THREE.ColorRepresentation, opts: THREE.MeshStandardMaterialParameters = {}) {
  return new THREE.MeshStandardMaterial({ color, roughness: 0.75, metalness: 0, ...opts })
}

function box(w: number, h: number, d: number, material: THREE.Material, x = 0, y = 0, z = 0, rounded = 0) {
  const geometry = rounded > 0 ? new RoundedBoxGeometry(w, h, d, 3, rounded) : new THREE.BoxGeometry(w, h, d)
  const mesh = new THREE.Mesh(geometry, material)
  mesh.position.set(x, y, z)
  mesh.castShadow = true
  mesh.receiveShadow = true
  return mesh
}

function cylinder(rTop: number, rBottom: number, h: number, material: THREE.Material, x = 0, y = 0, z = 0, segments = 20) {
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(rTop, rBottom, h, segments), material)
  mesh.position.set(x, y, z)
  mesh.castShadow = true
  mesh.receiveShadow = true
  return mesh
}

function flat(w: number, d: number, material: THREE.Material, x: number, z: number, y = 0.006) {
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, d), material)
  mesh.rotation.x = -Math.PI / 2
  mesh.position.set(x, y, z)
  mesh.receiveShadow = true
  return mesh
}

function canvasTexture(w: number, h: number, paint: (ctx: CanvasRenderingContext2D) => void) {
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  paint(canvas.getContext('2d')!)
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  texture.anisotropy = 4
  return texture
}

// Seeded random so the decoration looks the same on every load.
function seeded(seed: number) {
  return () => {
    seed = (seed * 16807) % 2147483647
    return (seed - 1) / 2147483646
  }
}

// ---- Textures ----
function concreteTexture() {
  const rand = seeded(5)
  const texture = canvasTexture(512, 512, (ctx) => {
    ctx.fillStyle = '#5b5e6c'
    ctx.fillRect(0, 0, 512, 512)
    for (let i = 0; i < 4000; i++) {
      const l = 30 + rand() * 14
      ctx.fillStyle = `hsla(230, 8%, ${l}%, 0.25)`
      ctx.fillRect(rand() * 512, rand() * 512, 2, 2)
    }
    // Large tiles.
    ctx.strokeStyle = 'rgba(0, 0, 0, 0.25)'
    ctx.lineWidth = 2
    for (let i = 0; i <= 512; i += 128) {
      ctx.beginPath(); ctx.moveTo(i, 0); ctx.lineTo(i, 512); ctx.stroke()
      ctx.beginPath(); ctx.moveTo(0, i); ctx.lineTo(512, i); ctx.stroke()
    }
  })
  texture.wrapS = THREE.RepeatWrapping
  texture.wrapT = THREE.RepeatWrapping
  texture.repeat.set(5, 3)
  return texture
}

function woodTexture() {
  const rand = seeded(7)
  const texture = canvasTexture(256, 256, (ctx) => {
    const plankH = 32
    for (let row = 0; row < 256 / plankH; row++) {
      let x = row % 2 ? -60 : 0
      while (x < 256) {
        const len = 80 + rand() * 70
        ctx.fillStyle = `hsl(26, 30%, ${30 + rand() * 6}%)`
        ctx.fillRect(x, row * plankH, len, plankH)
        ctx.fillStyle = 'rgba(0, 0, 0, 0.3)'
        ctx.fillRect(x, row * plankH, 1, plankH)
        x += len
      }
      ctx.fillStyle = 'rgba(0, 0, 0, 0.3)'
      ctx.fillRect(0, row * plankH, 256, 1)
    }
  })
  texture.wrapS = THREE.RepeatWrapping
  texture.wrapT = THREE.RepeatWrapping
  texture.repeat.set(2, 2)
  return texture
}

function cityTexture(seed: number) {
  const rand = seeded(seed)
  return canvasTexture(512, 256, (ctx) => {
    const sky = ctx.createLinearGradient(0, 0, 0, 256)
    sky.addColorStop(0, '#060b22')
    sky.addColorStop(0.7, '#12245a')
    sky.addColorStop(1, '#2a4a9a')
    ctx.fillStyle = sky
    ctx.fillRect(0, 0, 512, 256)
    for (let layer = 0; layer < 2; layer++) {
      let x = -10
      while (x < 512) {
        const w = 24 + rand() * 46
        const h = (layer ? 90 : 140) + rand() * 100
        ctx.fillStyle = layer ? '#0b1430' : '#14204a'
        ctx.fillRect(x, 256 - h, w, h)
        for (let wy = 256 - h + 8; wy < 252; wy += 9) {
          for (let wx = x + 5; wx < x + w - 5; wx += 7) {
            if (rand() < (layer ? 0.3 : 0.15)) {
              ctx.fillStyle = rand() < 0.55 ? '#7fb6ff' : '#ffd27a'
              ctx.fillRect(wx, wy, 3, 4)
            }
          }
        }
        x += w + 3
      }
    }
  })
}

// Lines of "code" that scroll on a working monitor.
function codeTexture() {
  const rand = seeded(42)
  const colours = ['#7ee2a8', '#79c0ff', '#d2a8ff', '#ffa657', '#c9d1d9', '#79c0ff']
  const texture = canvasTexture(256, 256, (ctx) => {
    ctx.fillStyle = '#0a1426'
    ctx.fillRect(0, 0, 256, 256)
    for (let y = 8; y < 256; y += 12) {
      let x = 12 + Math.floor(rand() * 4) * 14
      const parts = 1 + Math.floor(rand() * 4)
      for (let p = 0; p < parts && x < 230; p++) {
        const w = 14 + rand() * 50
        ctx.fillStyle = colours[Math.floor(rand() * colours.length)]!
        ctx.fillRect(x, y, Math.min(w, 244 - x), 5)
        x += w + 8
      }
    }
  })
  texture.wrapT = THREE.RepeatWrapping
  return texture
}

function artTexture(seed: number) {
  const rand = seeded(seed)
  return canvasTexture(128, 96, (ctx) => {
    ctx.fillStyle = '#d8cfbf'
    ctx.fillRect(0, 0, 128, 96)
    const tones = ['#5a7d6a', '#c58b5a', '#3e4a6b', '#e2b96f', '#8e5a4b']
    for (let i = 0; i < 4; i++) {
      ctx.fillStyle = tones[Math.floor(rand() * tones.length)]!
      ctx.beginPath()
      ctx.arc(20 + rand() * 88, 20 + rand() * 56, 10 + rand() * 22, 0, Math.PI * 2)
      ctx.fill()
    }
  })
}

// ---- Static scenery ----
type Track = (t: THREE.Texture) => void

function chair(x: number, z: number, facing: number, colour = '#2b2d37') {
  const g = new THREE.Group()
  g.position.set(x, 0, z)
  g.rotation.y = facing
  const seat = mat(colour, { roughness: 0.6 })
  const metal = mat('#55586a', { metalness: 0.6, roughness: 0.4 })
  g.add(box(0.62, 0.1, 0.58, seat, 0, 0.42, 0, 0.04))
  g.add(box(0.58, 0.55, 0.08, seat, 0, 0.76, -0.3, 0.04)) // back, behind the sitter
  g.add(cylinder(0.035, 0.035, 0.36, metal, 0, 0.2, 0))
  g.add(cylinder(0.27, 0.27, 0.035, metal, 0, 0.03, 0, 5))
  return g
}

function plant(x: number, z: number, scale: number) {
  const g = new THREE.Group()
  g.position.set(x, 0, z)
  g.scale.setScalar(scale)
  g.add(cylinder(0.24, 0.19, 0.48, mat('#2a2b33', { roughness: 0.5 }), 0, 0.24, 0))
  const leaf = mat('#3d8a55', { flatShading: true })
  const leafDark = mat('#2c6a41', { flatShading: true })
  const rand = seeded(Math.round((x + 20) * 100 + z * 10))
  for (let i = 0; i < 6; i++) {
    const m = new THREE.Mesh(new THREE.IcosahedronGeometry(0.2 + rand() * 0.14, 0), i % 2 ? leaf : leafDark)
    m.position.set((rand() - 0.5) * 0.4, 0.72 + i * 0.13 + rand() * 0.1, (rand() - 0.5) * 0.4)
    m.castShadow = true
    g.add(m)
  }
  return g
}

// A glass wall from (x1, z1) to (x2, z2) with dark mullions and rails.
function glassWall(x1: number, z1: number, x2: number, z2: number, h: number, glass: THREE.Material, frame: THREE.Material) {
  const g = new THREE.Group()
  const len = Math.hypot(x2 - x1, z2 - z1)
  g.position.set((x1 + x2) / 2, 0, (z1 + z2) / 2)
  g.rotation.y = -Math.atan2(z2 - z1, x2 - x1)
  const pane = new THREE.Mesh(new THREE.PlaneGeometry(len, h), glass)
  pane.position.y = h / 2
  pane.renderOrder = 1
  g.add(pane)
  const rail = (y: number, t: number) => {
    const m = box(len, t, 0.07, frame, 0, y, 0)
    m.castShadow = false
    g.add(m)
  }
  rail(0.04, 0.08)
  rail(h, 0.08)
  const posts = Math.max(1, Math.round(len / 1.9))
  for (let i = 0; i <= posts; i++) {
    const m = box(0.06, h, 0.07, frame, -len / 2 + (len * i) / posts, h / 2, 0)
    m.castShadow = false
    g.add(m)
  }
  return g
}

function warmLight(scene: THREE.Scene, x: number, y: number, z: number, intensity: number, distance: number, colour = '#ffb46b') {
  const light = new THREE.PointLight(colour, intensity, distance, 1.6)
  light.position.set(x, y, z)
  scene.add(light)
}

// The back and left walls (and what hangs on them) are in their own groups so
// they can be hidden when the camera turns round behind them.
function buildRoom(scene: THREE.Scene, track: Track) {
  const room = new THREE.Group()
  const backWall = new THREE.Group()
  const leftWall = new THREE.Group()
  room.add(backWall, leftWall)
  scene.add(room)

  // Floor slab with dark edges, like a cut-out model.
  const concrete = concreteTexture()
  track(concrete)
  const edge = mat('#17181f')
  const floor = new THREE.Mesh(new THREE.BoxGeometry(FLOOR_X * 2, 0.4, FLOOR_Z * 2), [
    edge, edge, mat('#ffffff', { map: concrete, roughness: 0.85 }), edge, edge, edge
  ])
  floor.position.y = -0.2
  floor.receiveShadow = true
  room.add(floor)

  // Walls: dark, back and left only; glass on the front and right.
  const wallMat = mat('#41444f', { roughness: 0.9 })
  const wallTop = mat('#1a1b22')
  backWall.add(box(FLOOR_X * 2 + 0.3, WALL_H, 0.3, wallMat, 0, WALL_H / 2, -FLOOR_Z - 0.15))
  backWall.add(box(FLOOR_X * 2 + 0.3, 0.06, 0.32, wallTop, 0, WALL_H + 0.03, -FLOOR_Z - 0.15))
  const leftBack = CORRIDOR_Z - DOOR_W / 2 + FLOOR_Z
  const leftFront = FLOOR_Z - (CORRIDOR_Z + DOOR_W / 2)
  leftWall.add(box(0.3, WALL_H, leftBack, wallMat, -FLOOR_X - 0.15, WALL_H / 2, -FLOOR_Z + leftBack / 2))
  leftWall.add(box(0.3, WALL_H, leftFront, wallMat, -FLOOR_X - 0.15, WALL_H / 2, FLOOR_Z - leftFront / 2))
  leftWall.add(box(0.3, WALL_H - 2.2, DOOR_W, wallMat, -FLOOR_X - 0.15, 2.2 + (WALL_H - 2.2) / 2, CORRIDOR_Z))
  leftWall.add(box(0.32, 0.06, FLOOR_Z * 2 + 0.3, wallTop, -FLOOR_X - 0.15, WALL_H + 0.03, 0))

  const glass = new THREE.MeshStandardMaterial({
    color: '#9cc4ff', transparent: true, opacity: 0.09, roughness: 0.05, metalness: 0.1,
    depthWrite: false, side: THREE.DoubleSide
  })
  const frame = mat('#14151b', { roughness: 0.4, metalness: 0.5 })
  room.add(glassWall(-FLOOR_X, FLOOR_Z, FLOOR_X, FLOOR_Z, WALL_H, glass, frame))
  room.add(glassWall(FLOOR_X, -FLOOR_Z, FLOOR_X, FLOOR_Z, WALL_H, glass, frame))

  // Door: frame, open leaf, small green sign.
  const doorFrame = mat('#5a4636')
  leftWall.add(box(0.36, 2.2, 0.08, doorFrame, -FLOOR_X - 0.1, 1.1, CORRIDOR_Z - DOOR_W / 2 - 0.04))
  leftWall.add(box(0.36, 2.2, 0.08, doorFrame, -FLOOR_X - 0.1, 1.1, CORRIDOR_Z + DOOR_W / 2 + 0.04))
  leftWall.add(box(0.36, 0.08, DOOR_W + 0.16, doorFrame, -FLOOR_X - 0.1, 2.2, CORRIDOR_Z))
  const hinge = new THREE.Group()
  hinge.position.set(-FLOOR_X + 0.05, 0, CORRIDOR_Z - DOOR_W / 2)
  hinge.rotation.y = -1.1
  hinge.add(box(0.06, 2.1, DOOR_W - 0.05, mat('#7a5a40'), 0, 1.05, (DOOR_W - 0.05) / 2))
  leftWall.add(hinge)
  leftWall.add(box(0.04, 0.18, 0.5, mat('#1f8f45', { emissive: '#3fdc6a', emissiveIntensity: 2 }), -FLOOR_X + 0.02, 2.45, CORRIDOR_Z))

  // Windows: night city behind the orchestrator's desk.
  const winFrame = mat('#101117', { metalness: 0.4, roughness: 0.5 })
  for (const [i, x] of [4.6, 7.8].entries()) {
    const tex = cityTexture(11 + i * 7)
    track(tex)
    const pane = new THREE.Mesh(new THREE.PlaneGeometry(3.0, 1.9), new THREE.MeshBasicMaterial({ map: tex, toneMapped: false, color: '#b8c8ff' }))
    pane.position.set(x, 1.5, -FLOOR_Z + 0.01)
    backWall.add(pane)
    backWall.add(box(3.1, 0.07, 0.1, winFrame, x, 2.47, -FLOOR_Z + 0.04))
    backWall.add(box(3.1, 0.07, 0.14, winFrame, x, 0.53, -FLOOR_Z + 0.06))
    for (const dx of [-1.52, 0, 1.52]) backWall.add(box(0.05, 1.98, 0.08, winFrame, x + dx, 1.5, -FLOOR_Z + 0.04))
  }
  // Cool light from the windows.
  warmLight(scene, 6.2, 1.8, -5.2, 10, 7, '#6f9dff')

  // Meeting room: wood floor, glass wall, table, chairs, art, warm lamp.
  const wood = woodTexture()
  track(wood)
  const meetW = MEET.wallX + FLOOR_X
  const meetD = MEET.frontZ + FLOOR_Z
  room.add(flat(meetW, meetD, mat('#ffffff', { map: wood, roughness: 0.6 }), -FLOOR_X + meetW / 2, -FLOOR_Z + meetD / 2))
  room.add(glassWall(MEET.wallX, -FLOOR_Z, MEET.wallX, MEET.frontZ, WALL_H, glass, frame))
  room.add(glassWall(MEET.wallX, MEET.frontZ, MEET.wallX - 0.9, MEET.frontZ, WALL_H, glass, frame))
  const tableTop = mat('#6b4a32', { roughness: 0.45 })
  const darkMetal = mat('#22232b', { metalness: 0.5, roughness: 0.4 })
  room.add(box(MEET.w, 0.07, MEET.d, tableTop, MEET.x, 0.76, MEET.z, 0.03))
  for (const dx of [-1, 1]) room.add(box(0.08, 0.72, MEET.d - 0.3, darkMetal, MEET.x + dx * (MEET.w / 2 - 0.3), 0.37, MEET.z))
  for (const seat of MEET_SEATS) room.add(chair(seat.x, seat.z, seat.facing, '#2a2b34'))
  const art = artTexture(9)
  track(art)
  backWall.add(box(1.5, 1.0, 0.05, mat('#14151b'), MEET.x, 1.65, -FLOOR_Z + 0.03))
  const artMesh = new THREE.Mesh(new THREE.PlaneGeometry(1.38, 0.88), mat('#ffffff', { map: art }))
  artMesh.position.set(MEET.x, 1.65, -FLOOR_Z + 0.06)
  backWall.add(artMesh)
  room.add(plant(-9.5, -5.5, 1.1))
  backWall.add(box(0.5, 0.1, 0.16, mat('#ffcf8a', { emissive: '#ffb46b', emissiveIntensity: 2.5 }), MEET.x - 1.4, 2.2, -FLOOR_Z + 0.09))
  backWall.add(box(0.5, 0.1, 0.16, mat('#ffcf8a', { emissive: '#ffb46b', emissiveIntensity: 2.5 }), MEET.x + 1.4, 2.2, -FLOOR_Z + 0.09))
  warmLight(scene, MEET.x, 2.3, MEET.z, 16, 7)

  // Lounge: rug, green sofa, coffee table, floor lamp, bookshelf, art.
  room.add(flat(3.6, 2.4, mat('#5e5347', { roughness: 1 }), -1.2, -4.5, 0.008))
  const sofa = new THREE.Group()
  sofa.position.set(-1.2, 0, -5.35)
  const green = mat('#3f6b4a', { roughness: 0.9 })
  sofa.add(box(2.6, 0.42, 0.9, green, 0, 0.21, 0, 0.08))
  sofa.add(box(2.6, 0.55, 0.25, green, 0, 0.6, -0.33, 0.08))
  for (const sx of [-1, 1]) sofa.add(box(0.25, 0.6, 0.9, green, sx * 1.18, 0.4, 0, 0.08))
  for (const sx of [-0.6, 0.6]) sofa.add(box(1.05, 0.14, 0.62, mat('#4c7d58', { roughness: 0.9 }), sx, 0.48, 0.08, 0.06))
  room.add(sofa)
  room.add(cylinder(0.5, 0.5, 0.06, tableTop, -1.2, 0.42, -4.1, 32))
  room.add(cylinder(0.05, 0.05, 0.4, darkMetal, -1.2, 0.2, -4.1))
  room.add(cylinder(0.04, 0.04, 0.12, mat('#e8e2d6'), -1.0, 0.51, -4.0))
  const lamp = new THREE.Group()
  lamp.position.set(0.75, 0, -5.4)
  lamp.add(cylinder(0.18, 0.2, 0.04, darkMetal, 0, 0.02, 0))
  lamp.add(cylinder(0.02, 0.02, 1.5, darkMetal, 0, 0.77, 0))
  lamp.add(cylinder(0.16, 0.24, 0.3, mat('#ffe2b0', { emissive: '#ffb46b', emissiveIntensity: 1.8, side: THREE.DoubleSide }), 0, 1.6, 0, 24))
  room.add(lamp)
  warmLight(scene, 0.75, 1.5, -5.1, 12, 6)
  const shelf = new THREE.Group()
  shelf.position.set(-3.5, 0, -FLOOR_Z + 0.3)
  const shelfWood = mat('#4a3628')
  shelf.add(box(1.4, 2.2, 0.05, shelfWood, 0, 1.1, -0.22))
  for (const sx of [-0.68, 0.68]) shelf.add(box(0.05, 2.2, 0.5, shelfWood, sx, 1.1, 0))
  const rand = seeded(3)
  const bookColours = ['#b0473f', '#3e6fb5', '#c9a24c', '#6c4fa1', '#3f7d52', '#c26b35', '#d9d4c7']
  for (let s = 0; s < 4; s++) {
    const y = 0.15 + s * 0.52
    shelf.add(box(1.32, 0.04, 0.44, shelfWood, 0, y, 0))
    let x = -0.6
    while (x < 0.55) {
      const w = 0.07 + rand() * 0.07
      const h = 0.28 + rand() * 0.14
      if (rand() < 0.85) shelf.add(box(w, h, 0.3, mat(bookColours[Math.floor(rand() * bookColours.length)]!), x + w / 2, y + 0.02 + h / 2, 0.02))
      x += w + 0.012
    }
  }
  room.add(shelf)
  const art2 = artTexture(21)
  track(art2)
  backWall.add(box(1.2, 0.8, 0.05, mat('#14151b'), -1.2, 1.75, -FLOOR_Z + 0.03))
  const art2Mesh = new THREE.Mesh(new THREE.PlaneGeometry(1.1, 0.7), mat('#ffffff', { map: art2 }))
  art2Mesh.position.set(-1.2, 1.75, -FLOOR_Z + 0.06)
  backWall.add(art2Mesh)

  // Coffee counter along the left wall, front half.
  const counter = new THREE.Group()
  counter.position.set(-FLOOR_X + 0.4, 0, 3.6)
  counter.add(box(0.7, 0.9, 3.0, mat('#24252d'), 0, 0.45, 0))
  counter.add(box(0.76, 0.05, 3.06, mat('#c9c2b4', { roughness: 0.3 }), 0, 0.92, 0))
  counter.add(box(0.4, 0.45, 0.35, mat('#15161b', { metalness: 0.5, roughness: 0.3 }), 0, 1.17, -0.8))
  counter.add(box(0.02, 0.06, 0.1, mat('#ff6b4a', { emissive: '#ff6b4a', emissiveIntensity: 2 }), 0.21, 1.3, -0.8))
  for (const cz of [0.2, 0.4]) counter.add(cylinder(0.05, 0.04, 0.1, mat('#e8e2d6'), 0.05, 0.99, cz))
  room.add(counter)
  leftWall.add(box(0.12, 0.08, 1.2, mat('#ffcf8a', { emissive: '#ffb46b', emissiveIntensity: 2.5 }), -FLOOR_X + 0.06, 2.1, 3.6))
  warmLight(scene, -FLOOR_X + 1.0, 2.0, 3.6, 12, 6)

  // Desk cluster: carpet and a divider between the two rows.
  room.add(flat(7.6, 4.9, mat('#3a3f52', { roughness: 1 }), 0, (NORTH_Z + SOUTH_Z) / 2, 0.008))
  const divider = mat('#3b4050', { roughness: 0.6, transparent: true, opacity: 0.92 })
  room.add(box(6.5, 0.42, 0.05, divider, 0, 1.0, (NORTH_Z + SOUTH_Z) / 2))
  warmLight(scene, -2.2, 2.6, 3.3, 12, 7, '#ffd9a8')
  warmLight(scene, 2.2, 2.6, 3.3, 12, 7, '#ffd9a8')
  warmLight(scene, 6.2, 2.5, -2.6, 12, 6, '#ffd9a8')

  // Plants and a water cooler.
  for (const [x, z, s] of [[-9.4, -0.95, 0.9], [-9.4, 0.95, 0.9], [-4.0, -5.4, 1.0], [2.6, -5.4, 1.2], [9.4, -5.4, 1.2], [9.4, 5.4, 1.3], [-4.6, 5.4, 1.1], [4.7, 5.4, 1.0]] as const) {
    room.add(plant(x, z, s))
  }
  const cooler = new THREE.Group()
  cooler.position.set(9.4, 0, -1.3)
  cooler.add(box(0.5, 1.0, 0.5, mat('#c9ced8'), 0, 0.5, 0, 0.04))
  cooler.add(cylinder(0.22, 0.22, 0.45, mat('#79c0ff', { transparent: true, opacity: 0.6, roughness: 0.1 }), 0, 1.23, 0))
  room.add(cooler)
  return { backWall, leftWall }
}

// ---- Desks ----
interface DeskView {
  place: string
  screens: THREE.MeshStandardMaterial[]
  code: THREE.Texture[]
  glow: THREE.PointLight | null
}

function buildDesk(scene: THREE.Scene, place: string, spot: DeskSpot, codeTex: THREE.Texture, track: Track, withGlow: boolean): DeskView {
  const g = new THREE.Group()
  g.position.set(spot.x, 0, spot.z)
  // Local +z points at the chair side; the sitter looks towards -z.
  g.rotation.y = spot.facing + Math.PI
  const top = mat('#4a4c58', { roughness: 0.5 })
  const leg = mat('#1c1d24', { metalness: 0.4, roughness: 0.5 })
  g.add(box(spot.width, 0.06, 0.9, top, 0, 0.75, 0, 0.02))
  g.add(box(spot.width, 0.02, 0.06, mat('#6b4a32'), 0, 0.73, 0.43)) // wood edge
  for (const sx of [-1, 1]) g.add(box(0.05, 0.72, 0.8, leg, sx * (spot.width / 2 - 0.1), 0.36, 0))
  g.add(box(0.6, 0.025, 0.2, mat('#1a1b21'), 0, 0.795, 0.2, 0.01)) // keyboard
  g.add(box(0.1, 0.025, 0.14, mat('#1a1b21'), 0.45, 0.795, 0.22, 0.01)) // mouse
  g.add(cylinder(0.055, 0.05, 0.11, mat('#e8e2d6'), -spot.width / 2 + 0.25, 0.835, 0.15))

  const screens: THREE.MeshStandardMaterial[] = []
  const code: THREE.Texture[] = []
  const spacing = 0.78
  for (let i = 0; i < spot.monitors; i++) {
    const offset = i - (spot.monitors - 1) / 2
    const monitor = new THREE.Group()
    monitor.position.set(offset * spacing, 0.78, -0.18 + Math.abs(offset) * 0.1)
    monitor.rotation.y = -offset * 0.35
    const dark = mat('#101116', { roughness: 0.35, metalness: 0.3 })
    monitor.add(box(0.24, 0.02, 0.16, dark, 0, 0.01, 0))
    monitor.add(box(0.05, 0.3, 0.04, dark, 0, 0.16, -0.02))
    monitor.add(box(0.74, 0.46, 0.04, dark, 0, 0.52, 0, 0.015))
    const tex = codeTex.clone()
    tex.needsUpdate = true
    tex.offset.y = i * 0.37
    track(tex)
    const screenMat = new THREE.MeshStandardMaterial({
      color: '#000000', emissive: '#ffffff', emissiveMap: tex, emissiveIntensity: 0.04, roughness: 0.3
    })
    const screen = new THREE.Mesh(new THREE.PlaneGeometry(0.68, 0.4), screenMat)
    screen.position.set(0, 0.52, 0.022)
    monitor.add(screen)
    g.add(monitor)
    screens.push(screenMat)
    code.push(tex)
  }

  let glow: THREE.PointLight | null = null
  if (withGlow) {
    glow = new THREE.PointLight('#5b9dff', 0, 3, 1.8)
    glow.position.set(0, 1.25, 0.25)
    g.add(glow)
  }
  // The desk group is turned by facing + PI, so PI here gives the chair the
  // sitter's own facing (its back behind the sitter).
  g.add(chair(0, CHAIR_GAP, Math.PI))
  scene.add(g)
  return { place, screens, code, glow }
}

// ---- Characters (small round robots) ----
interface CharacterView {
  root: THREE.Group
  body: THREE.Group
  head: THREE.Group
  antenna: THREE.Group
  legs: [THREE.Group, THREE.Group]
  arms: [THREE.Group, THREE.Group]
  eyes: THREE.Group
  eyeMeshes: THREE.Mesh[]
  smile: THREE.Mesh
  mouth: THREE.Mesh
  ring: THREE.Mesh
  ringMat: THREE.MeshBasicMaterial
  tag: HTMLDivElement
  tagStatus: HTMLSpanElement
  bubble: HTMLDivElement
  alertObj: CSS2DObject
  phase: number // per-robot offset so they don't all move in step
  heading: number
  lastPos: Point | null
  blinkAt: number
  status: CharacterStatus | null
  bubbleText: string | null
}

// A limb that swings from its top end.
function limb(radius: number, length: number, material: THREE.Material, pivotY: number, x: number) {
  const pivot = new THREE.Group()
  pivot.position.set(x, pivotY, 0)
  const mesh = new THREE.Mesh(new THREE.CapsuleGeometry(radius, length, 4, 12), material)
  mesh.position.y = -length / 2
  mesh.castShadow = true
  pivot.add(mesh)
  return pivot
}

function roundedRect(w: number, h: number, r: number) {
  const shape = new THREE.Shape()
  shape.moveTo(-w / 2 + r, -h / 2)
  shape.lineTo(w / 2 - r, -h / 2)
  shape.quadraticCurveTo(w / 2, -h / 2, w / 2, -h / 2 + r)
  shape.lineTo(w / 2, h / 2 - r)
  shape.quadraticCurveTo(w / 2, h / 2, w / 2 - r, h / 2)
  shape.lineTo(-w / 2 + r, h / 2)
  shape.quadraticCurveTo(-w / 2, h / 2, -w / 2, h / 2 - r)
  shape.lineTo(-w / 2, -h / 2 + r)
  shape.quadraticCurveTo(-w / 2, -h / 2, -w / 2 + r, -h / 2)
  return new THREE.ShapeGeometry(shape, 6)
}

function buildCharacter(scene: THREE.Scene, name: string): CharacterView {
  const colour = COLOURS[name] ?? OTHER_COLOUR
  const root = new THREE.Group()
  const body = new THREE.Group()
  root.add(body)
  const shell = mat(colour, { roughness: 0.35 })
  const shellDark = mat(new THREE.Color(colour).multiplyScalar(0.78), { roughness: 0.45 })
  const belly = mat(new THREE.Color(colour).lerp(new THREE.Color('#ffffff'), 0.55), { roughness: 0.4 })
  const glowColour = new THREE.Color(colour).lerp(new THREE.Color('#ffffff'), 0.35)

  // Stubby legs and arms, a round little body.
  const legs: [THREE.Group, THREE.Group] = [limb(0.085, 0.16, shellDark, 0.36, -0.12), limb(0.085, 0.16, shellDark, 0.36, 0.12)]
  body.add(...legs)
  body.add(box(0.5, 0.44, 0.42, shell, 0, 0.58, 0, 0.16))
  const bellyPatch = new THREE.Mesh(new THREE.CircleGeometry(0.12, 24), belly)
  bellyPatch.position.set(0, 0.56, 0.212)
  body.add(bellyPatch)
  const arms: [THREE.Group, THREE.Group] = [limb(0.07, 0.16, shell, 0.72, -0.3), limb(0.07, 0.16, shell, 0.72, 0.3)]
  arms[0].rotation.z = -0.25
  arms[1].rotation.z = 0.25
  body.add(...arms)

  // Big soft head with a dark face screen.
  const head = new THREE.Group()
  head.position.y = 1.16
  head.add(box(0.88, 0.74, 0.76, shell, 0, 0, 0, 0.17))
  const screen = new THREE.Mesh(roundedRect(0.66, 0.48, 0.13), mat('#0e1018', { roughness: 0.15, metalness: 0.3 }))
  screen.position.set(0, -0.02, 0.384)
  head.add(screen)
  // Face: glowing pill eyes, blush, a smile (an open mouth while talking).
  const glow = new THREE.MeshBasicMaterial({ color: '#dff6ff', toneMapped: false })
  const eyes = new THREE.Group()
  eyes.position.set(0, 0.02, 0.39)
  const eyeMeshes: THREE.Mesh[] = []
  for (const ex of [-0.14, 0.14]) {
    const eye = new THREE.Mesh(new THREE.CapsuleGeometry(0.04, 0.07, 4, 12), glow)
    eye.position.x = ex
    eye.scale.z = 0.3 // flat on the screen
    eyes.add(eye)
    eyeMeshes.push(eye)
  }
  head.add(eyes)
  const blush = new THREE.MeshBasicMaterial({ color: '#ff8fb3', transparent: true, opacity: 0.55 })
  for (const cx of [-0.23, 0.23]) {
    const cheek = new THREE.Mesh(new THREE.CircleGeometry(0.045, 20), blush)
    cheek.position.set(cx, -0.1, 0.388)
    head.add(cheek)
  }
  const smile = new THREE.Mesh(new THREE.TorusGeometry(0.05, 0.012, 6, 16, Math.PI), glow)
  smile.rotation.z = Math.PI // arc opening upwards: a smile
  smile.position.set(0, -0.1, 0.39)
  head.add(smile)
  const mouth = new THREE.Mesh(new THREE.CapsuleGeometry(0.025, 0.05, 4, 8), glow)
  mouth.rotation.z = Math.PI / 2
  mouth.position.set(0, -0.12, 0.39)
  mouth.scale.z = 0.3
  mouth.visible = false
  head.add(mouth)
  for (const sx of [-1, 1]) {
    const ear = cylinder(0.09, 0.09, 0.06, shellDark, sx * 0.46, 0, 0, 20)
    ear.rotation.z = Math.PI / 2
    head.add(ear)
  }
  // Antenna with a glowing tip; it wobbles from its base.
  const antenna = new THREE.Group()
  antenna.position.y = 0.37
  antenna.add(cylinder(0.018, 0.022, 0.18, shellDark, 0, 0.09, 0, 8))
  const tip = new THREE.Mesh(new THREE.SphereGeometry(0.065, 16, 12), new THREE.MeshBasicMaterial({ color: glowColour, toneMapped: false }))
  tip.position.y = 0.22
  antenna.add(tip)
  head.add(antenna)
  body.add(head)

  // Status ring on the floor.
  const ringMat = new THREE.MeshBasicMaterial({ color: colour, transparent: true, opacity: 0.35, depthWrite: false })
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.42, 0.52, 40), ringMat)
  ring.rotation.x = -Math.PI / 2
  ring.position.y = 0.02
  root.add(ring)

  // HTML labels (crisp text that follows the robot on screen): the speech
  // bubble stacked on top of the name tag, anchored above the antenna.
  const label = document.createElement('div')
  label.className = 'office3d-label'
  const bubble = document.createElement('div')
  bubble.className = 'office3d-bubble'
  bubble.hidden = true
  const tag = document.createElement('div')
  tag.className = 'office3d-tag'
  const dot = document.createElement('span')
  dot.className = 'office3d-dot'
  dot.style.background = colour
  const nameEl = document.createElement('span')
  nameEl.textContent = name
  const tagStatus = document.createElement('span')
  tagStatus.className = 'office3d-status'
  tag.append(dot, nameEl, tagStatus)
  label.append(bubble, tag)
  const labelObj = new CSS2DObject(label)
  labelObj.center.set(0.5, 1)
  labelObj.position.y = 1.95
  root.add(labelObj)

  const alert = document.createElement('div')
  alert.className = 'office3d-alert'
  alert.textContent = '!'
  const alertObj = new CSS2DObject(alert)
  alertObj.position.set(0.6, 1.75, 0)
  alertObj.visible = false
  root.add(alertObj)

  root.scale.setScalar(ROBOT_SCALE)
  root.visible = false
  scene.add(root)
  let phase = 0
  for (const ch of name) phase += ch.charCodeAt(0)
  return {
    root, body, head, antenna, legs, arms, eyes, eyeMeshes, smile, mouth, ring, ringMat, tag, tagStatus, bubble, alertObj,
    phase: phase % 7, heading: 0, lastPos: null, blinkAt: 0, status: null, bubbleText: null
  }
}

function turnTowards(current: number, target: number, amount: number) {
  let d = target - current
  d = Math.atan2(Math.sin(d), Math.cos(d))
  return current + d * Math.min(1, amount)
}

function animateCharacter(view: CharacterView, state: OfficeState, c: Character, nowMs: number, dt: number) {
  const status = characterStatus(state, c.name)
  const pos = characterPoint(state, c)
  const t = nowMs / 1000 + view.phase

  // Facing: along the walk while walking, else the place's direction.
  let target = view.heading
  if (c.walk && view.lastPos) {
    const dx = pos.x - view.lastPos.x
    const dz = pos.z - view.lastPos.z
    if (Math.hypot(dx, dz) > 1e-4) target = Math.atan2(dx, dz)
  } else if (!c.walk) {
    target = spotFor(c.desk).facing
  }
  view.heading = view.lastPos ? turnTowards(view.heading, target, dt * 12) : target
  view.lastPos = pos
  view.root.position.set(pos.x, 0, pos.z)
  view.root.rotation.y = view.heading

  const [legL, legR] = view.legs
  const [armL, armR] = view.arms
  let bob = 0
  let squash = 1
  let sway = 0
  let headTilt = 0
  let headTurn = 0
  let headRoll = 0
  let antennaSwing = Math.sin(t * 3) * 0.12
  let eyeX = 0
  let eyeY = 0
  if (status === 'walking') {
    // Little hops with a squash on landing.
    const s = Math.sin(t * 10)
    legL.rotation.x = s * 0.7
    legR.rotation.x = -s * 0.7
    armL.rotation.x = -s * 0.6
    armR.rotation.x = s * 0.6
    const hop = Math.abs(Math.sin(t * 10))
    bob = hop * 0.09
    squash = 1 - (1 - hop) * 0.06
    antennaSwing = Math.sin(t * 10 + 1) * 0.35
  } else {
    // Sitting: legs forward under the desk / table.
    legL.rotation.x = legR.rotation.x = -Math.PI / 2
    if (status === 'working') {
      armL.rotation.x = -1.25 + Math.sin(t * 22) * 0.14
      armR.rotation.x = -1.25 + Math.sin(t * 22 + Math.PI) * 0.14
      headTilt = 0.08 + Math.sin(t * 22) * 0.012
      eyeX = Math.sin(t * 1.6) * 0.035 // reading along the lines
      eyeY = -0.015
      antennaSwing = Math.sin(t * 7) * 0.08
    } else if (status === 'talking') {
      armL.rotation.x = -0.4 + Math.sin(t * 5 + 1) * 0.25
      armR.rotation.x = -1.1 + Math.sin(t * 6) * 0.4
      headTilt = Math.sin(t * 9) * 0.06
      headTurn = Math.sin(t * 2.3) * 0.15
      headRoll = Math.sin(t * 3.1) * 0.08
      bob = Math.abs(Math.sin(t * 6)) * 0.02
    } else {
      // Idle: gentle sway, look around now and then.
      armL.rotation.x = armR.rotation.x = -0.15 + Math.sin(t * 2) * 0.05
      sway = Math.sin(t * 1.3) * 0.04
      headTurn = Math.sin(t * 0.6) * 0.3
      headRoll = Math.sin(t * 0.9) * 0.05
      bob = Math.sin(t * 2) * 0.012
      eyeX = Math.sin(t * 0.6) * 0.03
    }
  }
  view.body.position.y = bob
  view.body.scale.set(2 - squash, squash, 2 - squash)
  view.body.rotation.z = sway
  view.head.rotation.set(headTilt, headTurn, headRoll)
  view.antenna.rotation.z = antennaSwing
  view.antenna.rotation.x = Math.sin(t * 2.2) * 0.06
  view.eyes.position.x = eyeX
  view.eyes.position.y = 0.02 + eyeY

  // Blink every few seconds; eyes squint a little while talking.
  if (nowMs - view.blinkAt > 2800 + view.phase * 400) view.blinkAt = nowMs
  const blinking = nowMs - view.blinkAt < 130
  const eyeScale = blinking ? 0.12 : status === 'talking' ? 0.75 : 1
  for (const eye of view.eyeMeshes) eye.scale.y = eyeScale
  // Mouth: a smile, or an open mouth moving while talking.
  const talking = status === 'talking'
  view.smile.visible = !talking
  view.mouth.visible = talking
  // The capsule lies on its side, so local x is the mouth's height.
  if (talking) view.mouth.scale.set(0.6 + Math.abs(Math.sin(t * 12)) * 1.4, 1, 0.3)

  // Ring: pulses while working, brighter while talking.
  view.ringMat.opacity = status === 'working' ? 0.5 + Math.sin(t * 6) * 0.3 : status === 'talking' ? 0.75 : 0.25
  view.ring.scale.setScalar(status === 'working' ? 1 + Math.sin(t * 6) * 0.06 : 1)

  if (view.status !== status) {
    view.status = status
    view.tagStatus.textContent = status
    view.tag.dataset.status = status
  }
  const bubble = activeBubble(state, c.name)
  if (bubble !== view.bubbleText) {
    view.bubble.hidden = bubble === null
    view.bubbleText = bubble
    view.bubble.textContent = bubble ?? ''
  }
  view.alertObj.visible = showsAlert(state, c.name)
}

// ---- Camera ----
// Default view; the user can rotate (drag), zoom (scroll / pinch) and pan
// (right-drag / two fingers) from here, and reset back to it.
const VIEW_AZIMUTH = THREE.MathUtils.degToRad(36) // from +z towards +x
const VIEW_ELEVATION = THREE.MathUtils.degToRad(38)
const VIEW_TARGET = new THREE.Vector3(0, 0.6, 0)
const VIEW_DISTANCE = 40
// Points that must stay in frame: the floor slab and the wall tops.
const FRAME_POINTS: THREE.Vector3[] = []
for (const x of [-FLOOR_X, FLOOR_X]) {
  for (const z of [-FLOOR_Z, FLOOR_Z]) {
    FRAME_POINTS.push(new THREE.Vector3(x, -0.4, z), new THREE.Vector3(x, WALL_H + 0.1, z))
  }
}

function defaultPosition(): THREE.Vector3 {
  const dir = new THREE.Vector3(
    Math.sin(VIEW_AZIMUTH) * Math.cos(VIEW_ELEVATION),
    Math.sin(VIEW_ELEVATION),
    Math.cos(VIEW_AZIMUTH) * Math.cos(VIEW_ELEVATION)
  )
  return VIEW_TARGET.clone().addScaledVector(dir, VIEW_DISTANCE)
}

// Size the view so the whole room fits (seen from the default angle) in the
// part not covered by the chat panel (insetRight px on the right), keeping
// world units square. Only the frustum changes: the user's rotation and zoom
// are kept.
function fitFrustum(camera: THREE.OrthographicCamera, width: number, height: number, insetRight: number) {
  const view = new THREE.Object3D()
  view.position.copy(defaultPosition())
  view.lookAt(VIEW_TARGET)
  view.updateMatrixWorld()
  const inv = view.matrixWorld.clone().invert()
  let minX = Infinity; let maxX = -Infinity; let minY = Infinity; let maxY = -Infinity
  for (const p of FRAME_POINTS) {
    const v = p.clone().applyMatrix4(inv)
    minX = Math.min(minX, v.x); maxX = Math.max(maxX, v.x)
    minY = Math.min(minY, v.y); maxY = Math.max(maxY, v.y)
  }
  const pad = 0.4
  const free = Math.max(width * 0.4, width - insetRight)
  let w = maxX - minX + pad * 2
  let h = maxY - minY + pad * 2
  if (w / h > free / height) h = w * height / free
  else w = h * free / height
  const perPx = h / height
  const cx = (minX + maxX) / 2
  const cy = (minY + maxY) / 2
  camera.left = cx - w / 2
  camera.right = camera.left + width * perPx
  camera.top = cy + h / 2
  camera.bottom = cy - h / 2
  camera.near = 1
  camera.far = 100
  camera.updateProjectionMatrix()
}

// ---- Public API ----
export interface OfficeScene {
  draw(state: OfficeState, frameMs: number): void
  setInsetRight(px: number): void
  resetView(): void
  dispose(): void
}

// Throws if WebGL is not available (the caller shows a message).
export function createOfficeScene(container: HTMLElement): OfficeScene {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
  renderer.setClearColor(0x000000, 0)
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.4
  renderer.shadowMap.enabled = true
  renderer.shadowMap.type = THREE.PCFShadowMap
  renderer.domElement.className = 'office3d-canvas'
  container.appendChild(renderer.domElement)

  const labels = new CSS2DRenderer()
  labels.domElement.className = 'office3d-labels'
  container.appendChild(labels.domElement)

  const scene = new THREE.Scene()
  const camera = new THREE.OrthographicCamera()
  const textures: THREE.Texture[] = []
  const track: Track = (t) => { textures.push(t) }

  // Night: dim cool sky light, a soft moonlight for shadows, warm lamps
  // (added with the scenery) and glowing screens.
  scene.add(new THREE.HemisphereLight('#a3b2ee', '#2a2a33', 2.4))
  const moon = new THREE.DirectionalLight('#d3dbff', 2.2)
  moon.position.set(9, 16, 10)
  moon.castShadow = true
  moon.shadow.mapSize.set(2048, 2048)
  moon.shadow.camera.left = -14
  moon.shadow.camera.right = 14
  moon.shadow.camera.top = 11
  moon.shadow.camera.bottom = -11
  moon.shadow.camera.near = 1
  moon.shadow.camera.far = 50
  moon.shadow.bias = -0.0004
  moon.shadow.normalBias = 0.02
  moon.shadow.radius = 4
  scene.add(moon)

  const walls = buildRoom(scene, track)
  const codeTex = codeTexture()
  track(codeTex)
  const desks = Object.entries(DESKS).map(([place, spot]) => buildDesk(scene, place, spot, codeTex, track, true))
  buildDesk(scene, '', EMPTY_DESK, codeTex, track, false)

  const characters = new Map<string, CharacterView>()
  let insetRight = 0

  // Rotate / zoom / pan. Angles are limited so the camera stays above the
  // floor; zoom and pan are limited so the room stays in view.
  camera.position.copy(defaultPosition())
  const controls = new OrbitControls(camera, renderer.domElement)
  controls.target.copy(VIEW_TARGET)
  controls.enableDamping = true
  controls.dampingFactor = 0.08
  controls.minPolarAngle = THREE.MathUtils.degToRad(18)
  controls.maxPolarAngle = THREE.MathUtils.degToRad(75)
  controls.minZoom = 0.6
  controls.maxZoom = 4
  controls.zoomToCursor = true
  controls.update()

  function resetView() {
    camera.position.copy(defaultPosition())
    camera.zoom = 1
    camera.updateProjectionMatrix()
    controls.target.copy(VIEW_TARGET)
    controls.update()
  }

  function resize() {
    const w = Math.max(1, container.clientWidth)
    const h = Math.max(1, container.clientHeight)
    renderer.setSize(w, h, false)
    labels.setSize(w, h)
    fitFrustum(camera, w, h, insetRight)
  }
  const observer = new ResizeObserver(resize)
  observer.observe(container)
  resize()

  let lastFrameMs = 0

  function draw(state: OfficeState, frameMs: number) {
    const dt = lastFrameMs ? Math.min(0.1, (frameMs - lastFrameMs) / 1000) : 0
    lastFrameMs = frameMs

    for (const c of Object.values(state.characters)) {
      let view = characters.get(c.name)
      if (!view) {
        view = buildCharacter(scene, c.name)
        characters.set(c.name, view)
      }
      view.root.visible = c.present
      if (!c.present) {
        view.lastPos = null
        continue
      }
      animateCharacter(view, state, c, frameMs, dt)
    }

    // Monitors: off when nobody sits there, on when the owner is idle,
    // scrolling code and a coloured glow while working.
    for (const desk of desks) {
      const owner = Object.values(state.characters).find(c => c.present && !c.walk && c.desk === desk.place)
      const status = owner ? characterStatus(state, owner.name) : null
      const working = status === 'working'
      for (const [i, screen] of desk.screens.entries()) {
        const target = working ? 1.7 : owner ? 0.6 : 0.04
        screen.emissiveIntensity += (target - screen.emissiveIntensity) * Math.min(1, dt * 8)
        if (working) desk.code[i]!.offset.y -= dt * 0.35
      }
      if (desk.glow) {
        desk.glow.color.set(owner ? COLOURS[owner.name] ?? OTHER_COLOUR : '#5b9dff')
        const glowTarget = working ? 3 + Math.sin(frameMs / 90) * 0.4 : owner ? 0.8 : 0
        desk.glow.intensity += (glowTarget - desk.glow.intensity) * Math.min(1, dt * 8)
      }
    }

    // Keep the orbit centre over the room, then apply damping.
    controls.target.x = THREE.MathUtils.clamp(controls.target.x, -FLOOR_X, FLOOR_X)
    controls.target.y = THREE.MathUtils.clamp(controls.target.y, 0, 2)
    controls.target.z = THREE.MathUtils.clamp(controls.target.z, -FLOOR_Z, FLOOR_Z)
    controls.update()
    // A solid wall between the camera and the room is hidden.
    const toCamera = camera.position.clone().sub(controls.target)
    walls.backWall.visible = toCamera.z > -0.5
    walls.leftWall.visible = toCamera.x > -0.5

    renderer.render(scene, camera)
    labels.render(scene, camera)
  }

  function setInsetRight(px: number) {
    if (px === insetRight) return
    insetRight = px
    resize()
  }

  function dispose() {
    controls.dispose()
    observer.disconnect()
    scene.traverse((obj) => {
      if (obj instanceof THREE.Mesh) {
        obj.geometry.dispose()
        for (const m of Array.isArray(obj.material) ? obj.material : [obj.material]) m.dispose()
      }
    })
    for (const t of textures) t.dispose()
    renderer.dispose()
    renderer.domElement.remove()
    labels.domElement.remove()
  }

  return { draw, setInsetRight, resetView, dispose }
}

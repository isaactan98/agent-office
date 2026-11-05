// 3D office view (three.js) for components/Office.vue.
// Draws an OfficeState from utils/officeState.ts: it reads the state, never
// changes it. All behaviour (who walks where, who is working) stays in the
// reducer; this file only turns places and statuses into a scene.
//
// Built from simple primitives (boxes, cylinders) and canvas textures, so
// there are no model or image files to load.
import * as THREE from 'three'
import { CSS2DObject, CSS2DRenderer } from 'three/examples/jsm/renderers/CSS2DRenderer.js'
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js'
import { DOOR, activeBubble, characterStatus, showsAlert, walkProgress } from './officeState'
import type { Character, CharacterStatus, OfficeState } from './officeState'

// ---- Layout (world units, y up, floor at y = 0) ----
const FLOOR_X = 9.5 // floor spans -FLOOR_X..FLOOR_X
const FLOOR_Z = 5.5
const WALL_H = 3.2
const CORRIDOR_Z = 0 // characters walk along this line between the desk rows
const DOOR_Z = CORRIDOR_Z
const DOOR_W = 1.7
const DOOR_POINT = { x: -FLOOR_X + 0.6, z: DOOR_Z }

// facing: the direction the sitting character looks (radians, 0 = +z).
interface DeskSpot { x: number, z: number, facing: number, wide?: boolean }
const BACK = Math.PI // looks at the back wall (-z), monitor faces the camera
const FRONT = 0 // looks towards the camera (+z)
const DESKS: Record<string, DeskSpot> = {
  'desk:orchestrator': { x: -5.2, z: -3.4, facing: BACK, wide: true },
  'desk:writer': { x: -0.2, z: -3.4, facing: BACK },
  'desk:reviewer': { x: 4.8, z: -3.4, facing: BACK },
  'spare:1': { x: 1.8, z: 3.4, facing: FRONT },
  'spare:2': { x: 4.6, z: 3.4, facing: FRONT },
  'spare:3': { x: 7.4, z: 3.4, facing: FRONT }
}
const CHAIR_GAP = 1.3 // desk centre → chair centre
const TABLE = { x: -5.2, z: 3.2, r: 1.0, seatR: 1.75 }
const ROBOT_SCALE = 1.3

// Same colours as the agent tags in the feed (app.vue).
const COLOURS: Record<string, string> = { orchestrator: '#0550ae', writer: '#8250df', reviewer: '#bc4c00' }
const OTHER_COLOUR = '#6e7781'

interface Point { x: number, z: number }

function chairPoint(desk: DeskSpot): Point {
  // The chair is on the side the character looks away from.
  return { x: desk.x - Math.sin(desk.facing) * CHAIR_GAP, z: desk.z - Math.cos(desk.facing) * CHAIR_GAP }
}

function tableSeat(place: string): Point & { facing: number } {
  const n = Number(place.split(':')[1]) || 1
  const angle = -Math.PI / 2 + ((n - 1) % 8) * (Math.PI / 4)
  const x = TABLE.x + Math.cos(angle) * TABLE.seatR
  const z = TABLE.z + Math.sin(angle) * TABLE.seatR
  return { x, z, facing: Math.atan2(TABLE.x - x, TABLE.z - z) }
}

// Where a character is for a place: the door, a desk chair, or a table seat.
function placePoint(place: string): Point {
  if (place === DOOR) return DOOR_POINT
  const desk = DESKS[place]
  if (desk) return chairPoint(desk)
  return tableSeat(place)
}

function placeFacing(place: string): number {
  const desk = DESKS[place]
  if (desk) return desk.facing
  if (place.startsWith('table:')) return tableSeat(place).facing
  return 0
}

// Position along a walk: to the corridor, along it, then to the target.
function walkPoint(from: Point, to: Point, progress: number): Point {
  const path = [from, { x: from.x, z: CORRIDOR_Z }, { x: to.x, z: CORRIDOR_Z }, to]
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
  return to
}

function characterPoint(state: OfficeState, c: Character): Point {
  if (!c.walk) return placePoint(c.desk)
  return walkPoint(placePoint(c.walk.from), placePoint(c.walk.to), walkProgress(state, c.name))
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
function floorTexture() {
  const rand = seeded(7)
  const texture = canvasTexture(512, 512, (ctx) => {
    const plankH = 64
    for (let row = 0; row < 512 / plankH; row++) {
      let x = row % 2 ? -120 : 0
      while (x < 512) {
        const len = 160 + rand() * 140
        const light = 62 + rand() * 8
        ctx.fillStyle = `hsl(30, 32%, ${light}%)`
        ctx.fillRect(x, row * plankH, len, plankH)
        // Grain.
        ctx.strokeStyle = 'rgba(90, 60, 30, 0.08)'
        ctx.lineWidth = 1
        for (let g = 0; g < 4; g++) {
          const gy = row * plankH + 8 + rand() * (plankH - 16)
          ctx.beginPath()
          ctx.moveTo(x + 6, gy)
          ctx.bezierCurveTo(x + len * 0.3, gy + 3, x + len * 0.6, gy - 3, x + len - 6, gy)
          ctx.stroke()
        }
        ctx.fillStyle = 'rgba(70, 45, 20, 0.35)'
        ctx.fillRect(x, row * plankH, 2, plankH)
        x += len
      }
      ctx.fillStyle = 'rgba(70, 45, 20, 0.35)'
      ctx.fillRect(0, row * plankH, 512, 2)
    }
  })
  texture.wrapS = THREE.RepeatWrapping
  texture.wrapT = THREE.RepeatWrapping
  texture.repeat.set(5, 3)
  return texture
}

function cityTexture(seed: number) {
  const rand = seeded(seed)
  return canvasTexture(256, 160, (ctx) => {
    const sky = ctx.createLinearGradient(0, 0, 0, 160)
    sky.addColorStop(0, '#141b3a')
    sky.addColorStop(0.6, '#3a3570')
    sky.addColorStop(1, '#b9668a')
    ctx.fillStyle = sky
    ctx.fillRect(0, 0, 256, 160)
    for (let i = 0; i < 30; i++) {
      ctx.fillStyle = `rgba(255, 255, 255, ${0.3 + rand() * 0.5})`
      ctx.fillRect(rand() * 256, rand() * 70, 1.5, 1.5)
    }
    let x = -10
    while (x < 256) {
      const w = 18 + rand() * 30
      const h = 40 + rand() * 90
      ctx.fillStyle = `hsl(240, 25%, ${10 + rand() * 8}%)`
      ctx.fillRect(x, 160 - h, w, h)
      for (let wy = 160 - h + 6; wy < 156; wy += 8) {
        for (let wx = x + 4; wx < x + w - 4; wx += 6) {
          if (rand() < 0.35) {
            ctx.fillStyle = rand() < 0.8 ? '#ffd88a' : '#9fd8ff'
            ctx.fillRect(wx, wy, 3, 4)
          }
        }
      }
      x += w + 2
    }
  })
}

// Lines of "code" that scroll on a working monitor.
function codeTexture() {
  const rand = seeded(42)
  const colours = ['#7ee2a8', '#79c0ff', '#d2a8ff', '#ffa657', '#e6edf3']
  const texture = canvasTexture(256, 256, (ctx) => {
    ctx.fillStyle = '#0d1117'
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

function artTexture() {
  return canvasTexture(128, 96, (ctx) => {
    ctx.fillStyle = '#f4efe6'
    ctx.fillRect(0, 0, 128, 96)
    ctx.fillStyle = '#0550ae'
    ctx.beginPath()
    ctx.arc(44, 50, 26, 0, Math.PI * 2)
    ctx.fill()
    ctx.fillStyle = '#bc4c00'
    ctx.fillRect(66, 18, 40, 40)
    ctx.fillStyle = '#8250df'
    ctx.beginPath()
    ctx.moveTo(60, 84)
    ctx.lineTo(112, 84)
    ctx.lineTo(86, 52)
    ctx.fill()
  })
}

// ---- Static scenery ----
function buildRoom(scene: THREE.Scene, track: (t: THREE.Texture) => void) {
  const room = new THREE.Group()
  scene.add(room)

  // Floor slab: the office sits on a thick base like a diorama.
  const floorTex = floorTexture()
  track(floorTex)
  const floor = new THREE.Mesh(new THREE.BoxGeometry(FLOOR_X * 2, 0.5, FLOOR_Z * 2), [
    mat('#3b3f58'), mat('#3b3f58'), mat('#d9b98c', { map: floorTex, roughness: 0.6 }), mat('#3b3f58'), mat('#2f3247'), mat('#3b3f58')
  ])
  floor.position.y = -0.25
  floor.receiveShadow = true
  room.add(floor)

  // Walls: back and left only, so the camera can look in (cut-away).
  const wallMat = mat('#e9e4f2', { roughness: 0.9 })
  const trimMat = mat('#c9c1dc')
  room.add(box(FLOOR_X * 2 + 0.3, WALL_H, 0.3, wallMat, 0, WALL_H / 2, -FLOOR_Z - 0.15))
  room.add(box(FLOOR_X * 2 + 0.3, 0.12, 0.34, trimMat, 0, WALL_H + 0.06, -FLOOR_Z - 0.15))
  // Left wall in two pieces around the door opening.
  const leftBack = DOOR_Z - DOOR_W / 2 + FLOOR_Z
  const leftFront = FLOOR_Z - (DOOR_Z + DOOR_W / 2)
  room.add(box(0.3, WALL_H, leftBack, wallMat, -FLOOR_X - 0.15, WALL_H / 2, -FLOOR_Z + leftBack / 2))
  room.add(box(0.3, WALL_H, leftFront, wallMat, -FLOOR_X - 0.15, WALL_H / 2, FLOOR_Z - leftFront / 2))
  room.add(box(0.3, WALL_H - 2.3, DOOR_W, wallMat, -FLOOR_X - 0.15, 2.3 + (WALL_H - 2.3) / 2, DOOR_Z))
  room.add(box(0.34, 0.12, FLOOR_Z * 2 + 0.3, trimMat, -FLOOR_X - 0.15, WALL_H + 0.06, 0))
  // Skirting along the walls.
  const skirt = mat('#8f86ad')
  room.add(box(FLOOR_X * 2, 0.14, 0.06, skirt, 0, 0.07, -FLOOR_Z + 0.03))

  // Door: frame, an open door leaf and a glowing sign above it.
  const frameMat = mat('#6b5440')
  room.add(box(0.36, 2.3, 0.1, frameMat, -FLOOR_X - 0.1, 1.15, DOOR_Z - DOOR_W / 2 - 0.05))
  room.add(box(0.36, 2.3, 0.1, frameMat, -FLOOR_X - 0.1, 1.15, DOOR_Z + DOOR_W / 2 + 0.05))
  room.add(box(0.36, 0.1, DOOR_W + 0.2, frameMat, -FLOOR_X - 0.1, 2.3, DOOR_Z))
  const leaf = box(0.07, 2.2, DOOR_W - 0.05, mat('#a0784a'), 0, 1.1, (DOOR_W - 0.05) / 2)
  const hinge = new THREE.Group()
  hinge.position.set(-FLOOR_X + 0.05, 0, DOOR_Z - DOOR_W / 2)
  hinge.rotation.y = -1.1
  hinge.add(leaf)
  room.add(hinge)
  room.add(box(0.04, 0.22, 0.6, mat('#2ea043', { emissive: '#3fdc6a', emissiveIntensity: 1.6 }), -FLOOR_X + 0.02, 2.62, DOOR_Z))
  const mat2 = new THREE.Mesh(new THREE.PlaneGeometry(1.1, 1.5), mat('#5b4e7a'))
  mat2.rotation.x = -Math.PI / 2
  mat2.position.set(-FLOOR_X + 0.75, 0.005, DOOR_Z)
  mat2.receiveShadow = true
  room.add(mat2)

  // Windows on the back wall with a night city outside.
  const glassFrame = mat('#4a4466')
  for (const [i, x] of [-5.2, -0.2, 4.8].entries()) {
    const tex = cityTexture(11 + i * 7)
    track(tex)
    const pane = new THREE.Mesh(new THREE.PlaneGeometry(3.6, 1.5), new THREE.MeshBasicMaterial({ map: tex }))
    pane.position.set(x, 2.05, -FLOOR_Z + 0.01)
    room.add(pane)
    room.add(box(3.8, 0.1, 0.12, glassFrame, x, 2.85, -FLOOR_Z + 0.05))
    room.add(box(3.8, 0.12, 0.2, glassFrame, x, 1.25, -FLOOR_Z + 0.08))
    for (const dx of [-1.85, 0, 1.85]) room.add(box(0.08, 1.6, 0.1, glassFrame, x + dx, 2.05, -FLOOR_Z + 0.05))
  }

  // Art on the left wall.
  const art = artTexture()
  track(art)
  room.add(box(0.08, 1.05, 1.4, mat('#2d2a3e'), -FLOOR_X + 0.04, 1.85, -2.8))
  const canvasArt = new THREE.Mesh(new THREE.PlaneGeometry(1.25, 0.9), mat('#ffffff', { map: art }))
  canvasArt.rotation.y = Math.PI / 2
  canvasArt.position.set(-FLOOR_X + 0.09, 1.85, -2.8)
  room.add(canvasArt)

  // Bookshelf in the back right corner.
  const shelf = new THREE.Group()
  shelf.position.set(8.0, 0, -FLOOR_Z + 0.35)
  const wood = mat('#8a6a4a')
  shelf.add(box(2.2, 2.4, 0.06, wood, 0, 1.2, -0.27)) // back
  for (const sx of [-1.07, 1.07]) shelf.add(box(0.06, 2.4, 0.6, wood, sx, 1.2, 0))
  shelf.add(box(2.2, 0.06, 0.6, wood, 0, 2.4, 0))
  const rand = seeded(3)
  const bookColours = ['#e5534b', '#3b82f6', '#f2cc60', '#8250df', '#2ea043', '#f0883e', '#e9e4f2']
  for (let s = 0; s < 4; s++) {
    const y = 0.2 + s * 0.55
    shelf.add(box(2.0, 0.04, 0.5, mat('#5c4430'), 0, y, 0.06))
    let x = -0.9
    while (x < 0.85) {
      const w = 0.08 + rand() * 0.08
      const h = 0.3 + rand() * 0.15
      shelf.add(box(w, h, 0.36, mat(bookColours[Math.floor(rand() * bookColours.length)]!), x + w / 2, y + 0.02 + h / 2, 0.1))
      x += w + 0.015
      if (rand() < 0.08) x += 0.2
    }
  }
  room.add(shelf)

  // Meeting area: rug, round table, chairs.
  const rug = new THREE.Mesh(new THREE.CircleGeometry(2.45, 48), mat('#6c5fa8', { roughness: 1 }))
  rug.rotation.x = -Math.PI / 2
  rug.position.set(TABLE.x, 0.01, TABLE.z)
  rug.receiveShadow = true
  room.add(rug)
  const rugRing = new THREE.Mesh(new THREE.RingGeometry(2.22, 2.3, 48), mat('#b5a8f0', { roughness: 1 }))
  rugRing.rotation.x = -Math.PI / 2
  rugRing.position.set(TABLE.x, 0.015, TABLE.z)
  room.add(rugRing)
  room.add(cylinder(TABLE.r, TABLE.r, 0.08, mat('#f4efe6', { roughness: 0.4 }), TABLE.x, 0.76, TABLE.z, 40))
  room.add(cylinder(0.08, 0.08, 0.72, mat('#4a4466'), TABLE.x, 0.38, TABLE.z))
  room.add(cylinder(0.45, 0.5, 0.05, mat('#4a4466'), TABLE.x, 0.03, TABLE.z))
  for (let n = 1; n <= 8; n++) {
    const seat = tableSeat(`table:${n}`)
    room.add(chair(seat.x, seat.z, seat.facing, '#d7d0ea'))
  }

  // Plants and a water cooler.
  for (const [x, z, s] of [[-8.8, -4.8, 1.2], [-8.9, -1.6, 0.9], [-8.9, 1.6, 0.9], [-2.7, -4.9, 1], [2.3, -4.9, 1], [8.8, 4.9, 1.3], [-8.6, 4.9, 1.1]] as const) {
    room.add(plant(x, z, s))
  }
  const cooler = new THREE.Group()
  cooler.position.set(8.8, 0, -1.2)
  cooler.add(box(0.55, 1.0, 0.55, mat('#e6e9ef'), 0, 0.5, 0, 0.05))
  cooler.add(cylinder(0.24, 0.24, 0.5, mat('#79c0ff', { transparent: true, opacity: 0.7, roughness: 0.1 }), 0, 1.25, 0))
  room.add(cooler)

  return room
}

function chair(x: number, z: number, facing: number, colour: string) {
  const g = new THREE.Group()
  g.position.set(x, 0, z)
  g.rotation.y = facing
  const seat = mat(colour)
  const dark = mat('#3d3a4f')
  g.add(box(0.62, 0.1, 0.58, seat, 0, 0.42, 0, 0.04))
  g.add(box(0.6, 0.5, 0.1, seat, 0, 0.72, -0.3, 0.04)) // back, behind the sitter
  g.add(cylinder(0.04, 0.04, 0.36, dark, 0, 0.2, 0))
  g.add(cylinder(0.26, 0.26, 0.04, dark, 0, 0.03, 0, 5))
  return g
}

function plant(x: number, z: number, scale: number) {
  const g = new THREE.Group()
  g.position.set(x, 0, z)
  g.scale.setScalar(scale)
  g.add(cylinder(0.26, 0.2, 0.45, mat('#e8dccb'), 0, 0.225, 0))
  g.add(cylinder(0.24, 0.24, 0.03, mat('#5b4330'), 0, 0.44, 0))
  const leaf = mat('#3f9b58', { flatShading: true })
  const leafDark = mat('#2f7d47', { flatShading: true })
  const rand = seeded(Math.round((x + 20) * 100 + z * 10))
  for (let i = 0; i < 5; i++) {
    const m = new THREE.Mesh(new THREE.IcosahedronGeometry(0.22 + rand() * 0.12, 0), i % 2 ? leaf : leafDark)
    m.position.set((rand() - 0.5) * 0.35, 0.7 + i * 0.12 + rand() * 0.1, (rand() - 0.5) * 0.35)
    m.castShadow = true
    g.add(m)
  }
  return g
}

// ---- Desks ----
interface DeskView {
  place: string
  screens: THREE.MeshStandardMaterial[]
  code: THREE.Texture[]
  glow: THREE.PointLight
}

function buildDesk(scene: THREE.Scene, place: string, spot: DeskSpot, codeTex: THREE.Texture, track: (t: THREE.Texture) => void): DeskView {
  const g = new THREE.Group()
  g.position.set(spot.x, 0, spot.z)
  // Local +z points at the chair side; the sitter looks towards -z.
  g.rotation.y = spot.facing + Math.PI
  const width = spot.wide ? 2.7 : 1.9
  const top = mat('#f2e6d3', { roughness: 0.5 })
  const leg = mat('#4a4466')
  g.add(box(width, 0.08, 0.95, top, 0, 0.74, 0, 0.03))
  for (const sx of [-1, 1]) {
    g.add(box(0.06, 0.72, 0.8, leg, sx * (width / 2 - 0.12), 0.36, 0))
  }
  g.add(box(width - 0.3, 0.3, 0.04, leg, 0, 0.5, -0.38)) // modesty panel
  // Keyboard, mug.
  g.add(box(0.62, 0.03, 0.2, mat('#e6e9ef'), 0, 0.795, 0.2, 0.01))
  g.add(cylinder(0.06, 0.06, 0.12, mat('#f0883e'), width / 2 - 0.3, 0.84, 0.15))

  const screens: THREE.MeshStandardMaterial[] = []
  const code: THREE.Texture[] = []
  const monitorXs = spot.wide ? [-0.55, 0.55] : [0]
  for (const mx of monitorXs) {
    const monitor = new THREE.Group()
    monitor.position.set(mx, 0.78, -0.2)
    if (spot.wide) monitor.rotation.y = mx < 0 ? 0.2 : -0.2
    const dark = mat('#22212e', { roughness: 0.4 })
    monitor.add(cylinder(0.14, 0.16, 0.03, dark, 0, 0.015, 0))
    monitor.add(box(0.06, 0.3, 0.05, dark, 0, 0.17, -0.02))
    monitor.add(box(0.96, 0.6, 0.05, dark, 0, 0.6, 0, 0.02))
    const tex = codeTex.clone()
    tex.needsUpdate = true
    track(tex)
    const screenMat = new THREE.MeshStandardMaterial({
      color: '#000000', emissive: '#ffffff', emissiveMap: tex, emissiveIntensity: 0.05, roughness: 0.3
    })
    const screen = new THREE.Mesh(new THREE.PlaneGeometry(0.88, 0.52), screenMat)
    screen.position.set(0, 0.6, 0.027)
    monitor.add(screen)
    g.add(monitor)
    screens.push(screenMat)
    code.push(tex)
  }

  const glow = new THREE.PointLight('#79c0ff', 0, 3.2, 2)
  glow.position.set(0, 1.4, 0.4)
  g.add(glow)
  // The desk group is turned by facing + PI, so PI here gives the chair
  // the sitter's own facing (its back behind the sitter).
  g.add(chair(0, CHAIR_GAP, Math.PI, '#5b5480'))
  scene.add(g)
  return { place, screens, code, glow }
}

// ---- Characters (small robots) ----
interface CharacterView {
  root: THREE.Group
  body: THREE.Group
  head: THREE.Group
  legs: [THREE.Group, THREE.Group]
  arms: [THREE.Group, THREE.Group]
  eyes: THREE.Mesh[]
  ring: THREE.Mesh
  ringMat: THREE.MeshBasicMaterial
  tag: HTMLDivElement
  tagStatus: HTMLSpanElement
  bubble: HTMLDivElement
  alertObj: CSS2DObject
  heading: number
  lastPos: Point | null
  blinkAt: number
  status: CharacterStatus | null
  bubbleText: string | null
}

function limb(w: number, h: number, d: number, material: THREE.Material, pivotY: number, x: number) {
  const pivot = new THREE.Group()
  pivot.position.set(x, pivotY, 0)
  pivot.add(box(w, h, d, material, 0, -h / 2, 0, Math.min(w, d) * 0.4))
  return pivot
}

function buildCharacter(scene: THREE.Scene, name: string): CharacterView {
  const colour = COLOURS[name] ?? OTHER_COLOUR
  const root = new THREE.Group()
  const body = new THREE.Group()
  root.add(body)
  const shell = mat(colour, { roughness: 0.45 })
  const white = mat('#f1f3f8', { roughness: 0.35 })
  const dark = mat('#1d1b2b', { roughness: 0.25, metalness: 0.2 })

  const legs: [THREE.Group, THREE.Group] = [limb(0.17, 0.45, 0.2, dark, 0.45, -0.15), limb(0.17, 0.45, 0.2, dark, 0.45, 0.15)]
  body.add(...legs)
  body.add(box(0.62, 0.6, 0.44, shell, 0, 0.76, 0, 0.12)) // torso
  body.add(box(0.36, 0.26, 0.04, white, 0, 0.78, 0.22, 0.03)) // chest panel
  const arms: [THREE.Group, THREE.Group] = [limb(0.14, 0.44, 0.16, shell, 1.0, -0.4), limb(0.14, 0.44, 0.16, shell, 1.0, 0.4)]
  body.add(...arms)

  const head = new THREE.Group()
  head.position.y = 1.36
  head.add(box(0.74, 0.54, 0.58, white, 0, 0, 0, 0.16))
  head.add(box(0.58, 0.3, 0.05, dark, 0, -0.01, 0.28, 0.06)) // visor
  const eyeMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(colour).lerp(new THREE.Color('#ffffff'), 0.65) })
  const eyes: THREE.Mesh[] = []
  for (const ex of [-0.13, 0.13]) {
    const eye = new THREE.Mesh(new RoundedBoxGeometry(0.09, 0.13, 0.02, 2, 0.03), eyeMat)
    eye.position.set(ex, 0, 0.315)
    head.add(eye)
    eyes.push(eye)
  }
  head.add(cylinder(0.018, 0.018, 0.2, dark, 0, 0.36, 0))
  const tip = new THREE.Mesh(new THREE.SphereGeometry(0.06, 16, 12), new THREE.MeshStandardMaterial({ color: colour, emissive: colour, emissiveIntensity: 1.2 }))
  tip.position.y = 0.48
  head.add(tip)
  body.add(head)

  // Status ring on the floor.
  const ringMat = new THREE.MeshBasicMaterial({ color: colour, transparent: true, opacity: 0.35, depthWrite: false })
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.42, 0.52, 40), ringMat)
  ring.rotation.x = -Math.PI / 2
  ring.position.y = 0.02
  root.add(ring)

  // HTML labels (crisp text, follow the robot on screen): the speech bubble
  // stacked on top of the name tag, anchored at its bottom above the head.
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
  labelObj.position.y = 2.05
  root.add(labelObj)

  const alert = document.createElement('div')
  alert.className = 'office3d-alert'
  alert.textContent = '!'
  const alertObj = new CSS2DObject(alert)
  alertObj.position.set(0.55, 1.9, 0)
  alertObj.visible = false
  root.add(alertObj)

  root.scale.setScalar(ROBOT_SCALE)
  root.visible = false
  scene.add(root)
  return {
    root, body, head, legs, arms, eyes, ring, ringMat, tag, tagStatus, bubble, alertObj,
    heading: 0, lastPos: null, blinkAt: 0, status: null, bubbleText: null
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
  const t = nowMs / 1000

  // Facing: along the walk while walking, else the place's direction.
  let target = view.heading
  if (c.walk && view.lastPos) {
    const dx = pos.x - view.lastPos.x
    const dz = pos.z - view.lastPos.z
    if (Math.hypot(dx, dz) > 1e-4) target = Math.atan2(dx, dz)
  } else if (!c.walk) {
    target = placeFacing(c.desk)
  }
  view.heading = view.lastPos ? turnTowards(view.heading, target, dt * 12) : target
  view.lastPos = pos
  view.root.position.set(pos.x, 0, pos.z)
  view.root.rotation.y = view.heading

  const [legL, legR] = view.legs
  const [armL, armR] = view.arms
  let bob = 0
  let headTilt = 0
  let headTurn = 0
  if (status === 'walking') {
    const s = Math.sin(t * 11)
    legL.rotation.x = s * 0.6
    legR.rotation.x = -s * 0.6
    armL.rotation.x = -s * 0.5
    armR.rotation.x = s * 0.5
    bob = Math.abs(Math.cos(t * 11)) * 0.06
  } else {
    // Sitting: legs forward under the desk / table.
    legL.rotation.x = legR.rotation.x = -Math.PI / 2
    if (status === 'working') {
      armL.rotation.x = -1.15 + Math.sin(t * 22) * 0.12
      armR.rotation.x = -1.15 + Math.sin(t * 22 + Math.PI) * 0.12
      headTilt = 0.12
    } else if (status === 'talking') {
      armL.rotation.x = -0.3
      armR.rotation.x = -0.9 + Math.sin(t * 6) * 0.35
      headTilt = Math.sin(t * 9) * 0.08
      headTurn = Math.sin(t * 2.3) * 0.15
    } else {
      armL.rotation.x = armR.rotation.x = -0.15
      headTurn = Math.sin(t * 0.7 + c.name.length) * 0.25
      bob = Math.sin(t * 2) * 0.01
    }
  }
  view.body.position.y = bob
  view.head.rotation.x = headTilt
  view.head.rotation.y = headTurn

  // Blink every few seconds.
  if (nowMs - view.blinkAt > 3000 + (c.name.length % 5) * 500) view.blinkAt = nowMs
  const blinking = nowMs - view.blinkAt < 140
  for (const eye of view.eyes) eye.scale.y = blinking ? 0.15 : 1

  // Ring: pulses while working, brighter while talking.
  view.ringMat.opacity = status === 'working' ? 0.45 + Math.sin(t * 6) * 0.3 : status === 'talking' ? 0.7 : 0.25
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
const VIEW_AZIMUTH = THREE.MathUtils.degToRad(38) // from +z towards +x
const VIEW_ELEVATION = THREE.MathUtils.degToRad(34)
// Points that must stay in frame (floor corners, wall tops, label headroom).
const FRAME_POINTS = [
  [-FLOOR_X, -0.5, -FLOOR_Z], [FLOOR_X, -0.5, -FLOOR_Z], [-FLOOR_X, -0.5, FLOOR_Z], [FLOOR_X, -0.5, FLOOR_Z],
  [-FLOOR_X, WALL_H + 0.2, -FLOOR_Z], [FLOOR_X, WALL_H + 0.2, -FLOOR_Z], [-FLOOR_X, WALL_H + 0.2, FLOOR_Z]
].map(([x, y, z]) => new THREE.Vector3(x, y, z))

function fitCamera(camera: THREE.OrthographicCamera, aspect: number) {
  const target = new THREE.Vector3(0, 0.6, 0)
  const dir = new THREE.Vector3(
    Math.sin(VIEW_AZIMUTH) * Math.cos(VIEW_ELEVATION),
    Math.sin(VIEW_ELEVATION),
    Math.cos(VIEW_AZIMUTH) * Math.cos(VIEW_ELEVATION)
  )
  camera.position.copy(target).addScaledVector(dir, 40)
  camera.lookAt(target)
  camera.updateMatrixWorld()
  const inv = camera.matrixWorldInverse
  let minX = Infinity; let maxX = -Infinity; let minY = Infinity; let maxY = -Infinity
  for (const p of FRAME_POINTS) {
    const v = p.clone().applyMatrix4(inv)
    minX = Math.min(minX, v.x); maxX = Math.max(maxX, v.x)
    minY = Math.min(minY, v.y); maxY = Math.max(maxY, v.y)
  }
  const pad = 0.2
  let w = maxX - minX + pad * 2
  let h = maxY - minY + pad * 2
  const cx = (minX + maxX) / 2
  const cy = (minY + maxY) / 2
  if (w / h > aspect) h = w / aspect
  else w = h * aspect
  camera.left = cx - w / 2
  camera.right = cx + w / 2
  camera.top = cy + h / 2
  camera.bottom = cy - h / 2
  camera.near = 1
  camera.far = 100
  camera.updateProjectionMatrix()
}

// ---- Public API ----
export interface OfficeScene {
  draw(state: OfficeState, frameMs: number): void
  dispose(): void
}

// Throws if WebGL is not available (the caller shows a message).
export function createOfficeScene(container: HTMLElement): OfficeScene {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
  renderer.setClearColor(0x000000, 0)
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.05
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
  const track = (t: THREE.Texture) => { textures.push(t) }

  // Lights: cool sky + warm sun from the front right, soft shadows.
  scene.add(new THREE.HemisphereLight('#c8d2ff', '#4a3a2c', 1.4))
  const sun = new THREE.DirectionalLight('#fff1dc', 2.6)
  sun.position.set(9, 16, 10)
  sun.castShadow = true
  sun.shadow.mapSize.set(2048, 2048)
  sun.shadow.camera.left = -13
  sun.shadow.camera.right = 13
  sun.shadow.camera.top = 10
  sun.shadow.camera.bottom = -10
  sun.shadow.camera.near = 1
  sun.shadow.camera.far = 50
  sun.shadow.bias = -0.0004
  sun.shadow.normalBias = 0.02
  sun.shadow.radius = 4
  scene.add(sun)
  const fill = new THREE.DirectionalLight('#b6a8ff', 0.6)
  fill.position.set(-10, 8, 4)
  scene.add(fill)

  buildRoom(scene, track)
  const codeTex = codeTexture()
  track(codeTex)
  const desks = Object.entries(DESKS).map(([place, spot]) => buildDesk(scene, place, spot, codeTex, track))

  const characters = new Map<string, CharacterView>()

  function resize() {
    const w = Math.max(1, container.clientWidth)
    const h = Math.max(1, container.clientHeight)
    renderer.setSize(w, h, false)
    labels.setSize(w, h)
    fitCamera(camera, w / h)
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

    // Monitors: off when nobody sits there, soft when the owner is idle,
    // scrolling code in the owner's colour while working.
    for (const desk of desks) {
      const owner = Object.values(state.characters).find(c => c.present && !c.walk && c.desk === desk.place)
      const status = owner ? characterStatus(state, owner.name) : null
      const colour = owner ? COLOURS[owner.name] ?? OTHER_COLOUR : '#79c0ff'
      const working = status === 'working'
      for (const [i, screen] of desk.screens.entries()) {
        const target = working ? 1.6 : owner ? 0.55 : 0.04
        screen.emissiveIntensity += (target - screen.emissiveIntensity) * Math.min(1, dt * 8)
        if (working) desk.code[i]!.offset.y -= dt * 0.35
      }
      desk.glow.color.set(colour)
      const glowTarget = working ? 2.2 + Math.sin(frameMs / 90) * 0.3 : owner ? 0.5 : 0
      desk.glow.intensity += (glowTarget - desk.glow.intensity) * Math.min(1, dt * 8)
    }

    renderer.render(scene, camera)
    labels.render(scene, camera)
  }

  function dispose() {
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

  return { draw, dispose }
}
